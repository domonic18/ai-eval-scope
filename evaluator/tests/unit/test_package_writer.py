"""package_writer 单测（arch/03 §三 / arch/16 §4.5 统一收尾 CLOSE）——补齐链与幂等。"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_eval.agent.core.session import AgentSession
from agent_eval.agent.executor.ledger import EvidenceLedger
from agent_eval.agent.executor.package_writer import (
    FALLBACK_NOT_WRITTEN,
    finalize_execution_package,
)
from agent_eval.execution.models import Task
from agent_eval.storage.package import PackageManifest, PackageStatus


class _StubPackageWriter:
    """write_package 最小桩：真 manifest 落指定包目录（真实实现经 workspace 根换算）。"""

    def __init__(self, package_dir: Path) -> None:
        self.package_dir = package_dir
        self.calls: list[dict[str, Any]] = []

    async def write_package(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        self.package_dir.mkdir(parents=True, exist_ok=True)
        manifest = PackageManifest(
            package_id=f"pkg_x_{kwargs.get('task_id')}",
            created_at=datetime.now(UTC).isoformat(),
            task_id=kwargs.get("task_id") or "task_1",
            sut_config_id="agent",
            status=PackageStatus.SUCCESS if kwargs.get("success") else PackageStatus.FAILED,
        )
        (self.package_dir / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        return {"package_dir": str(self.package_dir), "success": kwargs.get("success")}


def _task() -> Task:
    return Task(id="task_1", input={"subject": "数学"})


def _last_run() -> dict[str, Any]:
    return {
        "status": "success",
        "thread_id": "th-9",
        "text": "课件已全部完成！",
        "input": {"subject": "数学"},
        "pending": None,
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(package_dir: Path, status: PackageStatus) -> None:
    manifest = PackageManifest(
        package_id="pkg_pre_task_1",
        created_at=datetime.now(UTC).isoformat(),
        task_id="task_1",
        sut_config_id="agent",
        status=status,
    )
    (package_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


def test_finalize_materializes_degraded_package(tmp_path: Path) -> None:
    """异常收尾（空 session）走补齐链：五件套 + ledger.jsonl 全部落盘。

    对齐 run 20260911_050015 事故：SUT 已交付但旧 _abort 只写 manifest+metadata
    ——评估对象（answer）与过程证据（trace）双双丢失。
    """
    package_dir = tmp_path / "task_1"
    sut_tools = _StubPackageWriter(package_dir)
    evidence = EvidenceLedger()
    evidence.log("sut_call", action="dispatch", outcome="timeout")

    package = asyncio.run(
        finalize_execution_package(
            package_dir,
            _task(),
            AgentSession(),  # 图抛异常：无会话可恢复
            sut_tools=sut_tools,
            llm_role="agent",
            last_sut_run=_last_run(),
            evidence=evidence,
            fallback_error="Agent 执行保险丝触发",
            close_reason="aborted:AgentTimeoutError",
        )
    )

    assert package.manifest.status == "failed"
    assert sut_tools.calls[0]["error"] == "Agent 执行保险丝触发"
    assert (package_dir / "task.json").exists()
    trace = _read_json(package_dir / "trace.json")
    assert "保险丝触发" in trace["error"]  # 真实错误落 trace.error
    assert trace["response"]["sut"]["text"] == "课件已全部完成！"  # SUT 证据回填
    assert (package_dir / "output" / "answer.md").read_text(encoding="utf-8") == "课件已全部完成！"
    assert (package_dir / "transcript.md").exists()
    assert _read_json(package_dir / "metrics.json")["steps"] == 0
    ledger_lines = (package_dir / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in ledger_lines if line]
    assert events[0]["kind"] == "sut_call"  # 先前的证据事件保留
    assert events[-1]["kind"] == "close"
    assert events[-1]["reason"] == "aborted:AgentTimeoutError"
    # 指纹覆盖最终内容（含 ledger.jsonl）
    assert package.manifest.content_hash


def test_finalize_preserves_existing_package(tmp_path: Path) -> None:
    """幂等：Agent 已写包（manifest 存在）时不覆盖，仅补齐其余文件。"""
    package_dir = tmp_path / "task_1"
    package_dir.mkdir()
    _write_manifest(package_dir, PackageStatus.SUCCESS)
    sut_tools = _StubPackageWriter(package_dir)

    package = asyncio.run(
        finalize_execution_package(
            package_dir,
            _task(),
            AgentSession.from_messages([]),
            sut_tools=sut_tools,
            llm_role="agent",
            last_sut_run=None,
        )
    )

    assert package.manifest.status == "success"  # Agent 的成功判定不被兜底覆盖
    assert sut_tools.calls == []  # write_package 未被调用
    assert (package_dir / "task.json").exists()
    metadata_file = package_dir / "metadata.json"
    # 正常收尾不设异常守卫（守卫只在 fallback_error 非 None 时触发，不凭空写 metadata）
    assert not metadata_file.exists() or "guard_abort" not in _read_json(metadata_file)


def test_finalize_fallback_error_not_overriding_llm_error(tmp_path: Path) -> None:
    """LLM 已在 trace 写 error 时不覆盖——补齐语义是补全而非改写。"""
    package_dir = tmp_path / "task_1"
    package_dir.mkdir()
    _write_manifest(package_dir, PackageStatus.FAILED)
    (package_dir / "trace.json").write_text(
        json.dumps({"error": "SUT 侧限流拒绝"}), encoding="utf-8"
    )

    asyncio.run(
        finalize_execution_package(
            package_dir,
            _task(),
            AgentSession(),
            sut_tools=_StubPackageWriter(package_dir),
            llm_role="agent",
            last_sut_run=None,
            fallback_error="机械兜底错误",
        )
    )
    assert _read_json(package_dir / "trace.json")["error"] == "SUT 侧限流拒绝"


def test_abort_flips_llm_success_manifest_to_failed(tmp_path: Path) -> None:
    """异常收尾守卫（P2，run 20260911_073626 回归）：LLM 在异常前写的
    success 判定强制翻 failed——「自称成功但异常收场」不再流入下游。

    事故形态：三个产物下载全败、SUT text 只是进度播报，LLM 仍写
    success 包，随后保险丝熔断——幂等保留让 manifest success 与任务
    异常终止并存，评估器按「跑成功了但 0 分」误导读数人。
    """
    package_dir = tmp_path / "task_1"
    package_dir.mkdir()
    _write_manifest(package_dir, PackageStatus.SUCCESS)  # LLM 写的成功包
    (package_dir / "trace.json").write_text(
        json.dumps({"response": {"sut": {"text": "✅ 第 2 步完成"}}}), encoding="utf-8"
    )

    package = asyncio.run(
        finalize_execution_package(
            package_dir,
            _task(),
            AgentSession(),  # 异常收尾：无会话可恢复
            sut_tools=_StubPackageWriter(package_dir),
            llm_role="agent",
            last_sut_run=None,
            fallback_error="Agent 执行保险丝触发",
            close_reason="aborted:AgentTimeoutError",
        )
    )

    assert package.manifest.status == "failed"  # LLM 的 success 判定被机械翻转
    assert _read_json(package_dir / "metadata.json")["guard_abort"] is True
    # 包内容与证据不动——只翻结论，不毁证据
    assert _read_json(package_dir / "trace.json")["response"]["sut"]["text"] == "✅ 第 2 步完成"


def test_abort_guard_keeps_failed_manifest_and_marks_metadata(tmp_path: Path) -> None:
    """已 failed 的包（兜底包 / LLM 自判失败）不重复翻转，仅 metadata 留痕。"""
    package_dir = tmp_path / "task_1"
    package_dir.mkdir()
    _write_manifest(package_dir, PackageStatus.FAILED)

    asyncio.run(
        finalize_execution_package(
            package_dir,
            _task(),
            AgentSession(),
            sut_tools=_StubPackageWriter(package_dir),
            llm_role="agent",
            last_sut_run=None,
            fallback_error="Agent 会话异常中断",
        )
    )
    assert _read_json(package_dir / "manifest.json")["status"] == "failed"
    assert _read_json(package_dir / "metadata.json")["guard_abort"] is True


def test_finalize_without_evidence_skips_ledger(tmp_path: Path) -> None:
    """evidence 缺省 None：不落 ledger.jsonl（直连调用方不受机械壳约束）。"""
    package_dir = tmp_path / "task_1"
    sut_tools = _StubPackageWriter(package_dir)
    asyncio.run(
        finalize_execution_package(
            package_dir,
            _task(),
            AgentSession(),
            sut_tools=sut_tools,
            llm_role="agent",
            last_sut_run=None,
        )
    )
    assert not (package_dir / "ledger.jsonl").exists()
    trace = _read_json(package_dir / "trace.json")
    assert trace["error"] is None  # 无 fallback_error 时维持骨架缺省
    assert sut_tools.calls[0]["error"] == FALLBACK_NOT_WRITTEN
