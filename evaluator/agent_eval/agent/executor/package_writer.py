"""执行包物化（task/trace/answer/transcript/metrics + 机械守卫）——显式入参纯函数。

从 agent.py 拆出：write_package 由 Agent（LLM）调用后，执行器
在包上补齐结构化文件与机械守卫。原为 ExecutionAgent 私有方法，实例状态只有
last_run / llm_role 两个读取点，改为显式入参后与执行循环解耦。全部 merge
语义 / 幂等：保留 LLM 已写字段，setdefault 补过程统计。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from agent_eval.agent.core.session import AgentSession
from agent_eval.agent.executor.ledger import EvidenceLedger
from agent_eval.agent.executor.prompts import extract_instruction
from agent_eval.agent.executor.sut_tools import content_fingerprint
from agent_eval.agent.executor.terminal import (
    classify_terminal_result,
    render_deliverable,
)
from agent_eval.agent.executor.transcript import build_transcript
from agent_eval.core.types import TerminalKind
from agent_eval.execution.models import ProcessMetrics, Task
from agent_eval.storage.package import ExecutionPackage

# Agent 未调用 write_package 时兜底失败包的归因文案
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
    error: str | None = None,
) -> None:
    """写/补全 trace.json。

    LLM 经 write_package 工具已写入 SUT-run 形态（run_id/thread_id/sut_response/
    turns_used…）时保留其字段，仅以 setdefault 补充 Agent 过程统计
    （messages/tool_calls/turns/duration_ms，过程指标数据源）；未写时创建
    完整骨架并回填 SUT 最终回答（trace 只存计数时下游 eval 拿不到评估对象）。

    error 非 None 时写入 trace.error（LLM 已写错误不覆盖）——write_package 的
    error 只进返回摘要不入包，异常收尾的真实错误只能由补齐链落盘。
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
    if not trace.get("error"):
        # 补齐语义：已有非空错误不覆盖；无错误时落 fallback（或骨架缺省 None）
        trace["error"] = error
    _write_json_object(trace_file, trace)


def ensure_answer_file(package_dir: Any, last_sut_run: dict[str, Any] | None) -> str:
    """SUT 终态交付物化为 output/answer.md（合同三）。

    交付物 = {text, output, questions} 三元全量渲染（宁可重复不可丢失）：
    text 是 SUT 发言；结构化 output 转 generic markdown；反问显式标注
    「待应答」——此前只渲染 text，text 停在播报时 answer.md 即播报（run
    20260916_074046 neg_001/sem_002）。返回渲染内容（空串=无交付证据），
    供守卫与测试判读；已有产物文件时不重复物化。
    """
    deliverable = render_deliverable(classify_terminal_result(last_sut_run))
    if not deliverable.strip():
        return ""
    output_dir = package_dir / "output"
    if output_dir.exists() and any(output_dir.iterdir()):
        return deliverable  # SUT 已有产物文件，不重复物化
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "answer.md").write_text(deliverable, encoding="utf-8")
    return deliverable


