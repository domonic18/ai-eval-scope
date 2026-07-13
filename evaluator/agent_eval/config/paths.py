"""路径集中管理 — pip-installable 设计。

设计原则（支持 ``pip install agent-eval`` 后开箱即用）：
  - **包内资源**（prompts/schemas/rules/configs）随包发布，经 ``PACKAGE_ROOT`` 定位，
    无论是 editable install 还是 site-packages 都正确。
  - **工作目录**（workspace: runs/reports/cache/queue）是用户数据，不随包发布。
    通过 ``WORKSPACE_DIR`` 环境变量配置，缺省 ``./workspace``（相对 CWD）。

生产代码统一通过 ``from agent_eval.config.paths import paths`` 获取路径。
"""

from __future__ import annotations

import os
from pathlib import Path

# 包根目录（agent_eval/）— 随包发布的资源在此层。
# Path(__file__) 在 editable install 和 site-packages 中都能正确定位。
PACKAGE_ROOT = Path(__file__).resolve().parent.parent  # = agent_eval/


def _semver_tuple(version: str) -> tuple[int, ...]:
    """把 ``"1.2.3"`` 解析为可比较的整数元组，供内置包版本目录排序。"""
    parts: list[int] = []
    for chunk in version.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


class ProjectPaths:
    """路径配置（pip-installable）。

    使用示例::

        from agent_eval.config.paths import paths
        schema = paths.schemas_dir / "rule_set_schema.json"
        prompt = paths.prompts_dir / "logical_consistency.yaml"
        ws = paths.default_workspace  # 用户可经 WORKSPACE_DIR 环境变量覆盖

    Args:
        root: 资源根目录（可选，默认 ``PACKAGE_ROOT`` = agent_eval/）。
            测试时可注入 ``tmp_path`` 以隔离文件系统。
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or PACKAGE_ROOT

    @property
    def root(self) -> Path:
        """资源根目录。"""
        return self._root

    # ── 包内资源（随包发布）──

    @property
    def assets_dir(self) -> Path:
        """``assets/`` 目录（随包发布）。"""
        return self._root / "assets"

    @property
    def schemas_dir(self) -> Path:
        """``assets/schemas/`` — JSON Schema 文件。"""
        return self.assets_dir / "schemas"

    @property
    def configs_dir(self) -> Path:
        """``assets/configs/`` — 配置文件（llm_config 等）。"""
        return self.assets_dir / "configs"

    # ── 内置场景包（Scenario Package，Phase 2 重组）──
    # 原 assets/{rules,prompts,knowledge}/ 已归入 assets/packages/courseware/<version>/
    # rules/prompts/datasets 访问器透出到内置 courseware 包，旧调用点无需改动。

    @property
    def packages_dir(self) -> Path:
        """``assets/packages/`` — 内置场景包根。"""
        return self.assets_dir / "packages"

    def builtin_package_root(self, scenario: str = "courseware") -> Path:
        """内置场景包根目录（取该场景下最高版本目录）。"""
        base = self.packages_dir / scenario
        if not base.is_dir():
            return base / "1.0.0"  # 不存在时返回约定路径，调用方自然报错
        versions = sorted(
            (d for d in base.iterdir() if d.is_dir()),
            key=lambda d: _semver_tuple(d.name),
        )
        return versions[-1] if versions else base / "1.0.0"

    @property
    def rules_dir(self) -> Path:
        """内置 courseware 包的规则目录（``packages/courseware/<ver>/rules``）。"""
        return self.builtin_package_root() / "rules"

    @property
    def prompts_dir(self) -> Path:
        """内置 courseware 包的提示词目录（``packages/courseware/<ver>/prompts``）。"""
        return self.builtin_package_root() / "prompts"

    @property
    def knowledge_dir(self) -> Path:
        """参考知识目录（原 ``assets/knowledge/``，现归入 courseware 包 ``datasets/``）。"""
        return self.builtin_package_root() / "datasets"

    # ── 工作目录（用户数据，不随包发布）──

    @property
    def default_workspace(self) -> Path:
        """默认 workspace 目录。

        优先级：
          1. ``WORKSPACE_DIR`` 环境变量（绝对或相对 CWD）
          2. ``CWD / workspace``（用户运行 ``agent-eval`` 的当前目录下）
        """
        ws = os.environ.get("WORKSPACE_DIR") or os.environ.get("AGENT_EVAL_WORKSPACE")
        if ws:
            return Path(ws).resolve()
        return Path.cwd() / "workspace"


# 全局单例
paths = ProjectPaths()
