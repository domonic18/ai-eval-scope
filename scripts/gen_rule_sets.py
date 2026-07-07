"""构建期生成 rule-sets 静态 catalog（Web 托管）。

在 evaluator 环境运行::

    cd evaluator && uv run python ../scripts/gen_rule_sets.py

调用评估器 CapabilityResolver 派生每个内置规则集的所需能力（LLM/视觉），
产出 ``web/backend/assets/rule-sets.json`` 并提交入库。Web 的 /api/v1/rule-sets
直接 import 该 JSON（docs/arch/09 §7.7），无需运行时 Python。

内置规则集目录与 ``executor/eval_executor/rules/registry.py`` 的 _BUILTIN 保持一致；
改规则集后须重跑本脚本，避免 catalog 漂移（建议挂 pre-commit / CI）。
"""

from __future__ import annotations

import json
from pathlib import Path

import agent_eval.evaluation.evaluators  # noqa: F401  触发评估器注册
from agent_eval.config.loader import ConfigLoader
from agent_eval.config.paths import paths as agent_eval_paths
from agent_eval.evaluation.capability import CapabilityResolver
from agent_eval.evaluation.registry import registry as eval_registry

_ROOT = Path(__file__).resolve().parent.parent

# 与 executor/eval_executor/rules/registry.py 的 _BUILTIN 对齐
_BUILTIN = [
    {
        "id": "coursework-gate",
        "name": "课件基础（门控）",
        "description": "格式门控 + 常识门控（LLM 二次确认），不含质量/视觉评估",
        "path": agent_eval_paths.rules_dir / "coursework-gate.yaml",
        "scopes": ["single", "unit"],
    },
    {
        "id": "coursework-quality",
        "name": "课件质量评估",
        "description": "门控 + 软约束/偏好质量评估（LLM Judge），不含视觉",
        "path": agent_eval_paths.rules_dir / "coursework-quality.yaml",
        "scopes": ["single", "unit"],
    },
    {
        "id": "coursework-vision",
        "name": "课件完整评估（含视觉）",
        "description": "门控 + 质量评估 + 多模态视觉质量（executor 需预装 Chromium）",
        "path": agent_eval_paths.rules_dir / "coursework-vision.yaml",
        "scopes": ["single", "unit"],
    },
    {
        "id": "format-only",
        "name": "纯格式规则集",
        "description": "仅格式校验，无 LLM 依赖（冒烟 / CI 用）",
        "path": _ROOT / "executor" / "eval_executor" / "assets" / "rules" / "format_only.yaml",
        "scopes": ["single"],
    },
]


def _derive_capabilities(path: Path) -> list[str]:
    try:
        rs = ConfigLoader.load_rule_set(str(path))
        required = CapabilityResolver(eval_registry).resolve(rs)
        return sorted(c.value for c in required.capabilities)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: derive capabilities failed for {path}: {exc}")
        return []


def main() -> None:
    items = [
        {
            "id": rs["id"],
            "name": rs["name"],
            "description": rs["description"],
            "capabilities": _derive_capabilities(rs["path"]),
            "scopes": rs["scopes"],
        }
        for rs in _BUILTIN
    ]
    out = _ROOT / "web" / "backend" / "assets" / "rule-sets.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated {out} ({len(items)} rule sets)")


if __name__ == "__main__":
    main()
