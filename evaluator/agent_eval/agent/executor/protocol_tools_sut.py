"""AgentProtocolToolServer SUT 交互类工具 mixin — answer_sut_questions / cancel_run / get_agent_info / download_sut_file。

Agent 可调用；通道异常经 tool_guard 转 failed 结果交 Agent 自修复。
下载含机械边界（host 白名单 / 流式限额 / SPA 壳识别）。
仅供 ``protocol_tools.AgentProtocolToolServer`` 组合，不独立使用。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from agent_eval.agent.executor.protocol_shared import (
    DOWNLOAD_MAX_BYTES,
    SUT_FILE_DOWNLOAD_ENABLED,
    _looks_like_spa_shell,
    _normalize_answer,
    bounded_result,
    briefing_enriched,
    tool_guard,
)
from agent_eval.agent.executor.protocol_state import ProtocolStateMixin
from agent_eval.core.exceptions import AgentProtocolError, ToolExecutionError


class ProtocolSutToolsMixin(ProtocolStateMixin):
    """反问应答 / 取消 / 能力发现 / 产物下载（组合用 mixin）。"""

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
            (self.last_run or {}).get("thread_id") or "", pending["interrupt_id"], response
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

    @briefing_enriched
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

        【临时停用】SUT_FILE_DOWNLOAD_ENABLED=False 期间入口直接返回带收尾指引的
        failed 结果——不触网、不耗下载预算（停用缘由见常量注释）。
        """
        if not SUT_FILE_DOWNLOAD_ENABLED:
            self._ledger_record("download", "disabled", time.monotonic(), summary=url)
            return {
                "status": "failed",
                "error": {
                    "type": "ToolDisabled",
                    "message": (
                        "download_sut_file 临时停用（SUT 网关产物路径暂不可达，下载必然失败）。"
                        "不要重试下载；把产物路径与 SUT 回复原文作为证据，直接 "
                        "write_package 收尾（成功与否据已收集到的证据如实判定）"
                    ),
                },
                "url": url,
            }
        refused = self._budget("download")
        if refused is not None:
            return refused
        started = time.monotonic()
        dest_url, dest_path = self._download_destination(url, task_id, filename)
        try:
            try:
                size, content_type = await self._stream_download(dest_url, dest_path)
            except httpx.HTTPError as e:
                raise ToolExecutionError(f"产物下载传输失败: {e}", details={"url": dest_url}) from e
            if _looks_like_spa_shell(dest_path):
                raise ToolExecutionError(
                    "下载内容命中 SUT 网关前端壳（SPA fallback）——该路径没有真实产物，"
                    "请核对产物路径后重试或如实记录下载失败",
                    details={"url": dest_url},
                )
        except BaseException:
            dest_path.unlink(missing_ok=True)  # 半截文件不留包（孤儿文件防护）
            self._ledger_record("download", "error", started, summary=dest_path.name)
            raise
        self._ledger_record("download", "ok", started, summary=dest_path.name)
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
