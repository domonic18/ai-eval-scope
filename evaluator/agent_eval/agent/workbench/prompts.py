"""提示词资产 — workbench_agent_prompts.yaml 单点加载与文案渲染。"""

from __future__ import annotations

import functools
from typing import Any

import yaml

from agent_eval.config.paths import PACKAGE_ROOT
from agent_eval.core.exceptions import AgentError

PROMPTS_PATH = PACKAGE_ROOT / "assets" / "configs" / "workbench_agent_prompts.yaml"

# ref 缺省时的拟定指引（Agent 按需求起名，用户可在会话中自然语言改）
REF_AGENT_CHOSEN = (
    "未指定——请根据评测需求拟定（小写英文与连字符，语义贴合需求），"
    "并在改动计划第一行明确给出「拟定引用: <scenario/id>」"
)


@functools.lru_cache(maxsize=1)
def load_prompts() -> dict[str, Any]:
    """加载 workbench_agent_prompts.yaml（缺失/损坏/结构不完整即 AgentError）。

    ``system_prompt_base``（会话机段，零域语义）/ ``domain_segments.*``（域段）/
    ``domain_labels.*``（域展示名）/ ``templates``（首轮与回改模板）/ ``intro``。
    """
    try:
        data = yaml.safe_load(PROMPTS_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise AgentError(
            f"WorkbenchAgent 提示词资产损坏: {PROMPTS_PATH}（{e}）",
            details={"path": str(PROMPTS_PATH)},
        ) from e
    required = ("system_prompt_base", "domain_segments", "templates")
    if not isinstance(data, dict) or any(not data.get(k) for k in required):
        raise AgentError(
            f"WorkbenchAgent 提示词资产结构不完整（需 {'/'.join(required)}）: {PROMPTS_PATH}",
            details={"path": str(PROMPTS_PATH)},
        )
    return data


def banner_parts(prompts: dict[str, Any], domain: str, root: str) -> dict[str, Any]:
    """横幅结构化文案（§6.8 v4.13.2）：``banner:`` 资产 + {root}/{domains} 字面 replace。

    返回 dict 供 ``cli/console/banner.py`` 富渲染（渐变 logo 与配色是表现层，不入
    资产）；资产缺 ``banner`` 段返回空 dict（渲染端据此静默跳过）。
    """
    banner = prompts.get("banner")
    if not isinstance(banner, dict) or not banner:
        return {}
    parts = dict(banner)
    parts["domains"] = str(prompts.get("domain_labels", {}).get(domain, domain))
    parts["root"] = root
    return parts


def render_first_turn(
    instruction: str, *, new_package: bool = False, ref: str | None = None
) -> str:
    """组装首轮用户消息（新建包用 generate_new_package 模板）。

    ref 给定时钉住目标引用（Agent 不得自拟）；缺省时指引 Agent 按需求拟定
    并在计划首行明确给出（用户可自然语言改）。
    """
    templates: dict[str, str] = load_prompts()["templates"]
    key = "generate_new_package" if new_package else "first_turn"
    return (
        templates[key]
        .replace("{instruction}", instruction)
        .replace("{ref}", ref if ref else REF_AGENT_CHOSEN)
    )
