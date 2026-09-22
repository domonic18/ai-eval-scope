"""Agent Protocol 工具面共享件 — 常量 / 守卫装饰器 / 结果限幅纯函数。

无 server 状态的模块级支持件：截断上限常量、通道异常转 failed 结果的
``tool_guard``、决策简报注入的 ``briefing_enriched``、大体量字段保尾弃头的
``bounded_result`` 家族。被 protocol_tools*.py 各模块共用。
"""

from __future__ import annotations

import functools
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from agent_eval.agent.core.tools import truncate
from agent_eval.core.exceptions import AgentEvalError, ToolExecutionError
from agent_eval.execution.channels.message_digest import compact_messages

# 工具结果中大体量字段的截断上限（上下文经济性，非业务阈值）
VALUES_MAX_CHARS = 4000
EVENT_DATA_MAX_CHARS = 500
MAX_STREAM_EVENTS = 100
# 产物单文件下载上限（流式累计，超限即中止——防 SUT 指向超大文件耗尽磁盘/预算）
DOWNLOAD_MAX_BYTES = 50 * 1024 * 1024
# 【临时停用 2026-09-11，用户指示】staging 网关对 SUT 报告的产物路径（file:///workspace/...）
# 统一回 SPA 前端壳，下载必然失败且空烧执行步数（run 20260911_073626：3 连败促成
# 收尾拖延）——评测执行期间暂停下载功能，工具入口直接返回带收尾指引的 failed 结果
# （不触网、不耗下载预算）。恢复下载：置 True 即可，原逻辑无改动。
SUT_FILE_DOWNLOAD_ENABLED = False
# SPA 前端壳嗅探窗口（网关 fallback 页面远小于此）
SPA_SNIFF_BYTES = 4096
# 同任务 SUT 调用超时重试上限（机械守卫）：
# 真超时后再重试只会重烧同量级时长（run 20260910_134410 实测 chinese/english
# 各烧 3.7h/3.9h）。超过上限后 SUT 执行调用直接返回 TimeoutBudgetExhausted，
# 证据随结果透出供写失败包；只读取证与产物下载不受限
TIMEOUT_RETRY_LIMIT = 1
TIMEOUT_EVIDENCE_MAX_CHARS = 300


def _looks_like_spa_shell(path: Path) -> bool:
    """命中 SUT 网关 SPA 前端指纹：root 挂载点 + /assets/index-*.js 模块脚本。

    AG-UI 网关族对未知文件路径回前端壳而非 404（commands_agent_info 已记录的
    fallback 行为）——该「文件」不是产物，落包会让评估对象变成 JS 应用骨架
    （2026-09-11 实测：29.2k 课件被 396 字节 SPA 壳顶替入包）。双指纹同时命中
    才判定，含 root div 的正常 HTML 产物不受影响。
    """
    try:
        head = path.read_bytes()[:SPA_SNIFF_BYTES].decode("utf-8", errors="ignore")
    except OSError:
        return False
    return '<div id="root"' in head and "/assets/index-" in head


