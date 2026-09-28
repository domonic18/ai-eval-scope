"""LLM 角色注册表 — 能力轴单源（role × protocol × model 三轴分离）。

三轴语义：
- **role（能力轴）**：这条线干什么。``kind`` 是行为派发键——chat 线路进
  ProviderPool / 客户端工厂；decision 线路由判定专线构造器（DecisionClient）
  直接消费，不进 chat 池。
- **protocol（协议轴）**：怎么调（anthropic/openai/noul），见 ``llm_file.PROTOCOLS``。
- **model（模型轴）**：选谁——纯配置字段，换同协议模型零代码。

所有需要区分「chat 与非 chat 角色」的分支一律按本注册表的 kind 派发，
禁止对具体角色名字符串做相等判断。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleSpec:
    """单个 LLM 角色的注册项。"""

    name: str  # providers 键 / llm.json roles 键 / 平台 llm_models.role
    kind: str  # 行为派发键: "chat" | "decision"
    label: str  # 中文说明（向导/错误信息）


ROLE_SPECS: tuple[RoleSpec, ...] = (
    RoleSpec("text", "chat", "LLM Judge 文本（default）"),
    RoleSpec("vision", "chat", "视觉评估"),
    RoleSpec("agent", "chat", "执行侧 Agent（缺省回退 text）"),
    RoleSpec("decision", "decision", "判定专线（Noul 是/否概率原语，非 chat）"),
)

#: 全部合法角色名（providers 键全集；顺序即向导/文档展示顺序）
ROLES = tuple(s.name for s in ROLE_SPECS)

#: 角色 → 行为派发键
ROLE_KINDS: dict[str, str] = {s.name: s.kind for s in ROLE_SPECS}

#: chat 线路角色（进 ProviderPool / 客户端工厂 / 默认回退链）
CHAT_ROLES = tuple(s.name for s in ROLE_SPECS if s.kind == "chat")

#: 判定专线角色（DecisionClient 专线消费；不回退、不作 default、不进 chat 池）
DECISION_ROLE = "decision"


def is_chat_role(name: str) -> bool:
    """角色是否为 chat 线路（未注册角色按非 chat 处理，保守不进池）。"""
    return ROLE_KINDS.get(name) == "chat"


__all__ = [
    "CHAT_ROLES",
    "DECISION_ROLE",
    "ROLES",
    "ROLE_KINDS",
    "ROLE_SPECS",
    "RoleSpec",
    "is_chat_role",
]
