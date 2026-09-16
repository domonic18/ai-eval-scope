"""console 表现层基础设施单测 — prompts / output / equiv（arch/15 §三）。"""

from __future__ import annotations

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
