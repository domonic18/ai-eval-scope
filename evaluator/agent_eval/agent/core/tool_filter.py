"""模型可见工具面复位中间件（workbench / executor 双域共享）。

deepagents 的 ``create_deep_agent(tools=...)`` 为 **additive 合并、不移除内置**
——内置 ls/glob/read_file 等跑在 StateBackend 虚拟文件系统上（非真实磁盘）：
工作台 Agent 曾因空 ls/glob 误判「没有场景包」（2026-09 实测连续空转后放弃）；
ExecutionAgent 的任务最后两轮烧在内置 ls 上（真实 workspace 路径返回
"No files found"，run 20260911_010507），且内置 read_file 与自研白名单
read_file 同名并存，胜者取决于框架合并顺序。

不能用 harness profile 移除内置：注册表进程级全局、按模型键 additive 合且
不可注销——``agent-eval start`` 长驻进程内同键会波及其他域的 Agent，且按名
排除会连同名同姓的自家沙盒工具（read_file/write_file）一并剥掉。
故用 per-call 中间件做**允许清单复位**：模型可见的工具面 = 宿主装配清单，
其余（含未来版本新增的内置名与 task 子代理入口）一律剥除，对上游演进免疫。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from agent_eval.core.exceptions import AgentEvalError


def filter_visible_tools(
    request_tools: Sequence[Any] | None, allowed_tools: Sequence[Any]
) -> list[Any]:
    """按对象身份保留允许集；全部失配时原样返回（保守降级，不清空工具面）。

    身份（id）匹配而非按名：与自家沙盒 read_file/write_file 同名的内置工具
    必须剥除，按名会误伤。全部失配 = 上游契约漂移信号（框架拷贝了工具对象），
    此时退回现状（内置工具可见）而非交白卷——空工具面是更严重的故障态。
    """
    tools = list(request_tools or [])
    allowed_ids = {id(t) for t in allowed_tools}
    filtered = [t for t in tools if id(t) in allowed_ids]
    return filtered if filtered else tools


def build_toolset_filter(allowed_tools: Sequence[Any], *, middleware_name: str) -> Any:
    """构造工具面复位中间件（langchain 惰性导入，缺失时给安装指引）。

    middleware_name 必填且须按域独特（WorkbenchToolsetFilter /
    ExecutionToolsetFilter）——deepagents _apply_custom_middleware 按 .name
    合并，撞上内置中间件名会被原地替换（顶掉人家）而非追加。
    """
    try:
        from langchain.agents.middleware.types import AgentMiddleware, ModelRequest
    except ImportError as e:  # pragma: no cover — 无 agent extra 的环境才会走到
        raise AgentEvalError(
            "工具面复位中间件需要 langchain（agent extra）。"
            "安装：uv sync --extra agent 或 pip install 'ai-eval-scope[agent]'"
        ) from e

    class _ToolsetFilter(AgentMiddleware):  # type: ignore[type-arg,misc]
        """模型请求级复位：可见工具 = 宿主装配清单（含 task 在内的注入面全剥）。"""

        # 类属性覆盖：AgentMiddleware.name 是只读 property，只能类级定义
        name = middleware_name

        def wrap_model_call(
            self,
            request: ModelRequest[Any],  # type: ignore[name-defined]
            handler: Callable[[ModelRequest[Any]], Any],
        ) -> Any:
            filtered = filter_visible_tools(request.tools, self._allowed)
            return handler(request.override(tools=filtered))

        async def awrap_model_call(
            self,
            request: ModelRequest[Any],  # type: ignore[name-defined]
            handler: Callable[[ModelRequest[Any]], Any],
        ) -> Any:
            filtered = filter_visible_tools(request.tools, self._allowed)
            return await handler(request.override(tools=filtered))

    middleware = _ToolsetFilter()
    middleware._allowed = list(allowed_tools)  # noqa: SLF001 — 工厂持有的宿主清单
    return middleware


__all__ = ["build_toolset_filter", "filter_visible_tools"]
