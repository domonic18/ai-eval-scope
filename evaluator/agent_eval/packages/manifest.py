"""场景包清单（manifest）与解析结果模型。

对齐 13 配置管理设计 §四。一个 ScenarioPackage 由 ``agent_eval.yaml`` 清单描述，
清单所在目录即包根，其下按约定存放 rules/ prompts/ datasets/ 等资源目录。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from agent_eval.core.exceptions import ScenarioPackageValidationError

MANIFEST_FILENAME = "agent_eval.yaml"


class PackageManifest(BaseModel):
    """``agent_eval.yaml`` 的 ``package:`` 段。"""

    id: str = Field(description="包 ID，如 courseware / travel-itinerary-quality")
    scenario: str = Field(description="所属场景 ID，如 courseware")
    version: str = Field(default="1.0.0", description="语义版本号")
    name: str = Field(default="", description="包展示名")
    description: str = Field(default="", description="包描述")
    author: str = Field(default="", description="作者/团队")
    labels: list[str] = Field(
        default_factory=list, description="可变标签：latest/production/staging"
    )
    entry_points: dict[str, str] = Field(
        default_factory=dict, description="插件入口：{evaluators/readers/datasets: 'module:func'}"
    )
    dependencies: list[str] = Field(default_factory=list, description="依赖的其它包")
    artifact_types: list[str] = Field(default_factory=list, description="制品类型声明")
    default_rule_set: str | None = Field(
        default=None,
        description="默认规则集 id（job 未指定 rule_set_id 时采用，如 coursework-vision）",
    )
    default_task_set: str | None = Field(
        default=None,
        description="默认任务集名（task_sets/ 下的文件 stem，如 default；arch/16 §2.1）",
    )
    default_sut: str | None = Field(
        default=None,
        description="默认被测系统名（sut_configs/ 下文件的 sut.name；唯一系统可省略）",
    )

    model_config = {"extra": "allow"}

    @property
    def ref(self) -> str:
        """``scenario/package:version`` 引用串。"""
        return f"{self.scenario}/{self.id}:{self.version}"


@dataclass
class ResolvedPackage:
    """已定位到磁盘的场景包。

    ``root`` 为包根目录（含 agent_eval.yaml）；资源目录由 manifest 的约定字段派生。
    """

    manifest: PackageManifest
    root: Path
    source: str = "builtin"  # builtin | local | remote-cache

    @property
    def rules_dir(self) -> Path:
        return self.root / "rules"

    @property
    def prompts_dir(self) -> Path:
        return self.root / "prompts"

    @property
    def datasets_dir(self) -> Path:
        """参考知识/测试数据目录（原 knowledge 归于此，role=reference）。"""
        return self.root / "datasets"

    @property
    def metrics_dir(self) -> Path:
        return self.root / "metrics"

    @property
    def task_sets_dir(self) -> Path:
        """包内任务集目录（考卷，arch/16 §2.1）。"""
        return self.root / "task_sets"

    @property
    def sut_configs_dir(self) -> Path:
        """包内 SUT 接入配置目录（不含凭证，arch/16 §2.1；eval_only 型场景无此目录）。"""
        return self.root / "sut_configs"

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_FILENAME


def load_manifest(root: Path) -> PackageManifest:
    """从包根目录加载并校验 ``agent_eval.yaml``。"""
    path = root / MANIFEST_FILENAME
    if not path.exists():
        raise ScenarioPackageValidationError(
            f"缺少清单文件 {MANIFEST_FILENAME}", details={"root": str(root)}
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ScenarioPackageValidationError(
            f"清单 YAML 解析失败: {e}", details={"path": str(path)}
        ) from e
    pkg = data.get("package") if isinstance(data, dict) else None
    if not isinstance(pkg, dict):
        raise ScenarioPackageValidationError("清单缺少 'package:' 段", details={"path": str(path)})
    try:
        return PackageManifest.model_validate(pkg)
    except Exception as e:
        raise ScenarioPackageValidationError(
            f"清单字段非法: {e}", details={"path": str(path)}
        ) from e
