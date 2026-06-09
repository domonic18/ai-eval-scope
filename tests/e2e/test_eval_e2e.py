"""端到端测试 — 从黄金样本到报告输出的完整流程。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_eval.orchestrator.orchestrator import EvalResult, Orchestrator
from agent_eval.storage.package import EvaluationResult
from agent_eval.storage.workspace import Workspace

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _build_golden_package(tmp_path: Path, golden_name: str) -> Path:
    """从 golden 样本构建 ExecutionPackage 并返回包目录。"""
    golden_dir = FIXTURES / "golden" / golden_name
    if not golden_dir.exists():
        pytest.skip(f"Golden sample {golden_name} not found")

    pkg_dir = tmp_path / "packages" / f"task_{golden_name}"
    pkg_dir.mkdir(parents=True)

    # 复制 golden 样本
    output_dir = pkg_dir / "output"
    output_dir.mkdir()
    for f in golden_dir.rglob("*"):
        if f.is_file():
            rel = f.relative_to(golden_dir)
            target = pkg_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f.read_bytes())

    # 写入 manifest.json
    manifest = {
        "package_id": f"pkg_{golden_name}",
        "created_at": "2026-06-09T12:00:00+00:00",
        "task_id": f"task_{golden_name}",
        "sut_config_id": "manual",
        "status": "success",
    }
    (pkg_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 写入 task.json
    task_data = {
        "id": f"task_{golden_name}",
        "input": {"title": golden_name},
        "constraints": {},
    }
    (pkg_dir / "task.json").write_text(
        json.dumps(task_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 写入 metadata.json
    metadata = {"sut_name": "manual", "eval_system_version": "0.1.0"}
    (pkg_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return pkg_dir


class TestValidDocsetE2E:
    """valid_docset 黄金样本端到端测试。"""

    def test_full_eval_flow(self, tmp_path: Path) -> None:
        """黄金样本完整评估流程。"""
        pkg_dir = _build_golden_package(tmp_path, "valid_docset")
        ws = Workspace(root_dir=tmp_path / "workspace")
        ws.ensure_dirs()

        orch = Orchestrator(workspace=ws)
        result = orch.eval_only(pkg_dir)

        # 基本结果验证
        assert isinstance(result, EvalResult)
        assert result.report.total_samples == 1
        assert result.run_id != ""

    def test_result_directory_structure(self, tmp_path: Path) -> None:
        """输出目录结构完整。"""
        pkg_dir = _build_golden_package(tmp_path, "valid_docset")
        ws = Workspace(root_dir=tmp_path / "workspace")
        ws.ensure_dirs()

        orch = Orchestrator(workspace=ws)
        result = orch.eval_only(pkg_dir)

        run_ws = result.run_workspace
        assert run_ws is not None
        result_dirs = run_ws.list_results()
        assert len(result_dirs) >= 1

        task_id = result_dirs[0]
        result_dir = run_ws.get_result_dir(task_id)

        # 6 个文件 + evidence 目录
        assert (result_dir / "manifest.json").exists()
        assert (result_dir / "rule_results.json").exists()
        assert (result_dir / "scores.json").exists()
        assert (result_dir / "report.md").exists()
        assert (result_dir / "report.json").exists()
        assert (result_dir / "evidence").is_dir()

    def test_rule_results_json_format(self, tmp_path: Path) -> None:
        """rule_results.json 格式正确。"""
        pkg_dir = _build_golden_package(tmp_path, "valid_docset")
        ws = Workspace(root_dir=tmp_path / "workspace")
        ws.ensure_dirs()

        orch = Orchestrator(workspace=ws)
        result = orch.eval_only(pkg_dir)

        run_ws = result.run_workspace
        task_id = run_ws.list_results()[0]
        rr_file = run_ws.get_result_dir(task_id) / "rule_results.json"

        rule_results = json.loads(rr_file.read_text(encoding="utf-8"))
        assert isinstance(rule_results, list)
        assert len(rule_results) > 0

        # 每个条目包含必要字段
        for entry in rule_results:
            assert "constraint_id" in entry
            assert "passed" in entry
            assert "score" in entry
            assert "tier" in entry

    def test_scores_json_format(self, tmp_path: Path) -> None:
        """scores.json 格式正确。"""
        pkg_dir = _build_golden_package(tmp_path, "valid_docset")
        ws = Workspace(root_dir=tmp_path / "workspace")
        ws.ensure_dirs()

        orch = Orchestrator(workspace=ws)
        result = orch.eval_only(pkg_dir)

        run_ws = result.run_workspace
        task_id = run_ws.list_results()[0]
        scores_file = run_ws.get_result_dir(task_id) / "scores.json"

        scores = json.loads(scores_file.read_text(encoding="utf-8"))
        assert "s_format" in scores
        assert "s_common" in scores
        assert "reward" in scores

    def test_report_markdown_readable(self, tmp_path: Path) -> None:
        """report.md 人类可读。"""
        pkg_dir = _build_golden_package(tmp_path, "valid_docset")
        ws = Workspace(root_dir=tmp_path / "workspace")
        ws.ensure_dirs()

        orch = Orchestrator(workspace=ws)
        result = orch.eval_only(pkg_dir)

        run_ws = result.run_workspace
        task_id = run_ws.list_results()[0]
        md_file = run_ws.get_result_dir(task_id) / "report.md"

        md_content = md_file.read_text(encoding="utf-8")
        assert "# 评估报告" in md_content
        assert "Reward" in md_content

    def test_report_json_parseable(self, tmp_path: Path) -> None:
        """report.json 可解析。"""
        pkg_dir = _build_golden_package(tmp_path, "valid_docset")
        ws = Workspace(root_dir=tmp_path / "workspace")
        ws.ensure_dirs()

        orch = Orchestrator(workspace=ws)
        result = orch.eval_only(pkg_dir)

        run_ws = result.run_workspace
        task_id = run_ws.list_results()[0]
        json_file = run_ws.get_result_dir(task_id) / "report.json"

        report = json.loads(json_file.read_text(encoding="utf-8"))
        assert "sample_id" in report
        assert "stage_results" in report

    def test_summary_reports(self, tmp_path: Path) -> None:
        """聚合报告生成。"""
        pkg_dir = _build_golden_package(tmp_path, "valid_docset")
        ws = Workspace(root_dir=tmp_path / "workspace")
        ws.ensure_dirs()

        orch = Orchestrator(workspace=ws)
        result = orch.eval_only(pkg_dir)

        run_ws = result.run_workspace
        summary_md = run_ws.reports_dir / "summary.md"
        summary_json = run_ws.reports_dir / "summary.json"

        assert summary_md.exists()
        assert summary_json.exists()

        md_content = summary_md.read_text(encoding="utf-8")
        assert "聚合报告" in md_content
        assert "DR" in md_content

        json_content = json.loads(summary_json.read_text(encoding="utf-8"))
        assert "metrics" in json_content

    def test_workspace_index_updated(self, tmp_path: Path) -> None:
        """workspace index 正确更新。"""
        pkg_dir = _build_golden_package(tmp_path, "valid_docset")
        ws = Workspace(root_dir=tmp_path / "workspace")
        ws.ensure_dirs()

        orch = Orchestrator(workspace=ws)
        orch.eval_only(pkg_dir, project="e2e_test")

        index_file = ws.index_dir / "runs_index.json"
        assert index_file.exists()

        index = json.loads(index_file.read_text(encoding="utf-8"))
        assert index["runs"][0]["project"] == "e2e_test"
        assert "metrics" in index["runs"][0]
        assert "DR" in index["runs"][0]["metrics"]

    def test_valid_docset_passes_format_gate(self, tmp_path: Path) -> None:
        """valid_docset 通过格式门控。"""
        pkg_dir = _build_golden_package(tmp_path, "valid_docset")
        ws = Workspace(root_dir=tmp_path / "workspace")
        ws.ensure_dirs()

        orch = Orchestrator(workspace=ws)
        result = orch.eval_only(pkg_dir)

        assert result.report.dr == 1.0  # 所有样本通过格式门控

    def test_eval_result_loadable(self, tmp_path: Path) -> None:
        """EvaluationResult 可从磁盘加载。"""
        pkg_dir = _build_golden_package(tmp_path, "valid_docset")
        ws = Workspace(root_dir=tmp_path / "workspace")
        ws.ensure_dirs()

        orch = Orchestrator(workspace=ws)
        result = orch.eval_only(pkg_dir)

        run_ws = result.run_workspace
        task_id = run_ws.list_results()[0]
        result_dir = run_ws.get_result_dir(task_id)

        loaded = EvaluationResult.load(result_dir)
        assert loaded.manifest.result_id != ""
        assert loaded.manifest.package_id == "pkg_valid_docset"
        assert len(loaded.rule_results) > 0
        assert loaded.scores.reward != 0.0


class TestFormatInvalidE2E:
    """format_invalid 黄金样本端到端测试。"""

    def test_format_invalid_fails_gate(self, tmp_path: Path) -> None:
        """format_invalid 应在格式门控失败。"""
        pkg_dir = _build_golden_package(tmp_path, "format_invalid")
        ws = Workspace(root_dir=tmp_path / "workspace")
        ws.ensure_dirs()

        orch = Orchestrator(workspace=ws)
        result = orch.eval_only(pkg_dir)

        # 格式门控失败 → DR = 0
        assert result.report.dr == 0.0
        assert result.report.total_samples == 1


class TestCacheBehavior:
    """缓存行为测试。"""

    def test_second_eval_uses_cache(self, tmp_path: Path) -> None:
        """第二次评估命中缓存。"""
        pkg_dir = _build_golden_package(tmp_path, "valid_docset")
        ws = Workspace(root_dir=tmp_path / "workspace")
        ws.ensure_dirs()

        # 第一次
        orch1 = Orchestrator(workspace=ws)
        result1 = orch1.eval_only(pkg_dir)

        # 第二次（新 Orchestrator 加载缓存）
        orch2 = Orchestrator(workspace=ws)
        result2 = orch2.eval_only(pkg_dir)

        # 结果一致
        assert result1.report.dr == result2.report.dr
        assert result1.report.avg_reward == result2.report.avg_reward

    def test_cache_file_exists_after_eval(self, tmp_path: Path) -> None:
        """评估后缓存文件存在。"""
        pkg_dir = _build_golden_package(tmp_path, "valid_docset")
        ws = Workspace(root_dir=tmp_path / "workspace")
        ws.ensure_dirs()

        orch = Orchestrator(workspace=ws)
        orch.eval_only(pkg_dir)

        cache_file = ws.cache_dir / "evaluation_cache.json"
        assert cache_file.exists()

        cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert len(cache_data) > 0
        # 每个缓存条目包含 sample_id
        for key, val in cache_data.items():
            assert "sample_id" in val
