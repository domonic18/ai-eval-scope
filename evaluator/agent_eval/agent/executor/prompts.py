"""ExecutionAgent 提示词构建（arch/03 §3.3/§3.4）——模板加载与变量注入。

从 agent.py 拆出（plan/07 G4）：prompt 资产加载（YAML，损坏 fail-fast）、
system prompt（职责/工具/通用规则/通道纪律/输出规范）与 task prompt 拼装。
ExecutionAgent 仅做一行委托。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from agent_eval.config.paths import PACKAGE_ROOT
from agent_eval.core.exceptions import AgentError
from agent_eval.execution.models import Task

# 执行 Agent 提示词资产（prompt 在 YAML 中维护，不 hardcode；对齐 summary_prompt.yaml 惯例）
_PROMPTS_PATH = PACKAGE_ROOT / "assets" / "configs" / "execution_agent_prompts.yaml"


@lru_cache(maxsize=1)
def load_prompts() -> dict[str, Any]:
    """加载 execution_agent_prompts.yaml → {system_prompt, task_prompt, channel_discipline}。"""
    try:
        data = yaml.safe_load(_PROMPTS_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise AgentError(
            f"执行 Agent 提示词资产损坏: {_PROMPTS_PATH}（{e}）",
            details={"path": str(_PROMPTS_PATH)},
        ) from e
    if not isinstance(data, dict) or not data.get("system_prompt") or not data.get("task_prompt"):
        raise AgentError(
            f"执行 Agent 提示词资产结构不完整（需 system_prompt/task_prompt 两段）: {_PROMPTS_PATH}",
            details={"path": str(_PROMPTS_PATH)},
        )
    return data


def describe_all_tools(tool_servers: list[Any]) -> str:
    """汇总全部工具注册表（SUT Tools + 追加注册表）的描述清单。"""
    return "\n".join(server.describe_tools() for server in tool_servers)


def describe_channel_rules(tool_servers: list[Any]) -> str:
    """按注册表 discipline_key 拼装通道专属纪律——工具面与规则面同源（plan/07 G3）。

    语义工具注册表声明自己的纪律段（如 agent_protocol 的反问应答/线程续用/
    产物获取三步纪律），不声明或无对应段则不注入——generic_http 任务不背
    agent-protocol 规则噪声。纪律文本仍在 YAML 资产中（不 hardcode）。
    """
    segments = load_prompts().get("channel_discipline") or {}
    parts: list[str] = []
    for server in tool_servers:
        key = getattr(server, "discipline_key", None)
        segment = segments.get(key) if key else None
        if isinstance(segment, str) and segment.strip():
            parts.append(segment.strip())
    return "\n\n".join(parts)


def build_system_prompt(
    *,
    tool_servers: list[Any],
    max_turns: int,
    max_retries: int,
) -> str:
    """System Prompt：职责 + 可用工具 + 通用规则 + 通道纪律 + 输出规范。"""
    template: str = load_prompts()["system_prompt"]
    return template.format(
        tools=describe_all_tools(tool_servers),
        channel_rules=describe_channel_rules(tool_servers),
        max_turns=max_turns,
        max_retries=max_retries,
    )


def build_task_prompt(task: Task, *, workspace_dir: Path) -> str:
    """Task Prompt：任务输入/转发指令/预期/约束 + 目录模式 + 写包指令。

    forward 段提供确定性的纯文本转发内容——执行 Agent 不再依赖 LLM
    自行从 JSON 结构中提取 instruction（此前行为不一致，有时传整个 dict）。
    """
    segments: dict[str, str] = load_prompts()["task_prompt"]
    package_dir = workspace_dir / task.id
    parts = [
        segments["header"].format(task_id=task.id),
        segments["input"].format(task_input=json.dumps(task.input, ensure_ascii=False, indent=2)),
        segments["forward"].format(instruction_text=extract_instruction(task)),
    ]
    if task.expected:
        parts.append(
            segments["expected"].format(
                expected=json.dumps(task.expected, ensure_ascii=False, indent=2)
            )
        )
    if task.constraints:
        parts.append(
            segments["constraints"].format(
                constraints=json.dumps(task.constraints, ensure_ascii=False, indent=2)
            )
        )
    if task.input_mode == "directory" and task.directory_path:
        parts.append(
            segments["directory_mode"].format(
                directory_path=task.directory_path,
                file_patterns=task.file_patterns,
            )
        )
    parts.append(segments["footer"].format(package_dir=package_dir))
    return "\n\n".join(p.rstrip("\n") for p in parts)


def extract_instruction(task: Task) -> str:
    """从 task.input 提取纯文本指令（agent_run 的确定转发内容）。

    - dict 型 input：取 instruction 字段（缺失时取第一个字符串值——courseware
      包任务 input={"subject": ...} 走的即此兜底，改动需同步任务集模板）
    - str 型 input：直接返回
    """
    if isinstance(task.input, dict):
        text = task.input.get("instruction", "")
        if not text:
            # 兼容无 instruction 键的 input：取第一个非空字符串值
            for v in task.input.values():
                if isinstance(v, str) and v.strip():
                    text = v
                    break
        return str(text).strip()
    return str(task.input).strip()
