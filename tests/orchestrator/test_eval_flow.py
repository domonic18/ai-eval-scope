"""SDK eval 接口 + CLI eval 集成测试。"""

from __future__ import annotations

import json
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

    def test_eval_packages_with_project(
        self, golden_package: Path, tmp_path: Path
    ) -> None:
        """SDK eval 带 project 参数。"""
        output_dir = tmp_path / "workspace"
        result = eval_packages(
            golden_package,
            output_dir=output_dir,
            project="math_course_v2",
        )

        assert isinstance(result, EvalResult)

        # 验证 project 写入 index
        index_file = Path(output_dir) / "index" / "runs_index.json"
        assert index_file.exists()
        index = json.loads(index_file.read_text(encoding="utf-8"))
        assert any(
            r.get("project") == "math_course_v2" for r in index["runs"]
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

    def test_eval_full_execution(
        self, golden_package: Path, tmp_path: Path
    ) -> None:
        """CLI eval 完整执行流程：加载包 → 评估 → 输出报告。"""
        from typer.testing import CliRunner

        from cli import app

        rule_set_path = FIXTURES / "configs" / "rule_set.yaml"
        if not rule_set_path.exists():
            pytest.skip("rule_set.yaml fixture 不存在")

        output_dir = tmp_path / "cli_workspace"

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "eval",
                "--package-dir", str(golden_package),
                "--rule-set", str(rule_set_path),
                "--output-dir", str(output_dir),
            ],
        )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert "评估完成" in result.output

        # 验证 workspace 输出
        assert (Path(output_dir) / "runs").is_dir()
        assert (Path(output_dir) / "index" / "runs_index.json").exists()

    def test_eval_with_verbose(
        self, golden_package: Path, tmp_path: Path
    ) -> None:
        """CLI eval --verbose 模式。"""
        from typer.testing import CliRunner

        from cli import app

        rule_set_path = FIXTURES / "configs" / "rule_set.yaml"
        if not rule_set_path.exists():
            pytest.skip("rule_set.yaml fixture 不存在")

        output_dir = tmp_path / "verbose_workspace"

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "eval",
                "--package-dir", str(golden_package),
                "--rule-set", str(rule_set_path),
                "--output-dir", str(output_dir),
                "--verbose",
            ],
        )

        assert result.exit_code == 0, f"CLI failed: {result.output}"


class TestCLIPack:
    """CLI pack 命令测试。"""

    def test_pack_help(self) -> None:
        """pack --help 正常输出。"""
        from typer.testing import CliRunner

        from cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["pack", "--help"])
        assert result.exit_code == 0
        assert "--source-dir" in result.output
        assert "--files" in result.output

    def test_pack_directory_minimal(self, tmp_path: Path) -> None:
        """仅 --source-dir，自动推导 id/title。"""
        from typer.testing import CliRunner

        from cli import app

        # 准备源目录
        src = tmp_path / "my_course"
        src.mkdir()
        (src / "lesson.md").write_text("# 数学课", encoding="utf-8")

        output_dir = tmp_path / "packages"

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["pack", "--source-dir", str(src), "--output-dir", str(output_dir)],
        )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert "打包完成" in result.output

        # task-id 自动推导为目录名
        pkg_dir = output_dir / "my_course"
        assert pkg_dir.exists()
        assert (pkg_dir / "manifest.json").exists()
        assert (pkg_dir / "task.json").exists()

    def test_pack_inline_mode(self, tmp_path: Path) -> None:
        """--files 指定文件。"""
        from typer.testing import CliRunner

        from cli import app

        # 准备测试文件
        f1 = tmp_path / "doc1.md"
        f1.write_text("# 文档1", encoding="utf-8")
        f2 = tmp_path / "doc2.md"
        f2.write_text("# 文档2", encoding="utf-8")

        output_dir = tmp_path / "packages"

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "pack",
                "--files", str(f1),
                "--files", str(f2),
                "--output-dir", str(output_dir),
            ],
        )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert "文件数: 2" in result.output
        assert "打包完成" in result.output

    def test_pack_with_overrides(self, tmp_path: Path) -> None:
        """--task-id + --task-title 覆盖默认。"""
        from typer.testing import CliRunner

        from cli import app

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.md").write_text("# test", encoding="utf-8")

        output_dir = tmp_path / "packages"

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "pack",
                "--source-dir", str(src),
                "--task-id", "custom_id",
                "--task-title", "自定义标题",
                "--task-subject", "math",
                "--output-dir", str(output_dir),
            ],
        )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert (output_dir / "custom_id" / "manifest.json").exists()

        # 验证 task.json 包含覆盖值
        import json

        task = json.loads((output_dir / "custom_id" / "task.json").read_text())
        assert task["id"] == "custom_id"
        assert task["input"]["title"] == "自定义标题"
        assert task["input"]["subject"] == "math"

    def test_pack_no_source_error(self) -> None:
        """不指定 --files/--source-dir 报错。"""
        from typer.testing import CliRunner

        from cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["pack"])
        assert result.exit_code == 1

    def test_pack_with_validate(self, tmp_path: Path) -> None:
        """--validate 验证打包结果。"""
        from typer.testing import CliRunner

        from cli import app

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.md").write_text("# test", encoding="utf-8")

        output_dir = tmp_path / "packages"

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "pack",
                "--source-dir", str(src),
                "--output-dir", str(output_dir),
                "--validate",
            ],
        )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert "验证" in result.output

    def test_pack_then_eval(self, tmp_path: Path) -> None:
        """打包 → eval 端到端。"""
        from typer.testing import CliRunner

        from cli import app

        golden = FIXTURES / "golden" / "valid_docset" / "output"
        rule_set = FIXTURES / "configs" / "rule_set.yaml"
        if not rule_set.exists():
            pytest.skip("rule_set.yaml fixture 不存在")

        pack_dir = tmp_path / "packages"
        eval_ws = tmp_path / "workspace"

        runner = CliRunner()

        # Step 1: Pack
        result = runner.invoke(
            app,
            [
                "pack",
                "--files", str(golden / "index.md"),
                "--files", str(golden / "chapter_01.md"),
                "--task-id", "e2e_test",
                "--output-dir", str(pack_dir),
            ],
        )
        assert result.exit_code == 0, f"Pack failed: {result.output}"
        assert (pack_dir / "e2e_test" / "manifest.json").exists()

        # Step 2: Eval
        result = runner.invoke(
            app,
            [
                "eval",
                "--package-dir", str(pack_dir / "e2e_test"),
                "--rule-set", str(rule_set),
                "--output-dir", str(eval_ws),
            ],
        )
        assert result.exit_code == 0, f"Eval failed: {result.output}"
        assert "评估完成" in result.output