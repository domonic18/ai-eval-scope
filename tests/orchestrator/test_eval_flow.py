"""SDK eval 接口 + CLI eval 集成测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_eval.orchestrator.orchestrator import EvalResult, eval_packages

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestEvalPackagesSDK:
    """SDK eval_packages 接口测试。"""

    def test_eval_packages_basic(self, golden_package: Path, tmp_path: Path) -> None:
        """SDK eval 基本流程。"""
        output_dir = tmp_path / "workspace"
        result = eval_packages(
            golden_package,
            output_dir=output_dir,
        )

        assert isinstance(result, EvalResult)
        assert result.report.total_samples >= 1
        assert result.run_id != ""

    def test_eval_packages_with_rule_set(
        self,
        golden_package: Path,
        tmp_path: Path,
    ) -> None:
        """SDK eval 带 rule_set。"""
        rule_set_path = FIXTURES / "configs" / "rule_set.yaml"
        if not rule_set_path.exists():
            pytest.skip("rule_set.yaml fixture 不存在")

        output_dir = tmp_path / "workspace"
        result = eval_packages(
            golden_package,
            rule_set_path=str(rule_set_path),
            output_dir=output_dir,
        )

        assert isinstance(result, EvalResult)

    def test_eval_packages_output_structure(
        self,
        golden_package: Path,
        tmp_path: Path,
    ) -> None:
        """SDK eval 输出目录结构完整。"""
        output_dir = tmp_path / "workspace"
        eval_packages(
            golden_package,
            output_dir=output_dir,
        )

        # 验证 workspace 结构
        ws_root = Path(output_dir)
        assert (ws_root / "runs").is_dir()
        assert (ws_root / "index").is_dir()
        assert (ws_root / "cache").is_dir()
        assert (ws_root / "index" / "runs_index.json").exists()

    def test_eval_packages_nonexistent_dir(self, tmp_path: Path) -> None:
        """SDK eval 不存在的目录报错。"""
        from agent_eval.core.exceptions import OrchestratorError

        with pytest.raises(OrchestratorError, match="不存在"):
            eval_packages(
                tmp_path / "nonexistent",
                output_dir=tmp_path / "workspace",
            )


class TestCLIEval:
    """CLI eval 命令测试。"""

    def test_eval_help(self) -> None:
        """eval --help 正常输出。"""
        from typer.testing import CliRunner

        from cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["eval", "--help"])
        assert result.exit_code == 0
        assert "--package-dir" in result.output

    def test_eval_agent_mode_not_implemented(self) -> None:
        """--eval-mode agent 提示未实现。"""
        from typer.testing import CliRunner

        from cli import app

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "eval",
                "--package-dir",
                "/tmp/test",
                "--rule-set",
                "/tmp/rule.yaml",
                "--eval-mode",
                "agent",
            ],
        )
        assert result.exit_code == 1
        assert "尚未实现" in result.output

    def test_eval_missing_required_args(self) -> None:
        """缺少必要参数时报错。"""
        from typer.testing import CliRunner

        from cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["eval"])
        assert result.exit_code != 0
