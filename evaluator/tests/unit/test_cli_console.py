"""console 表现层基础设施单测 — prompts / output / equiv。"""

from __future__ import annotations

import sys
import types

import pytest
import typer
from typer.testing import CliRunner

from agent_eval.cli.console import equiv, output
from agent_eval.cli.console import prompts as console_prompts

runner = CliRunner()


# ── prompts ────────────────────────────────────────────────────────────


class TestSelect:
    def test_no_input_without_default_exits_2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_EVAL_NO_INPUT", "1")
        with pytest.raises(typer.Exit) as ei:
            console_prompts.select("选择包", ["chat", "courseware"])
        assert ei.value.exit_code == 2

    def test_no_input_with_default_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_EVAL_NO_INPUT", "1")
        assert (
            console_prompts.select("选择包", ["chat", "courseware"], default="courseware")
            == "courseware"
        )
        # 编号 default 同样生效
        assert console_prompts.select("选择包", ["chat", "courseware"], default=2) == "courseware"

    def test_env_bypass_by_index_and_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_EVAL_NO_INPUT", "1")
        monkeypatch.setenv("WB_PKG", "2")
        assert (
            console_prompts.select("选择包", ["chat", "courseware"], env_key="WB_PKG")
            == "courseware"
        )
        monkeypatch.setenv("WB_PKG", "chat")
        assert console_prompts.select("选择包", ["chat", "courseware"], env_key="WB_PKG") == "chat"

    def test_env_bypass_invalid_exits_2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_EVAL_NO_INPUT", "1")
        monkeypatch.setenv("WB_PKG", "nope")
        with pytest.raises(typer.Exit) as ei:
            console_prompts.select("选择包", ["chat"], env_key="WB_PKG")
        assert ei.value.exit_code == 2

    def test_piped_input_interactive(self) -> None:
        """管道输入（CliRunner 脚本化）不受 AGENT_EVAL_NO_INPUT 影响，正常提示。"""
        import typer

        app = typer.Typer()

        @app.command()
        def pick() -> None:
            print(f"picked={console_prompts.select('选择', ['a', 'b'])}")

        result = runner.invoke(app, [], input="2\n")
        assert result.exit_code == 0, result.output
        assert "picked=b" in result.output

    def test_invalid_then_valid_reprompts(self) -> None:
        import typer

        app = typer.Typer()

        @app.command()
        def pick() -> None:
            print(f"picked={console_prompts.select('选择', ['a', 'b'])}")

        result = runner.invoke(app, [], input="9\n1\n")
        assert result.exit_code == 0, result.output
        assert "picked=a" in result.output
        assert "无效选择" in result.output

    def test_implicit_default_empty_enter_picks_first(self) -> None:
        # 既有行为回归：向导类选择空回车仍落隐式默认第一项（不受 no_default 影响）
        import typer

        app = typer.Typer()

        @app.command()
        def pick() -> None:
            print(f"picked={console_prompts.select('选择', ['a', 'b'])}")

        result = runner.invoke(app, [], input="\n")
        assert result.exit_code == 0, result.output
        assert "picked=a" in result.output

    def test_no_default_empty_enter_reprompts(self) -> None:
        # 放行类选择：空回车不再隐式选第一项——按无效选择重问，
        # 曾是安全纵伤（授权/确认选择器空回车一律落「允许」「确认执行」）
        import typer

        app = typer.Typer()

        @app.command()
        def pick() -> None:
            print(f"picked={console_prompts.select('选择', ['允许', '取消'], no_default=True)}")

        result = runner.invoke(app, [], input="\n1\n")
        assert result.exit_code == 0, result.output
        assert "picked=允许" in result.output
        assert "无效选择" in result.output

    def test_no_default_hint_has_no_enter_promise(self) -> None:
        # 提示去掉「回车确认」——no_default 下空回车没有默认语义，文案不许撒谎
        import typer

        app = typer.Typer()

        @app.command()
        def pick() -> None:
            console_prompts.select("选择", ["a", "b"], no_default=True)

        result = runner.invoke(app, [], input="2\n")
        assert result.exit_code == 0, result.output
        assert "输入编号，回车确认" not in result.output
        assert "输入编号]" in result.output

    def test_no_default_no_input_requires_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # --no-input 下放行类无默认可用：必须显式提供（防线收口；ask_fn 场景不可达）
        monkeypatch.setenv("AGENT_EVAL_NO_INPUT", "1")
        with pytest.raises(typer.Exit) as ei:
            console_prompts.select("选择", ["a", "b"], no_default=True)
        assert ei.value.exit_code == 2


