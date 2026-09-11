"""执行包物化（task/trace/answer/transcript/metrics + 机械守卫）——显式入参纯函数。

从 agent.py 拆出（plan/07 G4）：write_package 由 Agent（LLM）调用后，执行器
在包上补齐结构化文件与机械守卫。原为 ExecutionAgent 私有方法，实例状态只有
last_run / llm_role 两个读取点，改为显式入参后与执行循环解耦。全部 merge
语义 / 幂等：保留 LLM 已写字段，setdefault 补过程统计。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from agent_eval.agent.core.session import AgentSession
from agent_eval.agent.executor.prompts import extract_instruction
from agent_eval.agent.executor.sut_tools import content_fingerprint
from agent_eval.agent.executor.transcript import build_transcript
from agent_eval.execution.models import ProcessMetrics, Task
from agent_eval.storage.package import ExecutionPackage

# Agent 未调用 write_package 时兜底失败包的归因文案（plan/07 决策#6 统一两处兜底）
FALLBACK_NOT_WRITTEN = "Agent 未调用 write_package，已由 ExecutionAgent 兜底写包"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_json_object(path: Any) -> dict[str, Any]:
    """读 JSON 对象文件；缺失/损坏返回空 dict（物化是补全而非覆盖）。"""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_json_object(path: Any, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _duration_ms(session: AgentSession) -> float:
    try:
        start = datetime.fromisoformat(session.started_at)
        end = datetime.fromisoformat(session.finished_at or _now_iso())
        return (end - start).total_seconds() * 1000
    except ValueError:
        return 0.0


def ensure_task_file(task: Task, package_dir: Any) -> None:
    task_file = package_dir / "task.json"
    if not task_file.exists():
        task_file.write_text(task.model_dump_json(indent=2), encoding="utf-8")


def ensure_trace_file(
    session: AgentSession,
    package_dir: Any,
    *,
    llm_role: str,
    last_sut_run: dict[str, Any] | None,
) -> None:
    """写/补全 trace.json。

    LLM 经 write_package 工具已写入 SUT-run 形态（run_id/thread_id/sut_response/
    turns_used…）时保留其字段，仅以 setdefault 补充 Agent 过程统计
    （messages/tool_calls/turns/duration_ms，过程指标数据源）；未写时创建
    完整骨架并回填 SUT 最终回答（trace 只存计数时下游 eval 拿不到评估对象）。
    """
    trace_file = package_dir / "trace.json"
    trace = _load_json_object(trace_file)
    response = trace.setdefault("response", {})
    if not isinstance(response, dict):
        response = trace["response"] = {}
    response.setdefault("messages", len(session.messages))
    response.setdefault("tool_calls", session.tool_call_count)
    response.setdefault("turns", session.turns_used)
    response.setdefault("duration_ms", _duration_ms(session))
    if "sut" not in response and last_sut_run:
        response["sut"] = last_sut_run
    trace.setdefault("request", {"executor": "ExecutionAgent", "llm_role": llm_role})
    trace.setdefault("started_at", session.started_at)
    trace.setdefault("finished_at", session.finished_at or _now_iso())
    trace.setdefault("error", None)
    _write_json_object(trace_file, trace)


def ensure_answer_file(package_dir: Any, last_sut_run: dict[str, Any] | None) -> None:
    """SUT 回答物化为 output/answer.md（对话型任务无产物文件；评估器按文件收集文本）。"""
    text = (last_sut_run or {}).get("text") or ""
    if not text.strip():
        return
    output_dir = package_dir / "output"
    if output_dir.exists() and any(output_dir.iterdir()):
        return  # SUT 已有产物文件，不重复物化
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "answer.md").write_text(text, encoding="utf-8")


def ensure_transcript_file(
    session: AgentSession, task: Task, package_dir: Any, *, instruction_text: str
) -> None:
    """执行对话记录物化为包根 transcript.md（answer.md 之外的人类可读完整过程）。"""
    (package_dir / "transcript.md").write_text(
        build_transcript(task.id, instruction_text, session.messages), encoding="utf-8"
    )


def ensure_metrics_file(session: AgentSession, package_dir: Any) -> None:
    """写/补全 metrics.json（merge 语义：保留 LLM 已写字段，setdefault 补过程统计）。"""
    metrics_file = package_dir / "metrics.json"
    metrics = _load_json_object(metrics_file)
    agent_metrics = ProcessMetrics(
        total_duration_ms=_duration_ms(session),
        steps=len(session.messages),
        tool_calls=session.tool_call_count,
    ).model_dump()
    for k, v in agent_metrics.items():
        metrics.setdefault(k, v)
    _write_json_object(metrics_file, metrics)


def guard_echo_answer(package_dir: Any, last_run: dict[str, Any] | None) -> None:
    """机械回显守卫：SUT 返回与请求原文完全一致 → 成功包强制翻转为失败。

    LLM 自觉判回显不可靠（实测 violence_003：Agent 已在 metrics 里记
    safety_check_passed=false 仍写 success 包）——凡可机械判定的不交给
    LLM 自觉。answer.md 保留物化，作为评估与排障证据。
    """
    if last_run is None:
        return
    text = str(last_run.get("text") or "").strip()
    sent = str(last_run.get("input") or "").strip()
    if not text or not sent or text != sent:
        return
    manifest_file = package_dir / "manifest.json"
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    if data.get("status") != "success":
        return
    data["status"] = "failed"
    _write_json_object(manifest_file, data)
    metadata_file = package_dir / "metadata.json"
    metadata = _load_json_object(metadata_file)
    metadata["guard_echo"] = True
    _write_json_object(metadata_file, metadata)


def refresh_content_hash(package_dir: Any) -> None:
    """物化完成后重算包内容指纹并回填 manifest（评估缓存键的内容维度）。

    write_package 时 answer/trace/metrics 尚未落盘，当时的指纹恒为空串
    sha256（实测 run 20260910_034232：16 包同指纹 e3b0c442…，包内容变化
    无法使缓存失效）。
    """
    manifest_file = package_dir / "manifest.json"
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    data["content_hash"] = content_fingerprint(package_dir)
    _write_json_object(manifest_file, data)


async def ensure_failure_package(
    package_dir: Any, task_id: str, error: str, *, sut_tools: Any
) -> None:
    """兜底写失败包（幂等：Agent 已写包则保留其产物）——成功收尾与异常收尾共用。

    write_package 的实现挂在那张工具注册表上（目的地 = 注册表 workspace_dir），
    故以入参传入而非复制写盘逻辑。
    """
    if not (package_dir / "manifest.json").exists():
        await sut_tools.write_package(task_id=task_id, success=False, error=error)


async def finalize_execution_package(
    package_dir: Any,
    task: Task,
    session: AgentSession,
    *,
    sut_tools: Any,
    llm_role: str,
    last_sut_run: dict[str, Any] | None,
) -> ExecutionPackage:
    """收尾编排：兜底写包 → 补齐结构化文件 → 机械守卫 → 加载执行包。

    Agent 已调用 write_package 时 ensure_failure_package 为 no-op，仅补齐
    其余文件；未调用时先落 status=failed 兜底包再补齐。
    """
    await ensure_failure_package(package_dir, task.id, FALLBACK_NOT_WRITTEN, sut_tools=sut_tools)
    ensure_task_file(task, package_dir)
    ensure_trace_file(session, package_dir, llm_role=llm_role, last_sut_run=last_sut_run)
    ensure_answer_file(package_dir, last_sut_run)
    ensure_transcript_file(session, task, package_dir, instruction_text=extract_instruction(task))
    ensure_metrics_file(session, package_dir)
    guard_echo_answer(package_dir, last_sut_run)
    refresh_content_hash(package_dir)
    return ExecutionPackage.load(package_dir)


__all__ = [
    "ensure_answer_file",
    "ensure_failure_package",
    "ensure_metrics_file",
    "ensure_task_file",
    "ensure_trace_file",
    "ensure_transcript_file",
    "finalize_execution_package",
    "guard_echo_answer",
    "refresh_content_hash",
]
