"""ResultSink：编排 拼装事件 → 上传制品 → 发送事件 → 失败入队（docs/arch/09 §8）。

调用时机：cli.py 的 eval 命令，在 flush_traces() 之后调 ResultSink.flush(eval_result)。
未配置凭据（enabled=False）→ flush 直接跳过，零开销。

流程：
  1. 拼装 run / sample / constraint 事件（制品上传后回填 object_key）。
  2. 上传制品（presigned PUT）；上传失败的引用留 None（解耦，后续补传）。
  3. 按 batch_max_events 分批发送；发送失败 → 入 SQLite 队列。
  4. 启动时重放队列里积压的事件。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_eval.core.logging import get_logger
from agent_eval.observability.client import IngestionClient, IngestionError
from agent_eval.observability.config import ObservabilityConfig, load_config
from agent_eval.observability.events import (
    build_artifact_event,
    build_constraint_event,
    build_run_event,
    build_sample_event,
    discover_artifacts,
)
from agent_eval.observability.queue import IngestQueue

if TYPE_CHECKING:
    from agent_eval.orchestrator.orchestrator import EvalResult


@dataclass
class SinkReport:
    """一次 flush 的结果摘要（供 CLI 打印）。"""

    enabled: bool
    sent: int = 0
    queued: int = 0
    artifacts_uploaded: int = 0
    artifacts_failed: int = 0
    replayed: int = 0
    error: str | None = None


class ResultSink:
    """评估结果 → 可观测平台。"""

    def __init__(
        self,
        config: ObservabilityConfig | None = None,
        *,
        client: IngestionClient | None = None,
        queue: IngestQueue | None = None,
    ) -> None:
        self.cfg = config or load_config()
        self.log = get_logger("observability.sink")
        self.client = client or IngestionClient(self.cfg)
        self.queue = queue or IngestQueue(
            self.cfg.queue_dir,
            max_attempts=self.cfg.queue_max_attempts,
        )

    # ── 主入口 ──
    def flush(self, result: EvalResult, *, run_workspace: Path | None = None) -> SinkReport:
        if not self.cfg.enabled:
            return SinkReport(enabled=False)

        report = SinkReport(enabled=True)
        try:
            # 先重放历史积压
            report.replayed = self.queue.replay(self.client, batch=self.cfg.queue_replay_batch).get(
                "sent", 0
            )

            events = self._build_events(result, run_workspace=run_workspace, report=report)
            report.sent, report.queued = self._send_in_batches(events)
        except Exception as exc:  # noqa: BLE001 — flush 不应让 eval 命令失败
            report.error = str(exc)
            self.log.error("sink.flush.failed", error=str(exc))
        return report

    # ── 事件拼装 + 制品上传 ──
    def _build_events(
        self,
        result: EvalResult,
        *,
        run_workspace: Path | None,
        report: SinkReport,
    ) -> list[dict[str, Any]]:
        run_id = result.run_id or result.report.run_id
        langfuse = self._langfuse_meta()

        events: list[dict[str, Any]] = [
            build_run_event(
                result.report,
                run_id=run_id,
                langfuse_trace_id=langfuse[0],
                langfuse_host=langfuse[1],
            )
        ]

        for sample in result.samples:
            events.append(build_sample_event(sample, external_run_id=run_id))

            # 制品上传（judge 记录 + 截图）
            base_dir = run_workspace or Path.cwd()
            for art in discover_artifacts(sample, base_dir=base_dir):
                object_key = self._upload_artifact(
                    art["path"],
                    external_run_id=run_id,
                    external_sample_id=sample.sample_id,
                    kind=art["kind"],
                    content_type=art["content_type"],
                    original_name=art["path"].name,
                    report=report,
                )
                if object_key:
                    events.append(
                        build_artifact_event(
                            external_run_id=run_id,
                            external_sample_id=sample.sample_id,
                            kind=art["kind"],
                            object_key=object_key,
                            content_type=art["content_type"],
                            size_bytes=art["path"].stat().st_size,
                            original_name=art["path"].name,
                            linked_constraint_id=art.get("linked_constraint_id"),
                        )
                    )

            # 约束事件（judge_record_object_key 暂留 None，由上面的 artifact 事件回填）
            for stage in sample.stage_results.values():
                for c in stage.constraint_results:
                    events.append(
                        build_constraint_event(
                            c,
                            external_run_id=run_id,
                            external_sample_id=sample.sample_id,
                        )
                    )

        return events

    def _upload_artifact(
        self,
        local_path: Path,
        *,
        external_run_id: str,
        external_sample_id: str,
        kind: str,
        content_type: str,
        original_name: str,
        report: SinkReport,
    ) -> str | None:
        """申请 presigned 并上传。失败返回 None（制品与事件解耦，不阻塞）。"""
        try:
            presigned = self.client.presign_put(
                {
                    "external_run_id": external_run_id,
                    "kind": kind,
                    "name": original_name,
                    "content_type": content_type,
                }
            )
            self.client.upload_file(local_path, presigned, content_type)
            report.artifacts_uploaded += 1
            return presigned["object_key"]
        except Exception as exc:  # noqa: BLE001
            report.artifacts_failed += 1
            self.log.warning("sink.artifact.upload_failed", path=str(local_path), error=str(exc))
            return None

    # ── 分批发送 ──
    def dispatch(self, events: list[dict[str, Any]]) -> tuple[int, int]:
        """发送预拼装的事件（供 upload 回填子命令复用）。返回 (sent, queued)。"""
        # 启动时顺带重放积压
        try:
            self.queue.replay(self.client, batch=self.cfg.queue_replay_batch)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("sink.dispatch.replay_failed", error=str(exc))
        return self._send_in_batches(events)

    def _send_in_batches(self, events: list[dict[str, Any]]) -> tuple[int, int]:
        batch = max(1, self.cfg.batch_max_events)
        sent = queued = 0
        for i in range(0, len(events), batch):
            chunk = events[i : i + batch]
            try:
                resp = self.client.post_ingest(chunk)
                sent += resp.accepted
                self.log.info(
                    "sink.ingest.ok",
                    accepted=resp.accepted,
                    duplicates=resp.duplicates,
                    errors=len(resp.errors),
                )
                if resp.errors:
                    self.log.warning("sink.ingest.partial_errors", errors=resp.errors[:5])
            except (IngestionError, Exception) as exc:  # noqa: BLE001
                # 任意失败 → 整批入队，后续重放（后端幂等，重复安全）
                self.queue.enqueue(chunk)
                queued += len(chunk)
                self.log.warning("sink.ingest.queued", events=len(chunk), error=str(exc))
        return sent, queued

    # ── Langfuse trace 透传（D4）──
    def _langfuse_meta(self) -> tuple[str | None, str | None]:
        try:
            from agent_eval.llm.tracing import get_langfuse

            lf = get_langfuse()
            if lf is None:
                return None, None
        except Exception:  # noqa: BLE001
            return None, None
        # tracing.py 当前未暴露「当前 trace_id」；有 langfuse 客户端时回填 host，trace_id 留待后续
        import os

        host = os.environ.get("LANGFUSE_HOST")
        return None, host


def flush(
    eval_result: EvalResult,
    *,
    upload_override: bool | None = None,
    run_workspace: Path | None = None,
) -> SinkReport:
    """便捷入口：读 env 构建 ResultSink 并 flush。"""
    sink = ResultSink(load_config(upload_override=upload_override))
    return sink.flush(eval_result, run_workspace=run_workspace)