class TestConfirmAsk:
    def test_no_input_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_EVAL_NO_INPUT", "1")
        assert console_prompts.confirm("执行?", default=True) is True
        assert console_prompts.ask("路径", default="./x") == "./x"

    def test_no_input_ask_without_default_exits_2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_EVAL_NO_INPUT", "1")
        with pytest.raises(typer.Exit) as ei:
            console_prompts.ask("必填项")
        assert ei.value.exit_code == 2

    def test_env_bypass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_EVAL_NO_INPUT", "1")
        monkeypatch.setenv("WB_YES", "true")
        assert console_prompts.confirm("执行?", env_key="WB_YES") is True
        monkeypatch.setenv("WB_NAME", "hello")
        assert console_prompts.ask("名称", env_key="WB_NAME") == "hello"


class _FakeStdin:
    """逐键回放的假 stdin（read(1) 一次消费一键；isatty 可切换）。"""

    def __init__(self, keys: list[str], *, tty: bool = True) -> None:
        self._keys = list(keys)
        self._tty = tty

    def fileno(self) -> int:
        return 0

    def isatty(self) -> bool:
        return self._tty

    def read(self, _n: int) -> str:
        return self._keys.pop(0) if self._keys else ""


class TestMaskedAsk:
    """ask(hide=True) 掩码回显：TTY 逐键 ``*`` 上屏，非 TTY 回退隐藏回显。"""

    @staticmethod
    def _fake_termios(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, object]]:
        calls: list[tuple[str, object]] = []
        mod = types.SimpleNamespace(
            TCSADRAIN=object(),
            tcgetattr=lambda fd: ["saved"],
            tcsetattr=lambda fd, when, attrs: calls.append(("restore", when)),
        )
        monkeypatch.setitem(sys.modules, "termios", mod)
        tty_mod = types.SimpleNamespace(setcbreak=lambda fd: calls.append(("cbreak", fd)))
        monkeypatch.setitem(sys.modules, "tty", tty_mod)
        return calls

    def test_hidden_uses_masked_input_on_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._fake_termios(monkeypatch)
        seen: list[str] = []
        monkeypatch.setattr(sys, "stdin", _FakeStdin(["s", "e", "c", "\r"]))
        monkeypatch.setattr(console_prompts, "_masked_input", lambda p: seen.append(p) or "sec")
        assert console_prompts.ask("token", hide=True) == "sec"
        assert seen == ["? token: "]  # 提示形态与 typer.prompt 路径一致

    def test_hidden_falls_back_without_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 管道 / CliRunner：termios 路径不启用 → click 隐藏回显（既有行为不变）
        self._fake_termios(monkeypatch)
        monkeypatch.setattr(sys, "stdin", _FakeStdin(["x"], tty=False))
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            console_prompts.typer,
            "prompt",
            lambda *a, **kw: calls.append(kw) or "pw",
        )
        assert console_prompts.ask("token", hide=True) == "pw"
        assert calls and calls[0]["hide_input"] is True

    def test_masked_input_stars_backspace(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._fake_termios(monkeypatch)
        monkeypatch.setattr(sys, "stdin", _FakeStdin(["a", "b", "\x7f", "c", "\r"]))
        assert console_prompts._masked_input("? x: ") == "ac"
        out = capsys.readouterr().out
        assert "**\b \b*" in out  # 两星 + 退格抹除 + 补一星
        assert out.endswith("\n")

    def test_masked_input_backspace_on_empty_ignored(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._fake_termios(monkeypatch)
        monkeypatch.setattr(sys, "stdin", _FakeStdin(["\x7f", "\x7f", "o", "k", "\r"]))
        assert console_prompts._masked_input("? x: ") == "ok"
        assert "\b \b" not in capsys.readouterr().out  # 空栈退格不误抹提示符

    def test_masked_input_eof_aborts_and_restores(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        calls = self._fake_termios(monkeypatch)
        monkeypatch.setattr(sys, "stdin", _FakeStdin(["\x04"]))
        with pytest.raises(typer.Abort):
            console_prompts._masked_input("? x: ")
        assert calls[-1][0] == "restore"  # finally 复原终端态，不残留 cbreak
        assert capsys.readouterr().out.endswith("\n")

    def test_masked_input_keyboard_interrupt_restores(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # ^C（ISIG 保留）→ KI 穿透，终端态仍复原
        calls = self._fake_termios(monkeypatch)

        class _KiStdin(_FakeStdin):
            def read(self, _n: int) -> str:
                raise KeyboardInterrupt

        monkeypatch.setattr(sys, "stdin", _KiStdin([]))
        with pytest.raises(KeyboardInterrupt):
            console_prompts._masked_input("? x: ")
        assert calls[-1][0] == "restore"


# ── output：退出码映射 ─────────────────────────────────────────────────


class TestMapExitCode:
    def test_matrix(self) -> None:
        import typer

        from agent_eval.core.exceptions import (
            AgentError,
            ConfigError,
            LLMNetworkError,
            PackageNotFoundError,
            ScenarioPackageValidationError,
            SchemaValidationError,
            SUTChannelError,
        )

        assert output.map_exit_code(RuntimeError()) == output.EXIT_BUSINESS
        assert output.map_exit_code(KeyboardInterrupt()) == output.EXIT_INTERRUPT
        assert output.map_exit_code(typer.Abort()) == output.EXIT_INTERRUPT
        assert output.map_exit_code(typer.Exit(code=7)) == 7
        assert output.map_exit_code(ConfigError("x")) == output.EXIT_CONFIG
        assert output.map_exit_code(SchemaValidationError("x")) == output.EXIT_CONFIG
        assert output.map_exit_code(ScenarioPackageValidationError("x")) == output.EXIT_CONFIG
        assert output.map_exit_code(PackageNotFoundError("x")) == output.EXIT_CONFIG
        assert output.map_exit_code(LLMNetworkError("x")) == output.EXIT_DEPENDENCY
        assert output.map_exit_code(SUTChannelError("x")) == output.EXIT_DEPENDENCY
        assert output.map_exit_code(AgentError("x")) == output.EXIT_BUSINESS

    def test_json_mode_toggle(self) -> None:
        output.set_output_format("text")  # 复位（此前 json 用例可能遗留全局态）
        assert output.is_json() is False
        output.set_output_format("json")
        try:
            assert output.is_json() is True
        finally:
            output.set_output_format("text")


# ── equiv：等价命令 argv ───────────────────────────────────────────────


class TestEquiv:
    def test_pipeline_argv_skips_falsy_and_quotes(self) -> None:
        argv = equiv.pipeline_argv(package="chat", task_set="default", rule_set=None, upload=False)
        assert argv == ["agent-eval", "pipeline", "--package", "chat", "--task-set", "default"]
        assert equiv.render(argv) == "agent-eval pipeline --package chat --task-set default"

    def test_upload_argv(self) -> None:
        assert equiv.upload_argv("20260831_093012") == [
            "agent-eval",
            "upload",
            "--run",
            "20260831_093012",
            "--workspace",
            "./workspace",
        ]

    def test_dataset_argv_positional_and_flags(self) -> None:
        argv = equiv.dataset_argv("gsm8k", source="ms", revision=None, force=False)
        assert argv == ["agent-eval", "dataset", "download", "gsm8k", "--source", "ms"]
        assert equiv.render(argv) == "agent-eval dataset download gsm8k --source ms"
        assert equiv.dataset_argv("gsm8k", force=True) == [
            "agent-eval",
            "dataset",
            "download",
            "gsm8k",
            "--force",
        ]


# ── pipeline_render：渲染门 seal（僵尸线程静音）────────────────────────


class TestPipelineRendererSeal:
    @staticmethod
    def _patch_render(monkeypatch: pytest.MonkeyPatch) -> list[str]:
        from agent_eval.cli.console import pipeline_render as pr

        seen: list[str] = []
        monkeypatch.setattr(pr, "rprint", lambda *a, **k: seen.append("rprint"))
        monkeypatch.setattr(pr, "print_task_table", lambda pkgs: seen.append("table"))
        monkeypatch.setattr(pr, "_print_summary", lambda report: seen.append("summary"))
        monkeypatch.setattr(pr, "_render_upload_receipt", lambda r: seen.append("receipt"))
        return seen

    @staticmethod
    def _resolve_payload() -> dict:
        return {
            "task_set_path": "ts.yaml",
            "task_count": 1,
            "sut_name": "sut",
            "sut_channel": "generic_http",
            "sut_base_url": "http://x",
            "rule_set_path": "rs.yaml",
            "run_id": "r1",
        }

    def test_seal_permanently_silences_progress(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_eval.cli.console.pipeline_render import PipelineRenderer
        from agent_eval.cli.pipeline_core import PipelineStage

        seen = self._patch_render(monkeypatch)
        renderer = PipelineRenderer(log_level="quiet")

        renderer.on_progress(PipelineStage.RESOLVE_INFO, self._resolve_payload())
        renderer.on_progress(PipelineStage.DONE, {"run_dir": "d"})
        assert seen  # seal 前正常渲染

        renderer.seal()
        sealed_count = len(seen)
        renderer.on_progress(PipelineStage.RESOLVE_INFO, self._resolve_payload())
        renderer.on_progress(PipelineStage.SUMMARY, {"report": {}})
        renderer.close()  # seal 后 close 亦无输出
        assert len(seen) == sealed_count  # 渲染门永久关闭

    def test_seal_idempotent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_eval.cli.console.pipeline_render import PipelineRenderer

        seen = self._patch_render(monkeypatch)
        renderer = PipelineRenderer(log_level="quiet")
        renderer.seal()
        renderer.seal()  # 幂等不炸
        assert seen == []


# ── exec_bridge：会话内执行的写者仲裁 + 日志档位快照 ───────────────────


class TestExecutionRenderBridge:
    @staticmethod
    def _make(emit_sink: list | None):
        from agent_eval.cli.console.exec_bridge import ExecutionRenderBridge

        finished: list[bool] = []
        emit = emit_sink.append if emit_sink is not None else None
        return ExecutionRenderBridge(emit, lambda: finished.append(True)), finished

    def test_gated_emit_three_states(self) -> None:
        sink: list[dict] = []
        bridge, finished = self._make(sink)

        bridge.gated_emit({"k": 1})
        assert sink == [{"k": 1}]  # normal 直通

        bridge.suspend()
        bridge.gated_emit({"k": 2})
        assert sink == [{"k": 1}]  # suspended 丢弃（LLM 事件行让位管线渲染）
        assert finished == [True]  # suspend 收未闭合行

        bridge.resume()
        bridge.gated_emit({"k": 3})
        assert sink == [{"k": 1}, {"k": 3}]  # resume 复通

        bridge.cancel()
        bridge.gated_emit({"k": 4})
        bridge.resume()  # sealed 后 resume 不重开渲染门
        assert sink == [{"k": 1}, {"k": 3}]  # sealed 永久丢弃

    def test_emit_none_is_noop(self) -> None:
        bridge, finished = self._make(None)  # JSON 模式：emit=None 桥仍在
        bridge.suspend()
        bridge.gated_emit({"k": 1})  # 不炸
        bridge.resume()
        bridge.cancel()
        assert finished == [True]

    def test_cancel_without_suspend(self) -> None:
        sink: list[dict] = []
        bridge, _ = self._make(sink)
        bridge.cancel()  # 未 suspend 直接 cancel（状态机穷举）
        bridge.gated_emit({"k": 1})
        assert sink == []

    def test_pipeline_progress_passthrough_then_sealed(self) -> None:
        from unittest.mock import MagicMock

        from agent_eval.cli.console.exec_bridge import ExecutionRenderBridge

        bridge = ExecutionRenderBridge(None)
        renderer = MagicMock()
        wrapped = bridge.pipeline_progress(renderer)

        bridge.suspend()  # 挂起不作用于管线渲染——执行期唯一写者直通
        wrapped("stage", {"p": 1})
        renderer.on_progress.assert_called_once_with("stage", {"p": 1})

        bridge.cancel()  # 封缄：渲染器 seal + 包装闭包丢弃
        renderer.seal.assert_called_once()
        wrapped("stage", {"p": 2})
        assert renderer.on_progress.call_count == 1

    def test_renderer_seal_without_pipeline_progress(self) -> None:
        # 未经过 pipeline_progress 注入渲染器时 cancel 不炸（renderer 为 None）
        bridge, _ = self._make([])
        bridge.cancel()


class TestBridgeLoggingRestore:
    def test_snapshot_restore_roundtrip(self) -> None:
        """pipeline_core 的 setup_logging 是进程全局突变——resume 必须复原会话档位。"""
        import logging

        from agent_eval.cli.console.exec_bridge import ExecutionRenderBridge
        from agent_eval.core.exec_events import EXEC_EVENT_LOGGER
        from agent_eval.core.logging import install_exec_event_handler, setup_logging

        try:
            bridge = ExecutionRenderBridge(None)

            # 场景1：debug 档 + 事件行可见 → 执行期被改为 warning → 复原
            setup_logging(level="DEBUG")
            install_exec_event_handler(enabled=True)
            bridge.suspend()
            setup_logging(level="WARNING")  # 模拟 pipeline_core 的全局突变
            assert logging.getLogger().level == logging.WARNING
            bridge.resume()
            assert logging.getLogger().level == logging.DEBUG
            assert logging.getLogger(EXEC_EVENT_LOGGER).handlers  # 事件渲染器复原

            # 场景2：normal 档（事件行不可见）同样复原
            setup_logging(level="INFO")
            install_exec_event_handler(enabled=False)
            bridge.suspend()
            setup_logging(level="ERROR")
            bridge.resume()
            assert logging.getLogger().level == logging.INFO
            assert not logging.getLogger(EXEC_EVENT_LOGGER).handlers
        finally:
            # 还原全局日志态，不污染其他用例
            setup_logging(level="INFO")
            install_exec_event_handler(enabled=False)

    def test_resume_without_snapshot_is_noop(self) -> None:
        from agent_eval.cli.console.exec_bridge import ExecutionRenderBridge

        bridge = ExecutionRenderBridge(None)
        bridge.resume()  # 未 suspend（无快照）不炸
