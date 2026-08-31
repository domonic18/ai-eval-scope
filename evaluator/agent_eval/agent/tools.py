"""Agent 工具服务器公共基座 — 工具规格与 LangChain 导出（v4.6）。

SUTToolServer / AgentProtocolToolServer 共用：工具实现为普通异步方法
（可直接调用与测试，零框架依赖），经 ToolExporterMixin 惰性导出为
LangChain Tool 显式绑定给 DeepAgents。
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from typing import Any, ClassVar

from agent_eval.core.exceptions import AgentError


@dataclass(frozen=True)
class ToolSpec:
    """单个工具的注册信息（名称/描述/方法名）。"""

    name: str
    description: str
    method: str


def truncate(text: str, max_chars: int) -> str:
    """超长文本截断（尾部追加标记）。"""
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...（已截断，共 {len(text)} 字符）"


class ToolExporterMixin:
    """LangChain Tool 导出基座：子类提供 TOOL_SPECS 与同名异步方法。

    to_langchain_tools() 惰性加载 langchain_core（[agent] extra），
    functools.wraps 保留原方法签名供 StructuredTool 推导参数 Schema。
    """

    TOOL_SPECS: ClassVar[list[ToolSpec]] = []

    def to_langchain_tools(self) -> list[Any]:
        """导出 LangChain Tool 列表供 DeepAgents 显式绑定。"""
        try:
            from langchain_core.tools import StructuredTool
        except ImportError:
            raise AgentError(
                "导出 LangChain Tool 需要 langchain-core。请执行: pip install 'agent-eval[agent]'",
                details={"missing_module": "langchain_core"},
            ) from None
        return [
            StructuredTool.from_function(
                coroutine=self._json_tool(getattr(self, spec.method)),
                name=spec.name,
                description=spec.description,
            )
            for spec in self.TOOL_SPECS
        ]

    def _json_tool(self, method: Any) -> Any:
        """包装工具方法：结果 JSON 序列化为字符串（dict/list 统一文本化）。"""

        @functools.wraps(method)
        async def run(*args: Any, **kwargs: Any) -> str:
            result = await method(*args, **kwargs)
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, default=str)

        return run

    def get_tool_names(self) -> list[str]:
        """返回所有注册的工具名称。"""
        return [spec.name for spec in self.TOOL_SPECS]

    def describe_tools(self) -> str:
        """返回工具描述清单，用于构建 System Prompt。"""
        lines = []
        for spec in self.TOOL_SPECS:
            method = getattr(self, spec.method)
            params = ", ".join(
                f"{name}: {getattr(annot, '__name__', str(annot))}"
                for name, annot in getattr(method, "__annotations__", {}).items()
                if name != "return"
            )
            lines.append(f"- {spec.name}({params}): {spec.description}")
        return "\n".join(lines)
