"""PackageBuilder 测试（内联模式 + 目录模式）。"""

import json
from pathlib import Path

import pytest

from agent_eval.execution.models import Task
from agent_eval.storage.builder import PackageBuilder
from agent_eval.storage.package import ExecutionPackage

FIXTURES = Path(__file__).parent.parent / "fixtures"
GOLDEN = FIXTURES / "golden"


@pytest.fixture
def builder() -> PackageBuilder:
    return PackageBuilder()


@pytest.fixture
def sample_task() -> Task:
    return Task(
        id="math_grade7_001",
        input={"subject": "math", "grade": 7, "topic": "一元一次方程"},
        constraints={"min_documents": 1, "max_documents": 10},
    )


@pytest.fixture
def directory_task() -> Task:
    return Task(
        id="dir_test_001",
        input={"subject": "综合", "grade": 3, "topic": "大单元学习总导"},
        input_mode="directory",
        file_patterns=["*.html"],
    )


class TestBuildInline:
    def test_build_inline_basic(
        self, builder: PackageBuilder, sample_task: Task, tmp_path: Path,
    ) -> None:
        output_files = [
            GOLDEN / "valid_docset" / "output" / "index.md",
            GOLDEN / "valid_docset" / "output" / "chapter_01.md",
        ]
        pkg_dir = builder.build_inline(
            task=sample_task,
            output_files=output_files,
            package_dir=tmp_path / "pkg",
            run_id="20260609_100000",
        )

        assert pkg_dir.exists()
        assert (pkg_dir / "manifest.json").exists()
        assert (pkg_dir / "task.json").exists()
        assert (pkg_dir / "metadata.json").exists()
        assert (pkg_dir / "trace.json").exists()
        assert (pkg_dir / "metrics.json").exists()
        assert (pkg_dir / "output").exists()

    def test_build_inline_copies_files(
        self, builder: PackageBuilder, sample_task: Task, tmp_path: Path,
    ) -> None:
        output_files = [
            GOLDEN / "valid_docset" / "output" / "index.md",
            GOLDEN / "valid_docset" / "output" / "chapter_01.md",
        ]
        pkg_dir = builder.build_inline(
            task=sample_task,
            output_files=output_files,
            package_dir=tmp_path / "pkg",
            run_id="20260609_100000",
        )

        output_dir = pkg_dir / "output"
        files = list(output_dir.iterdir())
        assert len(files) == 2

    def test_build_inline_manifest_content(
        self, builder: PackageBuilder, sample_task: Task, tmp_path: Path,
    ) -> None:
        pkg_dir = builder.build_inline(
            task=sample_task,
            output_files=[GOLDEN / "valid_docset" / "output" / "index.md"],
            package_dir=tmp_path / "pkg",
            run_id="20260609_100000",
        )

        manifest = json.loads((pkg_dir / "manifest.json").read_text())
        assert manifest["package_id"] == "pkg_20260609_100000_math_grade7_001"
        assert manifest["task_id"] == "math_grade7_001"
        assert manifest["status"] == "success"

    def test_build_inline_task_json(
        self, builder: PackageBuilder, sample_task: Task, tmp_path: Path,
    ) -> None:
        pkg_dir = builder.build_inline(
            task=sample_task,
            output_files=[GOLDEN / "valid_docset" / "output" / "index.md"],
            package_dir=tmp_path / "pkg",
            run_id="20260609_100000",
        )

        task_data = json.loads((pkg_dir / "task.json").read_text())
        assert task_data["id"] == "math_grade7_001"
        assert task_data["input"]["subject"] == "math"


