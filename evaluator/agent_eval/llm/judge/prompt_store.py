"""Prompt 模板存储抽象（arch/05 v2.1 + arch/13 §8.2）。

PromptStore 把 TemplateManager 的「单一目录加载」升级为多源抽象：
- FilePromptStore：场景包 prompts/ 目录（Phase 1）
- DbPromptStore：Web DB 经公开端点（Phase 2）
- SnapshotPromptStore：RunConfigSnapshot 回放（Phase 3）

scenario_id 实现为 Optional 以兼容旧式无场景 YAML（偏离 arch/13 草图的 str 必填）。
render 为 ABC 具体方法（三实现共用 Jinja2，无状态）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import jinja2

from agent_eval.core.exceptions import LLMError
from agent_eval.llm.judge.template_manager import JudgeTemplate


@dataclass
class PromptTemplateSummary:
    """list() 返回的轻量摘要（不含 system/user prompt 全文）。"""

    template_id: str
    name: str
    namespace: str | None = None
    scenario_id: str | None = None
    version: str | None = None
    labels: list[str] = field(default_factory=list)
    content_hash: str | None = None


class PromptStore(ABC):
    """Prompt 模板存储抽象（arch/13 §8.2）。

    scenario_id 传 None 时不按场景过滤（兼容旧式无场景 YAML 与单参直访点）。
    """

    _JINJA = jinja2.Environment(undefined=jinja2.StrictUndefined)

    @abstractmethod
    def get(
        self,
        scenario_id: str | None,
        template_id: str,
        version: str | None = None,
        label: str | None = None,
    ) -> JudgeTemplate: ...

    @abstractmethod
    def list(self, scenario_id: str | None = None) -> list[PromptTemplateSummary]: ...

    def render(self, template: JudgeTemplate, variables: dict[str, Any]) -> tuple[str, str]:
        """渲染模板，返回 (system_prompt, user_prompt)。

        三实现共用：纯 Jinja2 渲染 user_prompt_template，system_prompt 原样返回。
        """
        try:
            user_prompt = self._JINJA.from_string(template.user_prompt_template).render(**variables)
        except jinja2.UndefinedError as e:
            raise LLMError(
                f"模板渲染失败，变量缺失: {e}",
                details={"template_id": template.template_id},
            ) from e
        return template.system_prompt, user_prompt