def tool_guard(
    fn: Callable[..., Awaitable[dict[str, Any]]],
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """通道异常 → failed 结果（执行 Agent 可据以重试/降级/写错误包，而非中断图）。"""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return await fn(*args, **kwargs)
        except AgentEvalError as e:
            return {
                "status": "failed",
                "error": {
                    "type": type(e).__name__,
                    "message": truncate(str(e), VALUES_MAX_CHARS),
                },
            }

    return wrapper


def briefing_enriched(
    fn: Callable[..., Awaitable[dict[str, Any]]],
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """动作工具出口统一过 ``_enrich_result``。

    叠在 tool_guard 之上（guard 先把通道异常转 failed，简报随后照常注入
    ——拒绝载荷同样需要指路）；方法层而非导出层（_json_tool）：直调与
    LangChain 导出两条路径行为一致。
    """

    @functools.wraps(fn)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = await fn(self, *args, **kwargs)
        # _enrich_result 契约恒返回 dict（非 dict 结果恒等返回不会走到此处）
        enriched: dict[str, Any] = self._enrich_result(result, tool=fn.__name__)
        return enriched

    return wrapper


# 决策简报注入面：对外部世界的昂贵动作 + 取证动作——
# 每次执行后刷新，决策体在下一轮看的是最新现实；取证收尾类工具
# （answer_sut_questions/cancel_run/get_agent_info/create_thread）不注入
_BRIEFING_TOOLS = frozenset(
    {
        "agent_run",
        "agent_run_stream",
        "run_on_thread",
        "read_thread_state",
        "download_sut_file",
    }
)


def _normalize_answer(answer: Any) -> dict[str, Any]:
    """答案规范化：字符串视为单选值；dict 透传（selected 为字符串时包装为列表）。"""
    if isinstance(answer, str):
        return {"selected": [answer]}
    if isinstance(answer, dict):
        normalized = dict(answer)
        if isinstance(normalized.get("selected"), str):
            normalized["selected"] = [normalized["selected"]]
        return normalized
    raise ToolExecutionError(
        f"不支持的反问答案形态: {type(answer).__name__}（应为字符串或 {{selected: [...]}}）"
    )


def _digest_payload(value: Any) -> Any:
    """values/messages 载荷摘要：messages 替换为去 reasoning 的对话骨架。"""
    if isinstance(value, list):
        return compact_messages(value)
    if isinstance(value, dict) and isinstance(value.get("messages"), list):
        shallow = dict(value)
        shallow["messages"] = compact_messages(shallow["messages"])
        return shallow
    return value


def _messages_tail_json(messages: list[dict[str, Any]], budget: int) -> str:
    """消息序列化保尾弃头：预算从最新消息向前分配，历史头部以占位标记省略。

    整表 dumps 再头部截断在多轮线程上会把最新一条 SUT 回复（往往携带产物路径
    或完成声明）挤出窗口——执行 Agent「看不见」交付物便空转催促（run
    20260911_010507 实测：12 次催促烧尽 20 轮，文件路径始终不可见）。最新一条
    无条件保留（compact 后单条文本 ≤ COMPACT_TEXT_MAX_CHARS，预算必然容纳）。
    """
    kept: list[dict[str, Any]] = []
    used = 2  # JSON 数组方括号
    for message in reversed(messages):
        chunk = json.dumps(message, ensure_ascii=False, default=str)
        if kept and used + len(chunk) + 1 > budget:
            break
        kept.insert(0, message)
        used += len(chunk) + 1
    omitted = len(messages) - len(kept)
    if omitted <= 0:
        return json.dumps(kept, ensure_ascii=False, default=str)
    marker = json.dumps({"note": f"（前 {omitted} 条历史消息已省略）"}, ensure_ascii=False)
    return json.dumps([marker, *kept], ensure_ascii=False, default=str)


def _values_tail_json(values: dict[str, Any], budget: int) -> str:
    """values 外壳 + messages 的复合载荷保尾弃头（与消息列表同病同治）。

    values（state 终态）是 {messages: [...], ...} 复合结构——整表 dumps 再
    头部截断同样会把最新一条 SUT 回复挤出窗口，故 messages 用同一保尾预算
    序列化，外壳其余键 dumps 计入预算开销（过半则先头部截断）。
    """
    shell = {k: v for k, v in values.items() if k != "messages"}
    shell_json = json.dumps(shell, ensure_ascii=False, default=str)
    if len(shell_json) > budget // 2:
        shell_json = truncate(shell_json, budget // 2)
    messages_budget = budget - len(shell_json) - 20  # 组合键名/括号序列化开销
    tail = _messages_tail_json(values.get("messages") or [], max(messages_budget, 200))
    combined = {**json.loads(shell_json), "messages": json.loads(tail)}
    return json.dumps(combined, ensure_ascii=False, default=str)


def bounded_result(result: dict[str, Any]) -> dict[str, Any]:
    """截断大体量字段（values/messages 先摘要化再文本化），保留状态与产出物结构。

    消息列表与 values 复合载荷走保尾弃头——最新一条 SUT 回复必须留在
    窗口内；其余字段维持头部截断语义。
    """
    bounded = dict(result)
    for field in ("values", "messages", "text"):
        if field in bounded and bounded[field] is not None:
            if isinstance(bounded[field], str):
                bounded[field] = truncate(bounded[field], VALUES_MAX_CHARS)
                continue
            digest = _digest_payload(bounded[field])
            if isinstance(digest, list):
                bounded[field] = _messages_tail_json(digest, VALUES_MAX_CHARS)
            elif isinstance(digest, dict) and isinstance(digest.get("messages"), list):
                bounded[field] = _values_tail_json(digest, VALUES_MAX_CHARS)
            else:
                bounded[field] = truncate(
                    json.dumps(digest, ensure_ascii=False, default=str), VALUES_MAX_CHARS
                )
    if "error" in bounded and isinstance(bounded["error"], dict):
        message = bounded["error"].get("message")
        if isinstance(message, str):
            bounded["error"]["message"] = truncate(message, VALUES_MAX_CHARS)
    return bounded
