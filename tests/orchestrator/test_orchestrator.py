"""Orchestrator 单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_eval.core.exceptions import OrchestratorError
from agent_eval.orchestrator.orchestrator import EvalResult, Orchestrator
from agent_eval.storage.package import ExecutionPackage
from agent_eval.storage.workspace import Workspace


class TestOrchestratorInit:
    """Orchestrator 初始化测试。"""

    def test_default_init(self) -> None:
        """默认初始化创建默认 PipelineEngine。"""
        orch = Orchestrator()
        assert orch.pipeline_engine is not None
        assert orch.report_generator is not None
        assert orch.workspace is not None

    def test_custom_workspace(self, tmp_path: Path) -> None:
        """自定义 Workspace。"""
        ws = Workspace(root_dir=tmp_path / "ws")
        orch = Orchestrator(workspace=ws)
        assert orch.workspace.root == tmp_path / "ws"


class TestLoadPackages:
    """包加载测试。"""

    def test_load_single_package(self, golden_package: Path) -> None:
        """加载单个 ExecutionPackage 目录。"""
        orch = Orchestrator()
        packages = orch._load_packages(golden_package)
        assert len(packages) == 1
        assert isinstance(packages[0], ExecutionPackage)
        assert packages[0].manifest.package_id == "pkg_test_001"

    def test_load_multiple_packages(self, golden_package: Path) -> None:
        """加载包含多个子目录的目录。"""
        parent = golden_package.parent
        orch = Orchestrator()
        packages = orch._load_packages(parent)
        assert len(packages) >= 1

    def test_load_nonexistent_dir(self, tmp_path: Path) -> None:
        """加载不存在的目录。"""
        orch = Orchestrator()
        with pytest.raises(OrchestratorError, match="不存在"):
            orch._load_packages(tmp_path / "nonexistent")

    def test_load_empty_dir(self, tmp_path: Path) -> None:
        """加载无 manifest 的空目录。"""
        empty = tmp_path / "empty"
        empty.mkdir()
        orch = Orchestrator()
        with pytest.raises(OrchestratorError, match="未找到"):
            orch._load_packages(empty)

    def test_load_dir_with_mixed_content(self, tmp_path: Path) -> None:
        """混合内容目录：仅加载含 manifest.json 的子目录。"""
        # 有效包
        pkg1 = tmp_path / "pkg1"
        pkg1.mkdir()
        manifest = {
            "package_id": "pkg_1",
            "created_at": "2026-06-09T12:00:00+00:00",
            "task_id": "t1",
        }
        (pkg1 / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (pkg1 / "output").mkdir()
        (pkg1 / "output" / "index.md").write_text("# Test", encoding="utf-8")

        # 无效目录（无 manifest）
        (tmp_path / "not_a_pkg").mkdir()

        orch = Orchestrator()
        packages = orch._load_packages(tmp_path)
        assert len(packages) == 1
        assert packages[0].manifest.package_id == "pkg_1"


class TestEvalOnly:
    """eval_only 完整流程测试。"""

    def test_eval_only_single_package(
        self,
        golden_package: Path,
        workspace: Workspace,
    ) -> None:
        """对单个包执行 eval_only。"""
        orch = Orchestrator(workspace=workspace)
        result = orch.eval_only(golden_package)

        assert isinstance(result, EvalResult)
        assert result.report.total_samples == 1
        assert result.report.run_id != ""
        assert len(result.results) >= 1
        assert result.run_workspace is not None

    def test_eval_only_generates_result_files(
        self,
        golden_package: Path,
        workspace: Workspace,
    ) -> None:
        """eval_only 生成完整的 EvaluationResult 文件。"""
        orch = Orchestrator(workspace=workspace)
        result = orch.eval_only(golden_package)

        run_ws = result.run_workspace
        assert run_ws is not None

        # 验证结果目录
        result_dirs = run_ws.list_results()
        assert len(result_dirs) >= 1

        task_id = result_dirs[0]
        result_dir = run_ws.get_result_dir(task_id)
        assert (result_dir / "manifest.json").exists()
        assert (result_dir / "rule_results.json").exists()
        assert (result_dir / "scores.json").exists()
        assert (result_dir / "report.md").exists()
        assert (result_dir / "report.json").exists()
        assert (result_dir / "evidence").is_dir()

    def test_eval_only_generates_summary(
        self,
        golden_package: Path,
        workspace: Workspace,
    ) -> None:
        """eval_only 生成聚合报告。"""
        orch = Orchestrator(workspace=workspace)
        result = orch.eval_only(golden_package)

        run_ws = result.run_workspace
        assert (run_ws.reports_dir / "summary.md").exists()
        assert (run_ws.reports_dir / "summary.json").exists()

        # summary.json 可解析
        summary = json.loads(
            (run_ws.reports_dir / "summary.json").read_text(encoding="utf-8"),
        )
        assert "run_id" in summary
        assert "metrics" in summary

    def test_eval_only_updates_workspace_index(
        self,
        golden_package: Path,
        workspace: Workspace,
    ) -> None:
        """eval_only 更新 workspace index。"""
        orch = Orchestrator(workspace=workspace)
        result = orch.eval_only(golden_package)

        index_file = workspace.index_dir / "runs_index.json"
        assert index_file.exists()

        index = json.loads(index_file.read_text(encoding="utf-8"))
        assert len(index["runs"]) == 1
        assert index["runs"][0]["run_id"] == result.run_id
        assert "metrics" in index["runs"][0]

    def test_eval_only_with_project(
        self,
        golden_package: Path,
        workspace: Workspace,
    ) -> None:
        """eval_only 写入 project 信息。"""
        orch = Orchestrator(workspace=workspace)
        orch.eval_only(golden_package, project="math_course")

        index = json.loads(
            (workspace.index_dir / "runs_index.json").read_text(encoding="utf-8"),
        )
        assert index["runs"][0]["project"] == "math_course"

    def test_eval_only_saves_cache(
        self,
        golden_package: Path,
        workspace: Workspace,
    ) -> None:
        """eval_only 保存缓存到磁盘。"""
        orch = Orchestrator(workspace=workspace)
        orch.eval_only(golden_package)

        cache_file = workspace.cache_dir / "evaluation_cache.json"
        assert cache_file.exists()

        cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert len(cache_data) > 0


class TestLoadPackagesErrorPaths:
    """包加载错误路径测试。"""

    def test_load_single_package_with_invalid_manifest(self, tmp_path: Path) -> None:
        """单个包目录 manifest.json 存在但内容无效 → OrchestratorError。"""
        pkg_dir = tmp_path / "bad_pkg"
        pkg_dir.mkdir()
        # manifest.json 存在但内容不是合法 ExecutionPackage
        (pkg_dir / "manifest.json").write_text("not valid json{{{", encoding="utf-8")
        (pkg_dir / "output").mkdir()
        (pkg_dir / "output" / "index.md").write_text("# Test", encoding="utf-8")

        orch = Orchestrator()
        with pytest.raises(OrchestratorError, match="加载执行包失败"):
            orch._load_packages(pkg_dir)

    def test_load_packages_skips_invalid_subdir(self, tmp_path: Path, golden_package: Path) -> None:
        """子目录含 manifest.json 但加载失败时跳过（不中断）。"""
        # 有效包在 golden_package 的父目录
        parent = tmp_path / "pkgs"
        parent.mkdir()

        # 复制 golden 包
        import shutil

        good = parent / "good_pkg"
        shutil.copytree(golden_package, good)

        # 无效包：有 manifest 但内容错误
        bad = parent / "bad_pkg"
        bad.mkdir()
        (bad / "manifest.json").write_text("{bad json", encoding="utf-8")

        orch = Orchestrator()
        packages = orch._load_packages(parent)
        # 至少加载了有效包，无效包被跳过
        assert len(packages) >= 1
        assert packages[0].manifest.package_id == "pkg_test_001"


class TestCacheErrorPaths:
    """缓存错误路径测试。"""

    def test_load_corrupt_cache_file(self, tmp_path: Path) -> None:
        """缓存文件损坏时不崩溃。"""
        from agent_eval.evaluation.engine import build_default_pipeline
        from agent_eval.evaluation.registry import registry

        ws = Workspace(root_dir=tmp_path / "ws")
        ws.ensure_dirs()

        # 写入损坏的缓存文件
        cache_file = ws.cache_dir / "evaluation_cache.json"
        cache_file.write_text("this is not json {{{", encoding="utf-8")

        engine = build_default_pipeline(registry)
        orch = Orchestrator(pipeline_engine=engine, workspace=ws)

        # 应该不抛异常，只是 warning
        orch._load_cache(ws, engine)
        assert len(engine._cache) == 0

    def test_load_cache_with_corrupt_entry(self, tmp_path: Path) -> None:
        """缓存文件合法 JSON 但条目损坏时不崩溃。"""
        from agent_eval.evaluation.engine import build_default_pipeline
        from agent_eval.evaluation.registry import registry

        ws = Workspace(root_dir=tmp_path / "ws")
        ws.ensure_dirs()

        # 写入含损坏条目的缓存
        cache_file = ws.cache_dir / "evaluation_cache.json"
        cache_data = {
            "key1": {"invalid": "structure", "missing_fields": True},
            "key2": {"also_invalid": 123},
        }
        cache_file.write_text(json.dumps(cache_data), encoding="utf-8")

        engine = build_default_pipeline(registry)
        orch = Orchestrator(pipeline_engine=engine, workspace=ws)

        orch._load_cache(ws, engine)
        # 所有条目都损坏，cache 应为空
        assert len(engine._cache) == 0

    def test_save_cache_readonly_dir(self, tmp_path: Path) -> None:
        """缓存保存到只读目录时不崩溃。"""
        from agent_eval.evaluation.engine import build_default_pipeline
        from agent_eval.evaluation.registry import registry

        ws = Workspace(root_dir=tmp_path / "ws")
        ws.ensure_dirs()

        engine = build_default_pipeline(registry)
        orch = Orchestrator(pipeline_engine=engine, workspace=ws)

        # 让 cache_dir 变为不可写（通过 monkey-patch write_text）
        import unittest.mock

        with unittest.mock.patch.object(
            type(ws.cache_dir / "evaluation_cache.json"),
            "write_text",
            side_effect=PermissionError("read-only"),
        ):
            # 应该不抛异常，只是 warning
            orch._save_cache(ws, engine)


class TestWorkspaceIndexErrorPaths:
    """Workspace 索引错误路径测试。"""

    def test_index_with_corrupt_existing_runs(self, tmp_path: Path, golden_package: Path) -> None:
        """已有 runs_index.json 中 runs 不是 list 时自动修复。"""
        ws = Workspace(root_dir=tmp_path / "ws")
        ws.ensure_dirs()

        # 写入格式错误的索引（runs 不是 list）
        index_file = ws.index_dir / "runs_index.json"
        index_file.write_text(json.dumps({"runs": "not_a_list"}), encoding="utf-8")

        orch = Orchestrator(workspace=ws)
        orch.eval_only(golden_package)

        # 索引应被修复为包含正确条目
        index = json.loads(index_file.read_text(encoding="utf-8"))
        assert isinstance(index["runs"], list)
        assert len(index["runs"]) == 1

    def test_index_update_with_readonly_file(self, tmp_path: Path) -> None:
        """索引文件写入失败时不崩溃。"""
        from agent_eval.evaluation.models import MetricsReport, SampleScore

        ws = Workspace(root_dir=tmp_path / "ws")
        ws.ensure_dirs()

        # 创建只读索引文件
        index_file = ws.index_dir / "runs_index.json"
        index_file.write_text("{}", encoding="utf-8")

        orch = Orchestrator(workspace=ws)
        metrics = MetricsReport(
            run_id="test",
            total_samples=1,
            dr=1.0,
            cpr=1.0,
            avg_reward=1.0,
            cond_r=1.0,
            avg_time_ms=100,
            sample_scores=[],
            failure_breakdown={},
            thresholds={},
        )

        import unittest.mock

        with unittest.mock.patch.object(
            type(index_file),
            "write_text",
            side_effect=PermissionError("read-only"),
        ):
            # 应该不抛异常
            orch._update_workspace_index(ws, ws.create_run("test_run"), metrics, None)


class TestCachePersistence:
    """缓存持久化测试。"""

    def test_cache_hit_on_repeat_eval(
        self,
        golden_package: Path,
        workspace: Workspace,
    ) -> None:
        """重复评估命中缓存。"""
        orch = Orchestrator(workspace=workspace)

        # 第一次评估
        result1 = orch.eval_only(golden_package)

        # 创建新 Orchestrator 加载缓存
        orch2 = Orchestrator(workspace=workspace)
        result2 = orch2.eval_only(golden_package)

        # 两次结果一致
        assert result1.report.total_samples == result2.report.total_samples

    def test_cache_load_from_disk(
        self,
        golden_package: Path,
        workspace: Workspace,
    ) -> None:
        """从磁盘加载缓存。"""
        orch = Orchestrator(workspace=workspace)
        orch.eval_only(golden_package)

        # 新 engine 加载缓存
        from agent_eval.evaluation.engine import build_default_pipeline
        from agent_eval.evaluation.registry import registry

        engine = build_default_pipeline(registry)
        orch2 = Orchestrator(pipeline_engine=engine, workspace=workspace)
        orch2._load_cache(workspace, engine)

        assert len(engine._cache) > 0
