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


# 模板语法纠偏共享文案（Jinja2 渲染请求体的工具通用）：实测曾出现 shell 风格
# ${var} 占位符原样发出，或模板引用未提供的变量名（如工具参数名）致渲染异常
TEMPLATE_SYNTAX_HINT = (
    "模板语法为 Jinja2：变量写 {{ 字段名 }} 且必须来自本次提供的变量集合；"
    '常量字段直接写字面值（如 "platform": "fs"）；${var}、%s 等 shell/字符串模板'
    "风格不会被渲染，会原样发出"
)


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
        """包装工具方法：结果 JSON 序列化为字符串（dict/list 统一文本化）。

        导出层异常兜底（tool_guard 精神，实测教训）：未捕获的工具异常会沿
        LangGraph 击穿整个 Agent 会话（运行 1 渲染 TypeError、运行 2 文件读取
        失败均以「会话异常中断」收场）——一律转为 failed 结果交 Agent 决策
        （重试/降级/写错误包），方法级直接调用行为不变（仍抛异常，供测试与
        服务端组合使用）。
        """

        @functools.wraps(method)
        async def run(*args: Any, **kwargs: Any) -> str:
            try:
                result = await method(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 — 工具异常转 failed 结果，不中断图
                return json.dumps(
                    {
                        "status": "failed",
                        "error": {
                            "type": type(e).__name__,
                            "message": truncate(str(e), 2000),
                        },
                    },
                    ensure_ascii=False,
                    default=str,
                )
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
