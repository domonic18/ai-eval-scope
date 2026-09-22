"""评测执行工具面规格 — 工具声明的纯数据单源。

description 文案随 prompt 发给 LLM，是行为面：改文案即改工具调用行为。

无 TOOL_BUDGETS（与 sut_probe 不同）：执行是重操作，每次 run_evaluation 必经
用户确认门槛（ask_fn 二选一，``--trust-agent`` 也不旁路）——确认即预算，
失控空转在交互层被天然限流；其余四工具均为只读枚举/回执，无预算意义。
"""

from __future__ import annotations

from agent_eval.agent.core.tools import ToolSpec

EXEC_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="run_evaluation",
        description=(
            "执行评测流水线（执行被测 Agent → 评估 → 报告/上传，单 run_id 贯通）。"
            "package 填场景包引用（list_eval_targets 的 ref）；缺省任务集/SUT/规则集"
            "从包内解析（多任务集/多系统才需 task_set/sut_name，多规则集才需 rule_set）。"
            "gate 三态：off（默认，不判定）/ strict（逐项阈值卡点）/ 小数（reward 综合卡点）。"
            "执行前必经用户确认（展示等价 CLI 命令），终端直出与 CLI 同源进度；"
            "凭证缺失会经用户逐字段补录（隐藏输入）。终端态 status：done | gate_failed"
            "（门禁未达标，报告已生成/已上报）| cancelled（协作中断，已完成任务的产物"
            "已落盘可溯源）| failed | declined | refused | busy。摘要只带关键指标，"
            "失败明细用 show_run 查看"
        ),
        method="run_evaluation",
    ),
    ToolSpec(
        name="list_eval_targets",
        description=(
            "列出可评测对象（builtin/local/project 三源场景包 + 各包内任务集/SUT/"
            "规则集清单）——run_evaluation 选参的真相源。只读；source 可选"
            "（builtin/local/project，缺省全部）。改包请走场景包管理，本工具只读"
        ),
        method="list_eval_targets",
    ),
    ToolSpec(
        name="list_runs",
        description=(
            "列出本地评测运行（新→旧：run_id/模式/状态/包/任务数/reward）。"
            "执行后衔接或「看历史」用；详情走 show_run"
        ),
        method="list_runs",
    ),
    ToolSpec(
        name="show_run",
        description=(
            "查看单次运行详情（manifest + 指标摘要 + failure_breakdown 失败归因）。"
            "run_id 来自 run_evaluation 返回或 list_runs；改包重跑前先引用该 run 的"
            "失败证据。未评估/执行失败的 run 会给出相应诊断信息"
        ),
        method="show_run",
    ),
    ToolSpec(
        name="upload_run",
        description=(
            "把已完成的运行推送到可观测平台（重建事件流：run/sample/constraint/"
            "artifact）。适合 run_evaluation 未自动上报（未配置凭据或 cancelled）后"
            "补传；回执含 platform_url 查看页。需 AGENT_EVAL_HOST/API_KEY 凭据，"
            "缺失时报 no_credentials 并给出设置引导"
        ),
        method="upload_run",
    ),
]
