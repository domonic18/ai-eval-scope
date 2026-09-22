"""AgentProtocolToolServer 的工具规格定义（与实现分离）。

九个语义工具的 ToolSpec（Agent 侧工具文档）；同名异步方法实现见
protocol_tools_run / protocol_tools_sut。
"""

from __future__ import annotations

from agent_eval.agent.core.tools import ToolSpec

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="agent_run",
        description="执行被测 Agent（Agent Protocol）：wait 阻塞 / background 后台 / stream 流式，返回终态与产出物",
        method="agent_run",
    ),
    ToolSpec(
        name="agent_run_stream",
        description="流式执行被测 Agent 并聚合为完整输出 + 过程事件列表（需过程数据时使用）",
        method="agent_run_stream",
    ),
    ToolSpec(
        name="create_thread",
        description="创建多轮会话线程（对话式任务用；每 thread 同时仅一个活跃 run）",
        method="create_thread",
    ),
    ToolSpec(
        name="run_on_thread",
        description="在既有线程上执行一轮（多轮对话任务的后续轮次）",
        method="run_on_thread",
    ),
    ToolSpec(
        name="read_thread_state",
        description=(
            "只读查看线程当前状态（不注入新消息、不打断 SUT）：run 超时或拿不到"
            "产物时先取证——thread_busy=false 且 values/messages 有内容说明 SUT 已完成"
        ),
        method="read_thread_state",
    ),
    ToolSpec(
        name="answer_sut_questions",
        description=(
            "应答被测 Agent 的反问（run 返回 interrupted 且带 questions 时）："
            "按题目顺序逐题作答并续跑至终态；答案为选项值字符串或"
            " {'selected': [...], 'customText': '...'}"
        ),
        method="answer_sut_questions",
    ),
    ToolSpec(
        name="cancel_run",
        description="主动取消 run（interrupt 打断 / rollback 回滚，rollback 仅系统声明支持时用）",
        method="cancel_run",
    ),
    ToolSpec(
        name="get_agent_info",
        description="能力与 schema 发现（agents/search + schemas，接入自检用）",
        method="get_agent_info",
    ),
    ToolSpec(
        name="download_sut_file",
        description=(
            "下载被测系统生成的产物文件到执行包 output/（相对路径按 SUT 域解析；"
            "绝对 URL 仅允许 SUT 域与配置的 artifact_hosts）"
        ),
        method="download_sut_file",
    ),
]
