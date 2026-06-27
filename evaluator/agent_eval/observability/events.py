"""评估器模型 → 摄取事件映射（docs/arch/09 §8.2）。

统一以**事件 schema** 字段名为准输出（与 agent_eval/observability/schemas/ingest.event.v1.json 一致），
兼容 dataclass 与序列化 JSON 两种来源，确保后端只认 schema。

事件类型：run / sample / constraint / artifact。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from agent_eval.evaluation.models import (
    ConstraintResult,
    MetricsReport,
    SampleResult,
)


def _new_event_id() -> str:
    return uuid.uuid4().hex


def build_run_event(
    report: MetricsReport,
    *,
    run_id: str | None = None,
    mode: str = "eval_only",
    status: str = "completed",
    finished_at: str | None = None,
    rule_set_version: str | None = None,
    sut_version: str | None = None,
    langfuse_trace_id: str | None = None,
    langfuse_host: str | None = None,
) -> dict[str, Any]:
    """MetricsReport → run 事件。"""
    external_run_id = run_id or report.run_id
    return {
        "event_id": _new_event_id(),
        "type": "run",
        "data": {
            "external_run_id": external_run_id,
            "mode": mode,
            "status": status,
            "finished_at": finished_at,
            "metrics": {
                "DR": report.dr,
                "CPR": report.cpr,
                "avg_reward": report.avg_reward,
                "condR": report.cond_r,
                "avg_time_ms": report.avg_time_ms,
            },
            "total_samples": report.total_samples,
            "rule_set_version": rule_set_version,
            "sut_version": sut_version,
            "failure_breakdown": dict(report.failure_breakdown) or None,
            "thresholds": dict(report.thresholds) or None,
            "langfuse_trace_id": langfuse_trace_id,
            "langfuse_host": langfuse_host,
        },
    }


def build_sample_event(
    sample: SampleResult,
    *,
    external_run_id: str,
) -> dict[str, Any]:
    """SampleResult → sample 事件。dimensions 暂不映射（scores.json 维度，预留）。"""
    return {
        "event_id": _new_event_id(),
        "type": "sample",
        "data": {
            "external_run_id": external_run_id,
            "external_sample_id": sample.sample_id,
            "content_hash": sample.content_hash,
            "status": sample.status.value,
            "s_format": sample.s_format,
            "s_common": sample.s_common,
            "s_soft": sample.s_soft,
            "s_pref": sample.s_pref,
            "reward": sample.reward,
            "total_duration_ms": sample.total_duration_ms,
            "llm_calls": sample.llm_calls,
            "token_usage": sample.token_usage,
        },
    }


def build_constraint_event(
    constraint: ConstraintResult,
    *,
    external_run_id: str,
    external_sample_id: str,
    judge_record_object_key: str | None = None,
) -> dict[str, Any]:
    """ConstraintResult → constraint 事件。

    字段对齐（§8.2 注）：
      - status("pass"/"fail"/...) → passed(布尔)；status 同时直传（schema 约束枚举）。
      - judge_record_path（本地路径）→ judge_record_object_key（上传后替换，未上传为 None）。
    """
    return {
        "event_id": _new_event_id(),
        "type": "constraint",
        "data": {
            "external_run_id": external_run_id,
            "external_sample_id": external_sample_id,
            "constraint_id": constraint.constraint_id,
            "rule_id": constraint.constraint_id,  # 约束 id 作为 rule 引用
            "name": constraint.name,
            "tier": constraint.tier.value,
            "status": constraint.status.value,
            "passed": constraint.status.value == "pass",
            "score": constraint.score,
            "raw_score": constraint.raw_score,
            "reason": constraint.reason,
            "details": dict(constraint.details) or None,
            "duration_ms": constraint.duration_ms,
            "judge_provider": constraint.judge_provider,
            "judge_model": constraint.judge_model,
            "judge_record_object_key": judge_record_object_key,
            "module_results": constraint.module_results,
        },
    }


def build_artifact_event(
    *,
    external_run_id: str,
    external_sample_id: str | None,
    kind: str,
    object_key: str,
    content_type: str,
    size_bytes: int,
    md5: str | None = None,
    original_name: str | None = None,
    linked_constraint_id: str | None = None,
) -> dict[str, Any]:
    """制品上传成功后生成 artifact 事件（引用 object_key）。"""
    return {
        "event_id": _new_event_id(),
        "type": "artifact",
        "data": {
            "external_run_id": external_run_id,
            "external_sample_id": external_sample_id,
            "kind": kind,
            "object_key": object_key,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "md5": md5,
            "original_name": original_name,
            "linked_constraint_id": linked_constraint_id,
        },
    }


# ── 制品发现：从 SampleResult / 评估上下文收集本地制品路径 ──
# ConstraintResult.judge_record_path 指向 judge 记录 JSON；screenshots 在 details["screenshot_paths"]。
def discover_artifacts(
    sample: SampleResult,
    *,
    base_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """收集一个 sample 的本地制品（judge 记录 + 截图），返回待上传清单。

    每项：{kind, path, content_type, linked_constraint_id?}。path 解析为绝对路径（base_dir 相对）。
    """
    out: list[dict[str, Any]] = []
    for stage in sample.stage_results.values():
        for c in stage.constraint_results:
            # judge 记录
            if c.judge_record_path:
                p = Path(c.judge_record_path)
                if not p.is_absolute() and base_dir is not None:
                    p = base_dir / p
                if p.exists():
                    out.append(
                        {
                            "kind": "judge_record",
                            "path": p,
                            "content_type": "application/json",
                            "linked_constraint_id": c.constraint_id,
                        }
                    )
            # 截图（视觉评估器写入 details["screenshot_paths"]）
            shots = c.details.get("screenshot_paths") if c.details else None
            if isinstance(shots, list):
                for sp in shots:
                    p = Path(str(sp))
                    if not p.is_absolute() and base_dir is not None:
                        p = base_dir / p
                    if p.exists():
                        out.append(
                            {
                                "kind": "screenshot",
                                "path": p,
                                "content_type": "image/png",
                                "linked_constraint_id": c.constraint_id,
                            }
                        )
    return out
