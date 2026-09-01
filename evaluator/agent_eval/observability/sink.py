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


def _content_type_for(f: Path) -> str:
    """按文件后缀给语义化 Content-Type（前端据 contentType/kind 分栏与渲染）。"""
    suffix = f.suffix.lower()
    if suffix in (".html", ".htm"):
        return "text/html"
    if suffix == ".json":
        return "application/json"
    if suffix == ".md":
        return "text/markdown"
    return "text/plain"


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
    def flush(
        self,
        result: EvalResult,
        *,
        run_workspace: Path | None = None,
        package_dir: Path | str | None = None,
    ) -> SinkReport:
        if not self.cfg.enabled:
            return SinkReport(enabled=False)

        report = SinkReport(enabled=True)
        try:
            # 先重放历史积压
            report.replayed = self.queue.replay(self.client, batch=self.cfg.queue_replay_batch).get(
                "sent", 0
            )

            events = self._build_events(result, run_workspace=run_workspace, report=report)

            # 上传源文件（按样本归属；output/ 产物 + 执行包技术文件分类）
            if package_dir and result.samples:
                src_events = self._upload_package_artifacts(
                    Path(package_dir),
                    result.run_id or result.report.run_id,
                    result.samples,
                    report,
                )
                events.extend(src_events)

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
                mode=result.mode,
                rule_set_version=result.rule_set_version or None,
                sut_version=result.sut_version or None,
                rule_set=result.rule_set,
                scenario_config=result.scenario_config,
                langfuse_trace_id=langfuse[0],
                langfuse_host=langfuse[1],
                summary_report=result.summary_report,
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
                    "external_sample_id": external_sample_id,
                    "kind": kind,
                    "name": original_name,
                    "content_type": content_type,
                }
            )
            self.client.upload_file(local_path, presigned, content_type)
            report.artifacts_uploaded += 1
            object_key: str | None = presigned["object_key"]
            return object_key
        except Exception as exc:  # noqa: BLE001
            report.artifacts_failed += 1
            self.log.warning("sink.artifact.upload_failed", path=str(local_path), error=str(exc))
            return None

    def _upload_source_files(
        self,
        package_dir: Path,
        external_run_id: str,
        external_sample_id: str,
        report: SinkReport,
    ) -> list[dict[str, Any]]:
        """上传单个样本执行包的产物（output/ → kind=output；包根技术 json → kind=trace）。"""
        events: list[dict[str, Any]] = []

        def _upload(files: list[tuple[Path, str, str]], kind: str) -> None:
            """files: [(文件, 相对名, 相对根)]，按后缀给 contentType。"""
            for f, rel_name, rel_root in files:
                ct = _content_type_for(f)
                object_key = self._upload_artifact(
                    f,
                    external_run_id=external_run_id,
                    external_sample_id=external_sample_id,
                    kind=kind,
                    content_type=ct,
                    original_name=rel_name,
                    report=report,
                )
                if object_key:
                    events.append(
                        build_artifact_event(
                            external_run_id=external_run_id,
                            external_sample_id=external_sample_id,
                            kind=kind,
                            object_key=object_key,
                            content_type=ct,
                            size_bytes=f.stat().st_size,
                            original_name=rel_name,
                        )
                    )
                del rel_root  # rel_root 仅为语义清晰保留

        # ① 评测结果产物：output/ 下全部文件（SUT 产出，前端「原始文档」栏）
        output_dir = package_dir / "output"
        if output_dir.is_dir():
            # output/ 已由 build_package 按场景 format 门控预过滤，全量上传（任意场景均可预览）
            out_files = [
                (f, str(f.relative_to(output_dir)), str(output_dir))
                for f in sorted(output_dir.rglob("*"))
                if f.is_file()
            ]
            _upload(out_files, kind="output")

        # ② 执行包技术文件：包根 manifest/metadata/metrics/task/trace.json（前端「执行 Trace」栏）
        tech_files = [
            (f, f.name, str(package_dir))
            for f in sorted(package_dir.glob("*.json"))
            if f.is_file() and f.stem in ("manifest", "metadata", "metrics", "task", "trace")
        ]
        _upload(tech_files, kind="trace")

        # 兼容：无 output/ 且无技术文件（极简包/异常布局）→ 扫整包为 output
        if not events:
            for f in sorted(package_dir.rglob("*")):
                if f.is_file():
                    rel_name = str(f.relative_to(package_dir))
                    ct = _content_type_for(f)
                    object_key = self._upload_artifact(
                        f,
                        external_run_id=external_run_id,
                        external_sample_id=external_sample_id,
                        kind="output",
                        content_type=ct,
                        original_name=rel_name,
                        report=report,
                    )
                    if object_key:
                        events.append(
                            build_artifact_event(
                                external_run_id=external_run_id,
                                external_sample_id=external_sample_id,
                                kind="output",
                                object_key=object_key,
                                content_type=ct,
                                size_bytes=f.stat().st_size,
                                original_name=rel_name,
                            )
                        )
        return events

    def _upload_package_artifacts(
        self,
        package_dir: Path,
        external_run_id: str,
        samples: list[Any],
        report: SinkReport,
    ) -> list[dict[str, Any]]:
        """按样本上传执行包产物：单包目录归唯一样本；包集合目录逐样本各取各的子目录。

        多样本 run（runs/{run_id}/packages/{task_id}/…）此前只把全部文件绑到
        samples[0]——本方法保证每个样本的产物正确归属自身。
        """
        pdir = Path(package_dir)
        events: list[dict[str, Any]] = []
        if (pdir / "manifest.json").exists():
            # 单包目录 → 唯一样本
            if samples:
                events.extend(
                    self._upload_source_files(pdir, external_run_id, samples[0].sample_id, report)
                )
            return events
        # 包集合目录：逐样本子目录（子目录名 = task_id = sample_id）
        for sample in samples:
            sub = pdir / sample.sample_id
            if sub.is_dir():
                events.extend(
                    self._upload_source_files(sub, external_run_id, sample.sample_id, report)
                )
        return events

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
