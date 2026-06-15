"""数据包模型 — ExecutionPackage 与 EvaluationResult。

定义执行包（ExecutionPackage）和评估结果包（EvaluationResult）的完整结构，
包括目录布局、manifest 文件格式、读写方法。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agent_eval.core.types import PackageStatus

# ─── ExecutionPackage 相关模型 ───


class PackageManifest(BaseModel):
    """执行包 manifest.json。"""

    package_id: str = Field(description="执行包唯一标识")
    created_at: str = Field(description="创建时间（ISO 8601）")
    task_id: str = Field(description="任务 ID")
    sut_config_id: str = Field(default="manual", description="SUT 配置标识")
    status: PackageStatus = Field(default=PackageStatus.SUCCESS, description="执行状态")

    model_config = {"use_enum_values": True}


class PackageMetadata(BaseModel):
    """执行包 metadata.json — SUT 与环境元信息。"""

    sut_name: str = Field(default="manual", description="SUT 名称")
    sut_version: str = Field(default="", description="SUT 版本")
    sut_endpoint: str = Field(default="", description="SUT 端点")
    eval_system_version: str = Field(default="0.1.0", description="评估系统版本")
    python_version: str = Field(default="", description="Python 版本")


class DirectoryManifestFile(BaseModel):
    """目录清单中的单个文件信息。"""

    name: str = Field(description="文件名")
    path: str = Field(description="相对路径")
    depth: int = Field(description="目录深度")
    size: int = Field(default=0, description="文件大小（字节）")


class DirectoryManifestModule(BaseModel):
    """目录清单中的模块信息。"""

    name: str = Field(description="模块名")
    path: str = Field(description="模块相对路径")
    file_count: int = Field(description="文件数量")
    children: list[DirectoryManifestFile] = Field(
        default_factory=list,
        description="模块下文件列表",
    )


class DirectoryManifest(BaseModel):
    """目录清单 — output/_manifest.json。"""

    mode: str = Field(default="directory", description='固定为 "directory"')
    root_dir: str = Field(description="输出文件根目录（相对路径）")
    total_files: int = Field(description="文件总数")
    file_types: dict[str, int] = Field(
        default_factory=dict,
        description="按扩展名统计",
    )
    hierarchy_depth: int = Field(default=0, description="最大目录深度")
    modules: list[DirectoryManifestModule] = Field(
        default_factory=list,
        description="顶层模块列表",
    )


class ExecutionPackage(BaseModel):
    """执行包 — 一个任务执行后产出的完整数据包。

    对应目录结构:
        packages/{task_id}/
        ├── manifest.json
        ├── task.json
        ├── output/
        │   ├── _manifest.json  (目录模式时)
        │   └── ...
        ├── trace.json
        ├── metrics.json
        └── metadata.json
    """

    manifest: PackageManifest
    task_data: dict[str, Any] = Field(
        default_factory=dict,
        description="原始任务定义（task.json 内容）",
    )
    output_dir: Path | None = Field(
        default=None,
        description="output/ 目录路径",
    )
    trace: dict[str, Any] | None = Field(
        default=None,
        description="执行轨迹（trace.json 内容）",
    )
    metrics: dict[str, Any] | None = Field(
        default=None,
        description="过程指标（metrics.json 内容）",
    )
    metadata: PackageMetadata = Field(
        default_factory=PackageMetadata,
        description="SUT 与环境元信息",
    )
    directory_manifest: DirectoryManifest | None = Field(
        default=None,
        description="目录清单（仅目录模式）",
    )

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def load(cls, package_dir: Path) -> ExecutionPackage:
        """从目录加载 ExecutionPackage。"""
        if not package_dir.exists():
            from agent_eval.core.exceptions import PackageNotFoundError

            raise PackageNotFoundError(str(package_dir))

        manifest = PackageManifest.model_validate_json(
            (package_dir / "manifest.json").read_text(encoding="utf-8"),
        )

        task_data: dict[str, Any] = {}
        task_file = package_dir / "task.json"
        if task_file.exists():
            task_data = json.loads(task_file.read_text(encoding="utf-8"))

        trace: dict[str, Any] | None = None
        trace_file = package_dir / "trace.json"
        if trace_file.exists():
            trace = json.loads(trace_file.read_text(encoding="utf-8"))

        metrics: dict[str, Any] | None = None
        metrics_file = package_dir / "metrics.json"
        if metrics_file.exists():
            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))

        metadata = PackageMetadata()
        metadata_file = package_dir / "metadata.json"
        if metadata_file.exists():
            metadata = PackageMetadata.model_validate_json(
                metadata_file.read_text(encoding="utf-8"),
            )

        output_dir = package_dir / "output" if (package_dir / "output").exists() else None

        dir_manifest: DirectoryManifest | None = None
        dir_manifest_file = package_dir / "output" / "_manifest.json"
        if dir_manifest_file.exists():
            dir_manifest = DirectoryManifest.model_validate_json(
                dir_manifest_file.read_text(encoding="utf-8"),
            )

        return cls(
            manifest=manifest,
            task_data=task_data,
            output_dir=output_dir,
            trace=trace,
            metrics=metrics,
            metadata=metadata,
            directory_manifest=dir_manifest,
        )

    def save(self, package_dir: Path) -> Path:
        """将 ExecutionPackage 写入指定目录。"""
        package_dir.mkdir(parents=True, exist_ok=True)

        (package_dir / "manifest.json").write_text(
            self.manifest.model_dump_json(indent=2),
            encoding="utf-8",
        )
        (package_dir / "task.json").write_text(
            json.dumps(self.task_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (package_dir / "metadata.json").write_text(
            self.metadata.model_dump_json(indent=2),
            encoding="utf-8",
        )

        if self.trace is not None:
            (package_dir / "trace.json").write_text(
                json.dumps(self.trace, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if self.metrics is not None:
            (package_dir / "metrics.json").write_text(
                json.dumps(self.metrics, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return package_dir


# ─── EvaluationResult 相关模型 ───


class EvalResultManifest(BaseModel):
    """评估结果 manifest.json。"""

    result_id: str = Field(description="评估结果唯一标识")
    package_id: str = Field(description="关联的执行包 ID")
    rule_set_version: str = Field(description="规则集版本")
    evaluated_at: str = Field(description="评估时间（ISO 8601）")


class ScoreSummary(BaseModel):
    """评分汇总 — scores.json。"""

    s_format: float = Field(default=0.0)
    s_common: float = Field(default=0.0)
    s_soft: float = Field(default=0.0)
    s_pref: float = Field(default=0.0)
    reward: float = Field(default=0.0)
    dimensions: dict[str, float] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    """评估结果包 — 一个任务评估后的完整结果。

    对应目录结构:
        results/{task_id}/
        ├── manifest.json
        ├── rule_results.json
        ├── scores.json
        ├── evidence/
        ├── report.md
        └── report.json
    """

    manifest: EvalResultManifest
    rule_results: list[dict[str, Any]] = Field(default_factory=list)
    scores: ScoreSummary = Field(default_factory=ScoreSummary)
    report_markdown: str = Field(default="")
    report_json: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def load(cls, result_dir: Path) -> EvaluationResult:
        """从目录加载 EvaluationResult。"""
        manifest = EvalResultManifest.model_validate_json(
            (result_dir / "manifest.json").read_text(encoding="utf-8"),
        )

        rule_results: list[dict[str, Any]] = []
        rr_file = result_dir / "rule_results.json"
        if rr_file.exists():
            rule_results = json.loads(rr_file.read_text(encoding="utf-8"))

        scores = ScoreSummary()
        scores_file = result_dir / "scores.json"
        if scores_file.exists():
            scores = ScoreSummary.model_validate_json(
                scores_file.read_text(encoding="utf-8"),
            )

        report_markdown = ""
        md_file = result_dir / "report.md"
        if md_file.exists():
            report_markdown = md_file.read_text(encoding="utf-8")

        report_json: dict[str, Any] = {}
        rj_file = result_dir / "report.json"
        if rj_file.exists():
            report_json = json.loads(rj_file.read_text(encoding="utf-8"))

        return cls(
            manifest=manifest,
            rule_results=rule_results,
            scores=scores,
            report_markdown=report_markdown,
            report_json=report_json,
        )

    def save(self, result_dir: Path) -> Path:
        """将 EvaluationResult 写入指定目录。"""
        result_dir.mkdir(parents=True, exist_ok=True)

        (result_dir / "manifest.json").write_text(
            self.manifest.model_dump_json(indent=2),
            encoding="utf-8",
        )
        (result_dir / "rule_results.json").write_text(
            json.dumps(self.rule_results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (result_dir / "scores.json").write_text(
            self.scores.model_dump_json(indent=2),
            encoding="utf-8",
        )
        if self.report_markdown:
            (result_dir / "report.md").write_text(self.report_markdown, encoding="utf-8")
        if self.report_json:
            (result_dir / "report.json").write_text(
                json.dumps(self.report_json, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        (result_dir / "evidence").mkdir(exist_ok=True)

        return result_dir


def generate_run_id() -> str:
    """生成运行 ID（时间戳格式）。"""
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def generate_package_id(run_id: str, task_id: str) -> str:
    """生成执行包 ID。"""
    return f"pkg_{run_id}_{task_id}"


def generate_result_id(run_id: str, task_id: str) -> str:
    """生成评估结果 ID。"""
    return f"eval_{run_id}_{task_id}"
