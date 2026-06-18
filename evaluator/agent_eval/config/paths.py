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
    def prompts_dir(self) -> Path:
        """``assets/prompts/`` — LLM Judge Prompt 模板。"""
        return self.assets_dir / "prompts"

    @property
    def rules_dir(self) -> Path:
        """``assets/rules/`` — 默认规则集。"""
        return self.assets_dir / "rules"

    @property
    def configs_dir(self) -> Path:
        """``assets/configs/`` — 配置文件（llm_config 等）。"""
        return self.assets_dir / "configs"

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