def ensure_transcript_file(
    session: AgentSession,
    task: Task,
    package_dir: Any,
    *,
    instruction_text: str,
    aborted_reason: str | None = None,
) -> None:
    """执行对话记录物化为包根 transcript.md（answer.md 之外的人类可读完整过程）。

    aborted_reason（异常收尾）非 None 时注入中断注记——图抛异常无会话可
    恢复，对话过程为空属预期，注明原因与日志位置防误判记录丢失。
    """
    (package_dir / "transcript.md").write_text(
        build_transcript(
            task.id, instruction_text, session.messages, aborted_reason=aborted_reason
        ),
        encoding="utf-8",
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


def guard_answered_manifest(package_dir: Any, last_run: dict[str, Any] | None) -> None:
    """机械作答守卫：SUT 真实作答且无执行错误 → failed 包强制翻回 success。

    success 只判定「执行是否完成」（SUT 是否真实作答），回答内容是否满足
    must_mention / 是否安全属评估面——LLM 把「SUT 未拒绝」当执行失败写包，
    评估引擎按半张卷子短路成 run_error 剔除分母，安全评测的核心失败信号
    恰好被吞（run 20260913_052011 violence_001：jxb 未拒绝报复请求，包被
    判 failed，安全指标测不到）。与 guard_echo 同款守卫惯例：metadata 记
    guard_answered 留痕。异常收尾不走本守卫（guard_aborted_manifest 负责
    强制 failed）；回显守卫后置，回显包仍会被翻回 failed。
    """
    text = str((last_run or {}).get("text") or "").strip()
    if not text:
        return
    trace = _load_json_object(package_dir / "trace.json")
    if trace.get("error"):
        return  # 执行面真实错误（如 SUT 配置层故障）——如实保留 failed
    manifest_file = package_dir / "manifest.json"
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    if data.get("status") != "failed":
        return
    data["status"] = "success"
    _write_json_object(manifest_file, data)
    metadata_file = package_dir / "metadata.json"
    metadata = _load_json_object(metadata_file)
    metadata["guard_answered"] = True
    _write_json_object(metadata_file, metadata)


def guard_deliverable(package_dir: Any, last_run: dict[str, Any] | None) -> None:
    """交付物守卫（合同三纵深防御）：无交付证据而对话非空 → 留痕。

    执行侧证据缺陷不裸穿透到评估结论：answer 空 + output 目录空 + 台账无
    交付观测，但 transcript 有完整对话——说明 SUT 交付在链路上丢失（而非
    SUT 未交付），metadata 记 degraded_evidence 供评估侧与 Web 端甄别。
    """
    if classify_terminal_result(last_run).kind is not TerminalKind.NO_EVIDENCE:
        return
    output_dir = package_dir / "output"
    if output_dir.exists() and any(output_dir.iterdir()):
        return
    transcript = package_dir / "transcript.md"
    try:
        if not transcript.read_text(encoding="utf-8").strip():
            return
    except OSError:
        return
    metadata_file = package_dir / "metadata.json"
    metadata = _load_json_object(metadata_file)
    metadata["degraded_evidence"] = True
    _write_json_object(metadata_file, metadata)


def guard_evaluable_abort(package_dir: Any, last_run: dict[str, Any] | None) -> None:
    """可评估性守卫（合同四）：异常收尾但 SUT 已交付 → 翻回可评估。

    执行会话崩 ≠ SUT 未交付（run 20260916_074046 media_001/002 等 5 样本：
    评估侧 LLM 断连崩会话，SUT 已完整交付正确答案，guard_aborted_manifest
    强制 failed 后引擎按 RUN_ERROR 剔出分母——reward 归零、门禁被翻转）。
    可评估性只看证据：last_run 终态分类为 delivered / interrupt_pending 即翻
    回 success 进评分分母；真实错误保留在 trace.error 与 error_summary。
    与 guard_echo 同款守卫惯例：metadata 记 guard_evaluable_abort 留痕。
    仅 abort 路径在 guard_aborted_manifest 之后调用（正常收尾由作答守卫负责）。
    """
    if not classify_terminal_result(last_run).evaluable:
        return
    manifest_file = package_dir / "manifest.json"
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    if data.get("status") != "failed":
        return
    data["status"] = "success"
    _write_json_object(manifest_file, data)
    metadata_file = package_dir / "metadata.json"
    metadata = _load_json_object(metadata_file)
    metadata["guard_evaluable_abort"] = True
    _write_json_object(metadata_file, metadata)


def guard_aborted_manifest(package_dir: Any, error: str) -> None:
    """异常收尾守卫：任务以异常终止时 manifest 强制翻为 failed。

    LLM 在异常前写入的 success 判定不可信（run 20260911_073626：三个产物
    下载全败、SUT text 只是「第 2 步完成」进度播报，仍写 success 包，随后
    保险丝熔断）——「自称成功但异常收场」的包不会被当失败重跑，评分却必然
    极低，排查方向被带偏。完成与否的最终裁决权在机械壳，不在执行 LLM。
    已 failed 不动（兜底包 / LLM 自判失败），metadata 记 guard_abort 留痕，
    与 guard_echo 同款守卫惯例。
    """
    metadata_file = package_dir / "metadata.json"
    metadata = _load_json_object(metadata_file)
    metadata["guard_abort"] = True
    manifest_file = package_dir / "manifest.json"
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    if data.get("status") == "success":
        data["status"] = "failed"
        _write_json_object(manifest_file, data)
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
    evidence: EvidenceLedger | None = None,
    fallback_error: str | None = None,
    close_reason: str = "finalized",
) -> ExecutionPackage:
    """收尾编排：兜底写包 → 补齐结构化文件 → 机械守卫 → 证据落盘 → 加载执行包。

    Agent 已调用 write_package 时 ensure_failure_package 为 no-op，仅补齐
    其余文件；未调用时先落 status=failed 兜底包再补齐（fallback_error 覆盖
    兜底归因——异常收尾把真实错误写进 manifest，而非「未写包」套话）。
    成功收尾与异常收尾共用本链：唯一差异是传入的 session 与 fallback_error
    ——后者额外触发 guard_aborted_manifest（LLM 已写的 success 判定强制
    翻 failed）。
    """
    await ensure_failure_package(
        package_dir, task.id, fallback_error or FALLBACK_NOT_WRITTEN, sut_tools=sut_tools
    )
    ensure_task_file(task, package_dir)
    ensure_trace_file(
        session, package_dir, llm_role=llm_role, last_sut_run=last_sut_run, error=fallback_error
    )
    ensure_answer_file(package_dir, last_sut_run)
    ensure_transcript_file(
        session,
        task,
        package_dir,
        instruction_text=extract_instruction(task),
        aborted_reason=fallback_error,
    )
    ensure_metrics_file(session, package_dir)
    guard_deliverable(package_dir, last_sut_run)
    guard_answered_manifest(package_dir, last_sut_run)
    guard_echo_answer(package_dir, last_sut_run)
    if fallback_error is not None:
        # 异常收尾（fallback_error 仅由 abort 路径传入）：LLM 已写的 success
        # 判定不可信，强制翻 failed——正常收尾不设此守卫
        guard_aborted_manifest(package_dir, fallback_error)
        # 合同四：强制 failed 之后按证据复核——SUT 已交付的
        # 样本翻回可评估（执行会话崩 ≠ SUT 未交付），后置保证异常语义不松
        guard_evaluable_abort(package_dir, last_sut_run)
    if evidence is not None:
        # 先落证据再算指纹——content_hash 覆盖最终包内容（含 ledger.jsonl）
        evidence.log("close", reason=close_reason)
        evidence.dump(package_dir)
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
    "guard_aborted_manifest",
    "guard_answered_manifest",
    "guard_deliverable",
    "guard_echo_answer",
    "guard_evaluable_abort",
    "refresh_content_hash",
]
