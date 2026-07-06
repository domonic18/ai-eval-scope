"""规则集注册表 -- 规则集作为一等资源（executor 内部用，不再对外暴露 HTTP）。

内置规则集经注册表查找路径；目录端点已迁至 Web（构建期静态 rule-sets.json）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_eval.config.paths import paths as agent_eval_paths

from eval_executor.core.logging import get_logger

_LOG = get_logger(__name__)

# executor 自带规则集目录（纯格式冒烟用）
_EXECUTOR_ASSETS = Path(__file__).resolve().parent.parent / "assets" / "rules"


@dataclass(frozen=True)
class RuleSetInfo:
    """内置规则集描述。"""

    id: str
    name: str
    description: str
    path: Path
    scopes: tuple[str, ...] = ("single", "unit")


_BUILTIN: tuple[RuleSetInfo, ...] = (
    RuleSetInfo(
        id="coursework-gate",
        name="课件基础（门控）",
        description="格式门控 + 常识门控（LLM 二次确认），不含质量/视觉评估",
        path=agent_eval_paths.rules_dir / "coursework-gate.yaml",
    ),
    RuleSetInfo(
        id="coursework-quality",
        name="课件质量评估",
        description="门控 + 软约束/偏好质量评估（LLM Judge），不含视觉",
        path=agent_eval_paths.rules_dir / "coursework-quality.yaml",
    ),
    RuleSetInfo(
        id="coursework-vision",
        name="课件完整评估（含视觉）",
        description="门控 + 质量评估 + 多模态视觉质量（executor 需预装 Chromium）",
        path=agent_eval_paths.rules_dir / "coursework-vision.yaml",
    ),
    RuleSetInfo(
        id="format-only",
        name="纯格式规则集",
        description="仅格式校验，无 LLM 依赖（冒烟 / CI 用）",
        path=_EXECUTOR_ASSETS / "format_only.yaml",
    ),
)


def list_rule_sets() -> list[RuleSetInfo]:
    """所有可用规则集（内置）。"""
    return list(_BUILTIN)


def get_path(rule_set_id: str) -> Path | None:
    """规则集 id → 文件路径；未知 id 返回 None（由调用方决定回退或报错）。"""
    for rs in _BUILTIN:
        if rs.id == rule_set_id:
            return rs.path
    return None
