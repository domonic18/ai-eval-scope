"""规则集注册表 — 规则集作为一等资源。

替代 runner 里硬编码的 2 分支 `_rule_set_path`：内置规则集经注册表查找，
未来扩展项目上传规则集（P1）。目录端点 `GET /v1/rule-sets` 据此返回可选规则集
及其派生能力（由评估器 CapabilityResolver 计算），让调用方提交前即知是否需 LLM/视觉。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent_eval.config.paths import paths as agent_eval_paths

from eval_gateway.core.logging import get_logger

_LOG = get_logger(__name__)

# gateway 自带规则集目录（纯格式冒烟用）
_GATEWAY_ASSETS = Path(__file__).resolve().parent.parent / "assets" / "rules"


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
        description="门控 + 质量评估 + 多模态视觉质量（gateway 需预装 Chromium）",
        path=agent_eval_paths.rules_dir / "coursework-vision.yaml",
    ),
    RuleSetInfo(
        id="format-only",
        name="纯格式规则集",
        description="仅格式校验，无 LLM 依赖（gateway 冒烟 / CI 用）",
        path=_GATEWAY_ASSETS / "format_only.yaml",
    ),
)


def list_rule_sets() -> list[RuleSetInfo]:
    """所有可用规则集（内置；P1 扩展项目上传）。"""
    return list(_BUILTIN)


def get_path(rule_set_id: str) -> Path | None:
    """规则集 id → 文件路径；未知 id 返回 None（由调用方决定回退或报错）。"""
    for rs in _BUILTIN:
        if rs.id == rule_set_id:
            return rs.path
    return None


def _derive_capabilities(path: Path) -> list[str]:
    """加载规则集 → CapabilityResolver 派生所需能力（失败返回空，不阻断目录）。"""
    try:
        import agent_eval.evaluation.evaluators  # noqa: F401  触发注册
        from agent_eval.config.loader import ConfigLoader
        from agent_eval.evaluation.capability import CapabilityResolver
        from agent_eval.evaluation.registry import registry as eval_registry

        rule_set = ConfigLoader.load_rule_set(path)
        required = CapabilityResolver(eval_registry).resolve(rule_set)
        return sorted(c.value for c in required.capabilities)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("rule_set.capabilities_derive_failed", path=str(path), error=str(exc))
        return []


@lru_cache(maxsize=16)  # 同规则集（按路径）能力不变，缓存
def _capabilities_cached(path_str: str) -> list[str]:
    return _derive_capabilities(Path(path_str))


def catalog() -> list[dict[str, Any]]:
    """目录视图：[{id, name, description, capabilities, scopes}]（HTTP GET 用）。"""
    items: list[dict[str, Any]] = []
    for rs in _BUILTIN:
        items.append(
            {
                "id": rs.id,
                "name": rs.name,
                "description": rs.description,
                "capabilities": _capabilities_cached(str(rs.path)),
                "scopes": list(rs.scopes),
            }
        )
    return items