class TestBuildDirectory:
    def test_build_directory_basic(
        self, builder: PackageBuilder, directory_task: Task, tmp_path: Path,
    ) -> None:
        pkg_dir = builder.build_directory(
            task=directory_task,
            source_dir=GOLDEN / "directory_sample",
            package_dir=tmp_path / "pkg",
            run_id="20260609_100000",
        )

        assert pkg_dir.exists()
        assert (pkg_dir / "manifest.json").exists()
        assert (pkg_dir / "task.json").exists()
        assert (pkg_dir / "output").exists()
        assert (pkg_dir / "output" / "_manifest.json").exists()

    def test_build_directory_manifest(
        self, builder: PackageBuilder, directory_task: Task, tmp_path: Path,
    ) -> None:
        pkg_dir = builder.build_directory(
            task=directory_task,
            source_dir=GOLDEN / "directory_sample",
            package_dir=tmp_path / "pkg",
            run_id="20260609_100000",
        )

        dir_manifest = json.loads(
            (pkg_dir / "output" / "_manifest.json").read_text(),
        )
        assert dir_manifest["mode"] == "directory"
        assert dir_manifest["total_files"] == 4
        assert len(dir_manifest["modules"]) == 2

    def test_build_directory_metrics(
        self, builder: PackageBuilder, directory_task: Task, tmp_path: Path,
    ) -> None:
        pkg_dir = builder.build_directory(
            task=directory_task,
            source_dir=GOLDEN / "directory_sample",
            package_dir=tmp_path / "pkg",
            run_id="20260609_100000",
        )

        metrics = json.loads((pkg_dir / "metrics.json").read_text())
        assert metrics["total_files"] == 4
        assert metrics["modules"] == 2

    def test_build_directory_nonexistent_source(
        self, builder: PackageBuilder, directory_task: Task, tmp_path: Path,
    ) -> None:
        with pytest.raises(FileNotFoundError):
            builder.build_directory(
                task=directory_task,
                source_dir=tmp_path / "nonexistent",
                package_dir=tmp_path / "pkg",
            )


class TestValidatePackage:
    def test_valid_package(
        self, builder: PackageBuilder, sample_task: Task, tmp_path: Path,
    ) -> None:
        pkg_dir = builder.build_inline(
            task=sample_task,
            output_files=[GOLDEN / "valid_docset" / "output" / "index.md"],
            package_dir=tmp_path / "pkg",
            run_id="20260609_100000",
        )
        missing = builder.validate_package(pkg_dir)
        assert missing == []

    def test_missing_files(self, builder: PackageBuilder, tmp_path: Path) -> None:
        """空目录应报告所有必要文件缺失。"""
        pkg_dir = tmp_path / "empty_pkg"
        pkg_dir.mkdir()
        missing = builder.validate_package(pkg_dir)
        assert len(missing) > 0
        assert "manifest.json" in missing


class TestExecutionPackageLoad:
    def test_load_inline_package(
        self, builder: PackageBuilder, sample_task: Task, tmp_path: Path,
    ) -> None:
        pkg_dir = builder.build_inline(
            task=sample_task,
            output_files=[GOLDEN / "valid_docset" / "output" / "index.md"],
            package_dir=tmp_path / "pkg",
            run_id="20260609_100000",
        )

        pkg = ExecutionPackage.load(pkg_dir)
        assert pkg.manifest.task_id == "math_grade7_001"
        assert pkg.manifest.package_id == "pkg_20260609_100000_math_grade7_001"
        assert pkg.task_data["id"] == "math_grade7_001"
        assert pkg.output_dir is not None

    def test_load_directory_package(
        self, builder: PackageBuilder, directory_task: Task, tmp_path: Path,
    ) -> None:
        pkg_dir = builder.build_directory(
            task=directory_task,
            source_dir=GOLDEN / "directory_sample",
            package_dir=tmp_path / "pkg",
            run_id="20260609_100000",
        )

        pkg = ExecutionPackage.load(pkg_dir)
        assert pkg.directory_manifest is not None
        assert pkg.directory_manifest.total_files == 4
        assert len(pkg.directory_manifest.modules) == 2

    def test_save_and_reload(
        self, builder: PackageBuilder, sample_task: Task, tmp_path: Path,
    ) -> None:
        pkg_dir = builder.build_inline(
            task=sample_task,
            output_files=[GOLDEN / "valid_docset" / "output" / "index.md"],
            package_dir=tmp_path / "pkg",
            run_id="20260609_100000",
        )

        pkg = ExecutionPackage.load(pkg_dir)
        save_dir = tmp_path / "saved_pkg"
        pkg.save(save_dir)

        pkg2 = ExecutionPackage.load(save_dir)
        assert pkg2.manifest.task_id == pkg.manifest.task_id
