"""PackageBuilder — 手动打包工具。

将原始 Agent 产出物（Markdown/HTML 文档集）+ 任务定义打包为标准 ExecutionPackage。
支持两种模式：
  - 内联文件模式：直接指定文件列表
  - 目录模式（--directory）：指定目录路径，由 DirectoryCollector 自动遍历
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_eval.execution.models import Task
from agent_eval.storage.collector import DirectoryCollector
from agent_eval.storage.package import (
    PackageManifest,
    PackageMetadata,
    PackageStatus,
    generate_package_id,
    generate_run_id,
)


class PackageBuilder:
    """手动打包工具 — 将原始产出物打包为标准 ExecutionPackage。

    使用示例（内联模式）:
        builder = PackageBuilder()
        builder.build_inline(
            task=task,
            output_files=["output/index.md", "output/chapter_01.html"],
            package_dir=Path("workspace/runs/20260609/packages/task_001"),
        )

    使用示例（目录模式）:
        builder = PackageBuilder()
        builder.build_directory(
            task=task,
            source_dir=Path("/path/to/大单元学习总导/"),
            package_dir=Path("workspace/runs/20260609/packages/task_001"),
        )
    """

    @staticmethod
    def _reset_output_dir(package_dir: Path) -> Path:
        """重置 output 目录：已存在则先清空后重建，确保 pack 为覆盖语义。

        同一 task-id 的 package 跨次 pack 时，旧产物里"本次源不再包含"的文件
        会被清空，避免污染（如评 A 后评 B，B 不残留 A 的文件）。
        """
        output_dir = package_dir / "output"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def build_inline(
        self,
        task: Task,
        output_files: list[str | Path],
        package_dir: Path,
        run_id: str | None = None,
        status: PackageStatus = PackageStatus.SUCCESS,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """内联文件模式 — 直接指定文件列表打包。

        Args:
            task: 任务定义。
            output_files: 输出文件路径列表。
            package_dir: 执行包目标目录。
            run_id: 运行 ID。
            status: 执行状态。
            metadata: 额外元数据。

        Returns:
            执行包目录路径。
        """
        run_id = run_id or generate_run_id()
        package_id = generate_package_id(run_id, task.id)

        # 创建目录（output 覆盖语义：清空旧产物，避免跨次 pack 残留污染）
        package_dir.mkdir(parents=True, exist_ok=True)
        output_dir = self._reset_output_dir(package_dir)

        # 复制输出文件
        for src in output_files:
            src_path = Path(src)
            if src_path.exists() and src_path.is_file():
                dst = output_dir / src_path.name
                shutil.copy2(src_path, dst)

        # 写入 manifest.json
        manifest = PackageManifest(
            package_id=package_id,
            created_at=datetime.now(UTC).isoformat(),
            task_id=task.id,
            sut_config_id="manual",
            status=status,
        )
        (package_dir / "manifest.json").write_text(
            manifest.model_dump_json(indent=2),
            encoding="utf-8",
        )

        # 写入 task.json
        (package_dir / "task.json").write_text(
            task.model_dump_json(indent=2),
            encoding="utf-8",
        )

        # 写入 metadata.json
        pkg_metadata = PackageMetadata(
            sut_name="manual",
            eval_system_version="0.1.0",
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )
        if metadata:
            for k, v in metadata.items():
                if hasattr(pkg_metadata, k):
                    setattr(pkg_metadata, k, v)
        (package_dir / "metadata.json").write_text(
            pkg_metadata.model_dump_json(indent=2),
            encoding="utf-8",
        )

        # 写入 trace.json
        now = datetime.now(UTC).isoformat()
        trace = {
            "request": {"method": "manual", "source": "PackageBuilder"},
            "response": {"status": "manual_package"},
            "started_at": now,
            "finished_at": now,
            "error": None,
        }
        (package_dir / "trace.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 写入 metrics.json
        copied_count = len(list(output_dir.iterdir())) if output_dir.exists() else 0
        metrics = {
            "total_duration_ms": 0,
            "steps": 1,
            "retries": 0,
            "tool_calls": 0,
            "dead_end": False,
            "files_copied": copied_count,
        }
        (package_dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return package_dir

    def build_directory(
        self,
        task: Task,
        source_dir: Path,
        package_dir: Path,
        run_id: str | None = None,
        status: PackageStatus = PackageStatus.SUCCESS,
        metadata: dict[str, Any] | None = None,
        content_hash: str | None = None,
    ) -> Path:
        """目录模式 — 自动遍历目录结构打包。

        使用 DirectoryCollector 自动遍历源目录，收集匹配文件，
        生成 _manifest.json 清单，并将整个目录结构复制到执行包。

        Args:
            task: 任务定义。
            source_dir: 源目录路径（待收集的产出物目录）。
            package_dir: 执行包目标目录。
            run_id: 运行 ID。
            status: 执行状态。
            metadata: 额外元数据。

        Returns:
            执行包目录路径。
        """
        run_id = run_id or generate_run_id()
        package_id = generate_package_id(run_id, task.id)

        if not source_dir.exists():
            raise FileNotFoundError(f"源目录不存在: {source_dir}")
        if not source_dir.is_dir():
            raise NotADirectoryError(f"不是目录: {source_dir}")

        # 使用 DirectoryCollector 收集文件
        file_patterns = task.file_patterns or ["*.html", "*.htm"]
        collector = DirectoryCollector(
            root_dir=source_dir,
            file_patterns=file_patterns,
        )
        manifest_data = collector.collect()

        # 创建目录（output 覆盖语义：清空旧产物，避免跨次 pack 残留污染）
        package_dir.mkdir(parents=True, exist_ok=True)
        output_dir = self._reset_output_dir(package_dir)

        # 排除系统/隐藏文件（.DS_Store、Thumbs.db、._* 等）
        _ignore = shutil.ignore_patterns(".DS_Store", "Thumbs.db", "._*", "__MACOSX")

        # 复制整个目录结构到 output/
        for item in source_dir.iterdir():
            if item.name in collector.exclude_dirs:
                continue
            if item.is_file():
                if item.name.startswith("."):
                    continue
                if collector._matches_pattern(item):
                    shutil.copy2(item, output_dir / item.name)
            elif item.is_dir():
                shutil.copytree(item, output_dir / item.name, dirs_exist_ok=True, ignore=_ignore)

        # 写入 _manifest.json
        collector.write_manifest(manifest_data, output_dir)

        # 写入 manifest.json
        pkg_manifest = PackageManifest(
            package_id=package_id,
            created_at=datetime.now(UTC).isoformat(),
            task_id=task.id,
            content_hash=content_hash,
            sut_config_id="manual",
            status=status,
        )
        (package_dir / "manifest.json").write_text(
            pkg_manifest.model_dump_json(indent=2),
            encoding="utf-8",
        )

        # 写入 task.json
        (package_dir / "task.json").write_text(
            task.model_dump_json(indent=2),
            encoding="utf-8",
        )

        # 写入 metadata.json
        pkg_metadata = PackageMetadata(
            sut_name="manual",
            eval_system_version="0.1.0",
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )
        if metadata:
            for k, v in metadata.items():
                if hasattr(pkg_metadata, k):
                    setattr(pkg_metadata, k, v)
        (package_dir / "metadata.json").write_text(
            pkg_metadata.model_dump_json(indent=2),
            encoding="utf-8",
        )

        # 写入 trace.json
        now = datetime.now(UTC).isoformat()
        trace = {
            "request": {"method": "directory", "source": str(source_dir)},
            "response": {"status": "directory_package"},
            "started_at": now,
            "finished_at": now,
            "error": None,
        }
        (package_dir / "trace.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 写入 metrics.json
        metrics = {
            "total_duration_ms": 0,
            "steps": 1,
            "retries": 0,
            "tool_calls": 0,
            "dead_end": False,
            "total_files": manifest_data.total_files,
            "modules": len(manifest_data.modules),
        }
        (package_dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return package_dir

    def validate_package(self, package_dir: Path) -> list[str]:
        """校验执行包完整性。

        检查是否包含所有必要文件。

        Args:
            package_dir: 执行包目录。

        Returns:
            缺失文件列表（空列表表示校验通过）。
        """
        required_files = ["manifest.json", "task.json", "metadata.json"]
        missing: list[str] = []
        for fname in required_files:
            if not (package_dir / fname).exists():
                missing.append(fname)

        # output/ 目录应该存在（至少有一个输出文件）
        output_dir = package_dir / "output"
        if not output_dir.exists():
            missing.append("output/")
        elif not any(output_dir.iterdir()):
            missing.append("output/ (空目录)")

        return missing
