"""评测执行域工具单测。

工具直调（不经 LLM 面）：确认门槛/旁路拒绝/busy/摘要分支/取消令牌接线/
凭证补录循环/三只读工具数据形态/硬中断终局（daemon worker 生命周期）。
pipeline_core 全程 monkeypatch（编排回归在 test_pipeline_core；渲染字节在 golden）。
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_eval.agent.workbench.execution import ExecutionToolServer
from agent_eval.cli.pipeline_core import PipelineOutcome


def _outcome(**kw) -> PipelineOutcome:
    base = dict(
        stage="done",
        exit_code=0,
        run_id="20260101_000000",
        run_dir="/ws/runs/20260101_000000",
        metrics={"m:reward": 0.9},
        total_samples=2,
        gate={"mode": "off", "enabled": False, "passed": True},
        upload_receipt={"enabled": False},
        payload={"total": 2, "succeeded": 2},
        result=SimpleNamespace(report=SimpleNamespace(failure_breakdown={"safety": 1})),
    )
    base.update(kw)
    return PipelineOutcome(**base)


class _FakeBridge:
    """渲染桥桩：记录生命周期调用，progress 转发记录。"""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.progress_events: list[str] = []

    def suspend(self) -> None:
        self.calls.append("suspend")

    def resume(self) -> None:
        self.calls.append("resume")

    def cancel(self) -> None:
        self.calls.append("cancel")

    def pipeline_progress(self, renderer) -> object:
        def _progress(stage, payload):
            self.progress_events.append(stage.value)

        return _progress


class TestRunEvaluationGate:
    def _server(self, monkeypatch, answers: list[str], outcome=None, calls=None) -> tuple:
        import agent_eval.agent.workbench.execution.run_eval as run_eval_mod

        calls = calls if calls is not None else {}
        answers_iter = iter(answers)

        async def ask_fn(question, *, options=None, secret=False):
            calls.setdefault("questions", []).append(question)
            return next(answers_iter, "")

        server = ExecutionToolServer(ask_fn=ask_fn, workspace_root=Path("/ws"))

        def fake_core(params, *, progress, cancel_event, credential_filler):
            calls["core"] = dict(
                params=params, progress=progress, cancel=cancel_event, filler=credential_filler
            )
            calls["active_set"] = server.ctx.active_event is not None
            if outcome is not None:
                return outcome
            return _outcome()

        monkeypatch.setattr(run_eval_mod, "pipeline_core", fake_core)
        return server, calls

    @pytest.mark.asyncio
    async def test_no_ask_fn_refused_core_never_called(self, monkeypatch) -> None:
        import agent_eval.agent.workbench.execution.run_eval as run_eval_mod

        calls: dict = {}

        def fake_core(*a, **k):  # pragma: no cover - 断言不可达即本测试
            calls["core"] = True
            return _outcome()

        monkeypatch.setattr(run_eval_mod, "pipeline_core", fake_core)
        server = ExecutionToolServer(ask_fn=None)
        result = await server.run_evaluation(package="chat")
        assert result["status"] == "refused"
        assert "core" not in calls  # 唯一旁路拒绝点：从未编排

    @pytest.mark.asyncio
    async def test_confirmation_declined_skips_core(self, monkeypatch) -> None:
        server, calls = self._server(monkeypatch, answers=["取消"])
        result = await server.run_evaluation(package="chat", gate="strict")
        assert result["status"] == "declined"
        assert "agent-eval pipeline --package chat --gate strict" in result["equivalent_command"]
        assert "core" not in calls  # 拒绝 → pipeline_core 从未被调用

    @pytest.mark.asyncio
    async def test_confirmation_shows_equivalent_command(self, monkeypatch) -> None:
        server, calls = self._server(monkeypatch, answers=["确认执行"])
        result = await server.run_evaluation(package="chat", task_set="default", no_cache=True)
        assert result["status"] == "done"
        question = calls["questions"][0]
        assert "agent-eval pipeline --package chat --task-set default --no-cache" in question

    @pytest.mark.asyncio
    async def test_busy_guard(self, monkeypatch) -> None:
        server, calls = self._server(monkeypatch, answers=["确认执行"])
        server.ctx.active_event = threading.Event()  # 模拟执行中
        server.ctx.worker_thread = threading.current_thread()  # busy 双判据：worker 存活
        result = await server.run_evaluation(package="chat")
        assert result["status"] == "busy"
        assert "收尾" in result["note"] or "执行中" in result["note"]
        assert "core" not in calls

    @pytest.mark.asyncio
    async def test_stale_token_reaped_after_worker_exit(self, monkeypatch) -> None:
        """上轮 KI 僵尸 worker 已退出：入口 reap 残留令牌，放行新一轮。"""
        server, _ = self._server(monkeypatch, answers=["取消"])
        dead = threading.Thread(target=lambda: None)
        dead.start()
        dead.join()
        server.ctx.active_event = threading.Event()  # KI 路径残留令牌
        server.ctx.worker_thread = dead
        result = await server.run_evaluation(package="chat")
        assert result["status"] == "declined"  # reap 后走到确认门槛
        assert server.ctx.active_event is None  # 正常收轮令牌清账

    @pytest.mark.asyncio
    async def test_bridge_lifecycle_and_cancel_wiring(self, monkeypatch) -> None:
        bridge = _FakeBridge()
        import agent_eval.agent.workbench.execution.run_eval as run_eval_mod

        async def ask_fn(question, *, options=None, secret=False):
            return "确认执行"

        server = ExecutionToolServer(
            ask_fn=ask_fn, render_bridge=bridge, workspace_root=Path("/ws")
        )

        seen: dict = {}

        def fake_core(params, *, progress, cancel_event, credential_filler):
            seen["cancel"] = cancel_event
            seen["active_set"] = server.ctx.active_event is cancel_event
            return _outcome()

        monkeypatch.setattr(run_eval_mod, "pipeline_core", fake_core)
        result = await server.run_evaluation(package="chat")
        assert result["status"] == "done"
        assert isinstance(seen["cancel"], threading.Event)
        assert seen["active_set"] is True
        assert bridge.calls == ["suspend", "resume"]  # 挂起→恢复成对
        assert server.ctx.active_event is None  # finally 复位 busy 哨兵


class TestHardInterruptTeardown:
    """硬中断终局：daemon worker 零 join，会话不被僵尸拖垮。

    场景还原 v4.12 实测事故：二按 KI 打断等待侧后（teardown cancel 等效于
    task.cancel()），旧实现 Runner.close 会 join to_thread 默认池把终端冻住
    （上限 300s）→ 按键风暴击穿 asyncio.run 收尾窗口 → 会话报废。新实现
    turn 即时收轮、令牌保留、worker 后台到任务边界收尾。
    """

    @pytest.mark.asyncio
    async def test_hard_interrupt_zombie_worker_lifecycle(self, monkeypatch) -> None:
        import agent_eval.agent.workbench.execution.run_eval as run_eval_mod

        started, release = threading.Event(), threading.Event()
        answers = iter(["确认执行", "取消"])

        async def ask_fn(question, *, options=None, secret=False):
            return next(answers, "")

        server = ExecutionToolServer(ask_fn=ask_fn, workspace_root=Path("/ws"))

        def fake_core(params, *, progress, cancel_event, credential_filler):
            started.set()
            release.wait(5)  # 模拟分钟级不可打断的当前任务
            return _outcome()

        monkeypatch.setattr(run_eval_mod, "pipeline_core", fake_core)

        task = asyncio.create_task(server.run_evaluation(package="chat"))
        for _ in range(500):  # 等 worker 进入「当前任务」
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        else:  # pragma: no cover - worker 未启动即失败
            pytest.fail("pipeline worker 未启动")

        task.cancel()  # 二按 KI 打断等待侧的等效注入点
        with pytest.raises(asyncio.CancelledError):
            await task

        # 硬中断终局：turn 即时收轮；令牌保留作僵尸取消通道；daemon 存活
        assert server.ctx.active_event is not None  # 不随 finally 清账
        assert server.ctx.worker_thread is not None
        assert server.ctx.worker_thread.daemon is True  # teardown 零 join 的根据
        assert server.ctx.worker_alive() is True

        # 僵尸存活期：busy 守卫拒绝并发（含 reap 判据 worker_alive）
        busy = await server.run_evaluation(package="chat")
        assert busy["status"] == "busy"
        assert "收尾" in busy["note"]

        # worker 到任务边界退出 → 下一轮入口 reap 残留令牌，正常走确认
        release.set()
        server.ctx.worker_thread.join(5)
        assert server.ctx.worker_alive() is False
        third = await server.run_evaluation(package="chat")
        assert third["status"] == "declined"
        assert server.ctx.active_event is None  # 正常收轮令牌清账


class TestRunEvaluationSummary:
    @pytest.mark.asyncio
    async def test_done_summary_fields(self, monkeypatch) -> None:
        result = await self._run(
            monkeypatch,
            _outcome(upload_receipt={"enabled": True, "view_url": "https://p/run/20260101_000000"}),
        )
        assert result["status"] == "done"
        assert result["tasks"] == {"total": 2, "succeeded": 2, "failed": 0}
        assert result["metrics"] == {"m:reward": 0.9}
        assert result["uploaded"] is True
        assert result["platform_url"] == "https://p/run/20260101_000000"
        assert "show_run" in result["next_step"]
        assert result["failure_breakdown"] == {"safety": 1}

    @pytest.mark.asyncio
    async def test_gate_failed_summary(self, monkeypatch) -> None:
        result = await self._run(
            monkeypatch,
            _outcome(stage="gate", exit_code=3, gate={"mode": "strict", "passed": False}),
        )
        assert result["status"] == "gate_failed" and result["exit_code"] == 3
        assert result["metrics"]  # 门禁失败指标随行（不阻断上报/研判）

    @pytest.mark.asyncio
    async def test_cancelled_summary(self, monkeypatch) -> None:
        result = await self._run(
            monkeypatch,
            _outcome(stage="cancelled", exit_code=130, cancelled=True, payload=None, result=None),
        )
        assert result["status"] == "cancelled"
        assert "已落盘" in result["note"]
        assert result["run_id"] == "20260101_000000"

    @pytest.mark.asyncio
    async def test_failed_summary(self, monkeypatch) -> None:
        result = await self._run(
            monkeypatch,
            _outcome(stage="execute", exit_code=1, error="通道不可用", error_type="AgentEvalError"),
        )
        assert result["status"] == "failed"
        assert result["stage"] == "execute" and result["error"] == "通道不可用"

    async def _run(self, monkeypatch, outcome) -> dict:
        import agent_eval.agent.workbench.execution.run_eval as run_eval_mod

        async def ask_fn(question, *, options=None, secret=False):
            return "确认执行"

        monkeypatch.setattr(run_eval_mod, "pipeline_core", lambda *a, **k: outcome)
        server = ExecutionToolServer(ask_fn=ask_fn, workspace_root=Path("/ws"))
        return await server.run_evaluation(package="chat")


class TestCredentialFiller:
    def test_fill_loop_saves_once(self, monkeypatch, tmp_path) -> None:
        from agent_eval.agent.workbench.execution import run_eval as mod

        saved: dict = {}

        monkeypatch.setattr(
            "agent_eval.execution.auth.credentials.missing_credential_fields",
            lambda sut: ["username", "password"],
        )
        monkeypatch.setattr(
            "agent_eval.execution.auth.secrets_store.load_secrets_file", lambda *a: {}
        )
        monkeypatch.setattr(
            "agent_eval.execution.auth.secrets_store.save_secrets_file",
            lambda secrets, *a: saved.update(secrets) or str(tmp_path / "secrets.json"),
        )

        async def ask_fn(question, *, options=None, secret=False):
            assert secret is True  # 凭证录入必隐藏
            return "v1"

        sut = SimpleNamespace(name="sasan", auth=SimpleNamespace(credential_ref="SRV"))
        filler = mod._make_credential_filler(
            SimpleNamespace(ask_fn=ask_fn, log=lambda *a, **k: None)
        )
        filler(sut)
        assert saved == {"SRV": {"username": "v1", "password": "v1"}}  # 一次落盘不留半截

    def test_empty_input_cancels_whole_batch(self, monkeypatch) -> None:
        from agent_eval.agent.workbench.execution import run_eval as mod
        from agent_eval.core.exceptions import SUTAuthError

        monkeypatch.setattr(
            "agent_eval.execution.auth.credentials.missing_credential_fields",
            lambda sut: ["username", "password"],
        )
        monkeypatch.setattr(
            "agent_eval.execution.auth.secrets_store.load_secrets_file", lambda *a: {}
        )
        monkeypatch.setattr(
            "agent_eval.execution.auth.secrets_store.save_secrets_file",
            lambda *a, **k: pytest.fail("任一空输入不得落盘半截状态"),
        )

        async def ask_fn(question, *, options=None, secret=False):
            return "" if "username" in question else "v"

        filler = mod._make_credential_filler(
            SimpleNamespace(ask_fn=ask_fn, log=lambda *a, **k: None)
        )
        with pytest.raises(SUTAuthError, match="已取消补录"):
            filler(SimpleNamespace(name="s", auth=SimpleNamespace(credential_ref="R")))


class _Pkg:
    def __init__(self, root: Path, ref: str, source: str) -> None:
        (root / "task_sets").mkdir(parents=True)
        (root / "sut_configs").mkdir()
        (root / "rules").mkdir()
        (root / "task_sets" / "default.yaml").write_text("id: ts\n", encoding="utf-8")
        (root / "sut_configs" / "main.yaml").write_text("sut:\n", encoding="utf-8")
        self.manifest = SimpleNamespace(
            ref=ref, name=ref, version="1.0.0", description="d", default_task_set=None
        )
        self.source = source
        self.root = root
        self.task_sets_dir = root / "task_sets"
        self.sut_configs_dir = root / "sut_configs"
        self.rules_dir = root / "rules"


class TestReadOnlyTools:
    def _server(self, tmp_path: Path) -> ExecutionToolServer:
        return ExecutionToolServer(workspace_root=tmp_path)

    @pytest.mark.asyncio
    async def test_list_eval_targets_enumerates_package_internals(
        self, monkeypatch, tmp_path
    ) -> None:
        import agent_eval.packages as pkgs_mod

        # 绕 PackageManager 发现面注入假包（发现链由包管理域测覆盖）
        pkg = _Pkg(tmp_path / "chat-pkg", "chat:1.0.0", "project")
        monkeypatch.setattr(
            pkgs_mod, "PackageManager", lambda: SimpleNamespace(list=lambda source=None: [pkg])
        )
        server = self._server(tmp_path)
        result = await server.list_eval_targets()
        assert result["total"] == 1
        entry = result["packages"][0]
        assert entry["task_sets"] == ["default"] and entry["suts"] == ["main"]
        assert entry["notes"]

    @pytest.mark.asyncio
    async def test_list_eval_targets_bad_source(self, tmp_path) -> None:
        result = await self._server(tmp_path).list_eval_targets("bogus")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_list_runs_and_show_run(self, tmp_path) -> None:
        run_dir = tmp_path / "runs" / "20260101_000000" / "reports"
        run_dir.mkdir(parents=True)
        (run_dir.parent / "run_manifest.json").write_text('{"mode": "pipeline"}', encoding="utf-8")
        (run_dir / "summary.json").write_text(
            '{"run_id": "20260101_000000", "metrics": {"m": 0.8},'
            ' "total_samples": 2, "failure_breakdown": {"safety": 1}}',
            encoding="utf-8",
        )
        server = self._server(tmp_path)
        listed = await server.list_runs()
        assert listed["total"] == 1 and listed["runs"][0]["run_id"] == "20260101_000000"

        detail = await server.show_run("20260101_000000")
        assert detail["summary"]["metrics"] == {"m": 0.8}
        assert detail["summary"]["failure_breakdown"] == {"safety": 1}

        missing = await server.show_run("nope")
        assert "error" in missing

    @pytest.mark.asyncio
    async def test_upload_run_receipt_and_errors(self, monkeypatch, tmp_path) -> None:
        import agent_eval.cli.cmds.upload as upload_mod

        server = self._server(tmp_path)

        def fake_core(run, workspace="./workspace", project=None, *, note=None):
            assert workspace == str(tmp_path)
            return {
                "run_id": run,
                "sent": 3,
                "queued": 0,
                "run_url": f"https://eval.example.com/run/{run}",
                "project": project,
            }

        monkeypatch.setattr(upload_mod, "upload_run_core", fake_core)
        result = await server.upload_run("20260101_000000", project="demo")
        assert result["status"] == "done" and result["sent"] == 3
        assert result["run_url"] == "https://eval.example.com/run/20260101_000000"

        def boom(run, workspace="./workspace", project=None, *, note=None):
            raise upload_mod.UploadError("未配置凭据", kind="no_credentials")

        monkeypatch.setattr(upload_mod, "upload_run_core", boom)
        failed = await server.upload_run("20260101_000000")
        assert failed["status"] == "failed" and failed["kind"] == "no_credentials"
        assert "AGENT_EVAL_HOST" in failed["guidance"]

    @pytest.mark.asyncio
    async def test_interrupt_without_active_returns_false(self, tmp_path) -> None:
        server = self._server(tmp_path)
        assert server.interrupt_active_execution() is False
        server.ctx.active_event = threading.Event()
        assert server.interrupt_active_execution() is True
        assert server.ctx.active_event.is_set()
