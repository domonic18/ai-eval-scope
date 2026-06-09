"""项目路径集中管理。

所有资源路径的唯一来源。生产代码统一通过 ``from agent_eval.config.paths import paths``
获取路径，避免在各个模块中用 ``Path(__file__).parent.*`` 拼接。
"""

from __future__ import annotations

from pathlib import Path

# 项目根目录 — 唯一的 Path(__file__) 计算
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class ProjectPaths:
    """项目路径配置。

    使用示例::

        from agent_eval.config.paths import paths

        schema = paths.schemas_dir / "rule_set_schema.json"
        prompt = paths.prompts_dir / "logical_consistency.yaml"

    Args:
        root: 项目根目录（可选，默认自动检测）。
            测试时可注入 ``tmp_path`` 以隔离文件系统。
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or PROJECT_ROOT

    @property
    def root(self) -> Path:
        """项目根目录。"""
        return self._root

    # ── assets/ ──

    @property
    def assets_dir(self) -> Path:
        """``assets/`` 目录。"""
        return self._root / "assets"

    @property
    def schemas_dir(self) -> Path:
        """``assets/schemas/`` — JSON Schema 文件。"""
        return self.assets_dir / "schemas"

    @property
    def prompts_dir(self) -> Path:
        """``assets/prompts/`` — LLM Judge Prompt 模板。"""
        return self.assets_dir / "prompts"

    @property
    def rules_dir(self) -> Path:
        """``assets/rules/`` — 默认规则集。"""
        return self.assets_dir / "rules"

    @property
    def configs_dir(self) -> Path:
        """``assets/configs/`` — 配置文件样例。"""
        return self.assets_dir / "configs"

    # ── workspace/ ──

    @property
    def default_workspace(self) -> Path:
        """默认 workspace 目录（``<root>/workspace``）。"""
        return self._root / "workspace"


# 全局单例 — 所有模块导入此对象
paths = ProjectPaths()
