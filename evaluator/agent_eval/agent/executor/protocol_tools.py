"""Agent Protocol 语义工具面。

取代手搓 HTTP 请求：agent_run / agent_run_stream / create_thread /
run_on_thread / answer_sut_questions / cancel_run / get_agent_info /
download_sut_file 八个语义工具，封装 AgentProtocolChannel 暴露给
DeepAgents 显式绑定（ToolExporterMixin）。
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from agent_eval.agent.core.tools import ToolExporterMixin, ToolSpec, truncate
from agent_eval.core.exceptions import (
    AgentEvalError,
    AgentProtocolError,
    ToolExecutionError,
)
from agent_eval.execution.channels.agent_protocol import AgentProtocolChannel
from agent_eval.execution.channels.thread_commands import (
    ask_question_tool_call_ids,
    compact_messages,
)

# 工具结果中大体量字段的截断上限（上下文经济性，非业务阈值）
VALUES_MAX_CHARS = 4000
EVENT_DATA_MAX_CHARS = 500
MAX_STREAM_EVENTS = 100
# 产物单文件下载上限（流式累计，超限即中止——防 SUT 指向超大文件耗尽磁盘/预算）
DOWNLOAD_MAX_BYTES = 50 * 1024 * 1024


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


class AgentProtocolToolServer(ToolExporterMixin):
    """Agent Protocol 语义工具注册表，绑定一个 AgentProtocolChannel。"""

    TOOL_SPECS = TOOL_SPECS

    def __init__(
        self,
        channel: AgentProtocolChannel,
        *,
        default_metadata: dict[str, Any] | None = None,
        workspace_dir: str | Path | None = None,
    ) -> None:
        """初始化工具注册表。

        Args:
            channel: Agent Protocol 通道实例。
            default_metadata: 附加到每次 run 的元数据（如 eval_run_id/sut_name，
                便于被测系统侧审计与限流豁免协商）。
            workspace_dir: 产物下载落盘根（download_sut_file 写
                {workspace_dir}/{task_id}/output/）；缺省 None，由 ExecutionAgent
                逐 run 注入包根——目的地是执行器基础设施，不由 LLM 决定。
        """
        self.channel = channel
        self.default_metadata = default_metadata or {}
        self.workspace_dir: Path | None = Path(workspace_dir) if workspace_dir else None
        # 最近一次 SUT run 摘要（ExecutionPackage trace 回填 SUT 回答文本用）
        self.last_run: dict[str, Any] | None = None

    def _record_last_run(self, result: dict[str, Any], input: Any = None) -> None:
        """记录最近一次 run 的状态/线程/回答文本（截断前原文，供 trace 落盘）。

        input 一并记录：ExecutionAgent 的机械回显守卫据此判定「SUT 返回=请求原文」。
        interrupted 时提取待应答反问（interrupt_id/tool_call_id/题目），供
        answer_sut_questions 应答；回到 success 即清除（过时应答无意义）。
        """
        run = result.get("run") or {}
        output = result.get("output") or {}
        pending: dict[str, Any] | None = None
        if result.get("status") == "interrupted" and result.get("questions"):
            ids = ask_question_tool_call_ids(result.get("messages"))
            pending = {
                "interrupt_id": result["questions"][0].get("interrupt_id") or "",
                "tool_call_id": ids[-1] if ids else "",
                "questions": [
                    {k: v for k, v in q.items() if k != "interrupt_id"} for q in result["questions"]
                ],
            }
        self.last_run = {
            "status": result.get("status"),
            "thread_id": run.get("thread_id"),
            "run_id": run.get("run_id"),
            # commands 形态在顶层 text；runs 形态经 output_paths 提取到 output.text
            "text": result.get("text") or output.get("text") or "",
            "input": input,
            "pending": pending,
        }

    @tool_guard
    async def agent_run(
        self,
        input: dict[str, Any] | str,
        exec_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行被测 Agent：按 exec_mode 走 wait/background/stream。"""
        result = await self.channel.run(
            input, exec_mode=exec_mode, metadata=self._merge_metadata(metadata)
        )
        self._record_last_run(result, input)
        return bounded_result(result)

    @tool_guard
    async def agent_run_stream(
        self,
        input: dict[str, Any] | str,
        stream_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """流式执行并聚合（未知事件保留在 events，完整原文可写入 trace）。"""
        result = await self.channel.run_stream(
            input, stream_mode=stream_mode, metadata=self._merge_metadata(metadata)
        )
        self._record_last_run(result, input)
        result["events"] = [
            {
                "event": e.get("event"),
                "data": truncate(
                    json.dumps(e.get("data"), ensure_ascii=False, default=str), EVENT_DATA_MAX_CHARS
                ),
            }
            for e in result.get("events", [])[:MAX_STREAM_EVENTS]
        ]
        return bounded_result(result)

    @tool_guard
    async def create_thread(self, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """创建多轮会话线程。"""
        return await self.channel.create_thread(self._merge_metadata(metadata))

    @tool_guard
    async def run_on_thread(
        self,
        thread_id: str,
        input: dict[str, Any] | str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """在既有线程上执行一轮。"""
        result = await self.channel.run_on_thread(
            thread_id, input, metadata=self._merge_metadata(metadata)
        )
        self._record_last_run(result, input)
        return bounded_result(result)

    @tool_guard
    async def answer_sut_questions(self, answers: list[Any]) -> dict[str, Any]:
        """应答被测 Agent 的 askQuestion 反问并续跑至终态（一次调用闭环）。

        answers 逐题对应最近一次 interrupted run 的 questions 顺序：字符串视为
        单选值，{"selected": [...], "customText": ...} 原样透传。应答经
        input.respond 提交后继续轮询到终态——评估 Agent 无需再手动 run_on_thread。

        恢复载荷为前端同款 ``{"answers": [逐题答案]}``（run 20260910_234613 实测：
        旧实现按 ask_question 工具调用 id 键控，SUT 端校验不到 answers 数组报
        「答案数据无效(非数组)未采纳」，SUT agent 视角=提问卡片失败 ×3 后放弃反问）。
        """
        pending = (self.last_run or {}).get("pending")
        if not pending:
            raise ToolExecutionError(
                "没有待应答的反问——仅当 agent_run/run_on_thread 返回 interrupted"
                "（带 questions）后才可调用本工具"
            )
        questions = pending.get("questions") or []
        if not isinstance(answers, list) or len(answers) != len(questions):
            received = len(answers) if isinstance(answers, list) else type(answers).__name__
            raise ToolExecutionError(
                f"反问共 {len(questions)} 题，收到 {received} 份答案，须逐题一一对应: "
                + json.dumps(questions, ensure_ascii=False)
            )
        response = {"answers": [_normalize_answer(a) for a in answers]}
        result = await self.channel.answer_interrupt(
            self.last_run.get("thread_id") or "", pending["interrupt_id"], response
        )
        self._record_last_run(result, answers)
        return bounded_result(result)

    @tool_guard
    async def cancel_run(self, run_id: str, action: str = "interrupt") -> dict[str, Any]:
        """主动取消 run。"""
        return await self.channel.cancel_run(run_id, action)

    @tool_guard
    async def get_agent_info(self, agent_id: str | None = None) -> dict[str, Any]:
        """能力与 schema 发现。"""
        return await self.channel.get_agent_info(agent_id)

    @tool_guard
    async def download_sut_file(
        self,
        url: str,
        task_id: str,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """下载 SUT 产物文件到执行包 output/（随既有链路自动入包指纹与上报）。

        机械边界（不依赖 LLM 自觉）：相对路径按 base_url 解析；绝对 URL 的 host
        必须在白名单（base_url 域 ∪ sut.artifact_hosts）内，防 SUT 返回恶意地址；
        流式累计字节超 DOWNLOAD_MAX_BYTES 即中止。文件名经 basename 拍平防路径逃逸。
        """
        dest_url, dest_path = self._download_destination(url, task_id, filename)
        try:
            try:
                size, content_type = await self._stream_download(dest_url, dest_path)
            except httpx.HTTPError as e:
                raise ToolExecutionError(f"产物下载传输失败: {e}", details={"url": dest_url}) from e
        except BaseException:
            dest_path.unlink(missing_ok=True)  # 半截文件不留包（孤儿文件防护）
            raise
        return {
            "status": "success",
            "file": f"output/{dest_path.name}",
            "size_bytes": size,
            "content_type": content_type,
        }

    def _download_destination(
        self, url: str, task_id: str, filename: str | None
    ) -> tuple[str, Path]:
        """解析下载 URL（host 白名单）与落盘目的地（workspace/{task_id}/output/）。"""
        if self.workspace_dir is None:
            raise ToolExecutionError("执行上下文未配置 workspace_dir，无法落盘下载产物")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", task_id):
            raise ToolExecutionError(
                f"非法 task_id（仅允许字母/数字/./_/-）: {task_id!r}",
                details={"task_id": task_id},
            )
        resolved_url = self._resolve_download_url(url)
        name = Path(filename).name if filename else Path(urlparse(resolved_url).path).name
        if not name or name in (".", ".."):
            name = "artifact"  # URL 尾段无文件名（如以 / 结尾）时的兜底名
        dest_dir = self.workspace_dir / task_id / "output"
        dest_dir.mkdir(parents=True, exist_ok=True)
        return resolved_url, dest_dir / name

    def _resolve_download_url(self, url: str) -> str:
        """相对路径拼 base_url（host 恒为 SUT 域）；绝对 URL 做 host 白名单校验。"""
        parsed = urlparse(url)
        if not parsed.netloc:
            base = self.channel.sut.base_url.rstrip("/")
            return f"{base}/{url.lstrip('/')}"
        base_host = (urlparse(self.channel.sut.base_url).hostname or "").lower()
        allowed = {
            base_host,
            *(h.strip().lower() for h in self.channel.sut.artifact_hosts if h.strip()),
        } - {""}
        host = (parsed.hostname or "").lower()
        if host not in allowed:
            raise ToolExecutionError(
                f"下载 URL 越界: host {host!r} 不在白名单（base_url 域 ∪ sut.artifact_hosts）"
                "——SUT 产物仅在配置声明的域内下载",
                details={"host": host, "allowed": sorted(allowed)},
            )
        return url

    async def _stream_download(self, url: str, path: Path) -> tuple[int, str]:
        """流式下载到 path，返回 (字节数, Content-Type)；HTTP 错误/超限即中止。"""
        session = await self.channel.auth.get_session()
        size = 0
        async with self.channel.client.stream(
            "GET", url, headers=session.mount_headers() or None, timeout=self.channel.sut.timeout
        ) as response:
            if response.status_code >= 400:
                raise AgentProtocolError(
                    f"产物下载失败（HTTP {response.status_code}）: {url}",
                    details={"sut": self.channel.sut.name, "status_code": response.status_code},
                )
            content_type = response.headers.get("content-type", "")
            with path.open("wb") as fh:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > DOWNLOAD_MAX_BYTES:
                        raise ToolExecutionError(
                            f"产物超过单文件大小上限 {DOWNLOAD_MAX_BYTES} 字节，已中止: {url}",
                            details={"url": url, "limit_bytes": DOWNLOAD_MAX_BYTES},
                        )
                    fh.write(chunk)
        return size, content_type

    def _merge_metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        return {**self.default_metadata, **(metadata or {})}


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


def bounded_result(result: dict[str, Any]) -> dict[str, Any]:
    """截断大体量字段（values/messages 先摘要化再文本化），保留状态与产出物结构。"""
    bounded = dict(result)
    for field in ("values", "messages", "text"):
        if field in bounded and bounded[field] is not None:
            if isinstance(bounded[field], str):
                bounded[field] = truncate(bounded[field], VALUES_MAX_CHARS)
            else:
                bounded[field] = truncate(
                    json.dumps(_digest_payload(bounded[field]), ensure_ascii=False, default=str),
                    VALUES_MAX_CHARS,
                )
    if "error" in bounded and isinstance(bounded["error"], dict):
        message = bounded["error"].get("message")
        if isinstance(message, str):
            bounded["error"]["message"] = truncate(message, VALUES_MAX_CHARS)
    return bounded


__all__ = ["AgentProtocolToolServer"]
