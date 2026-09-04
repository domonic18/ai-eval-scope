"""AgentProtocolChannel — Agent Protocol v0.1.6 通道（arch/03 §4.0.6，本期唯一排期通道）。

封装协议语义调用：runs/wait、runs/background、runs/stream（SSE 容错聚合）、
threads 多轮、cancel、agents 能力发现；RunStatus → 执行引擎状态机映射固定表；
产出物按 sut.output_paths 提取（取代 response_mapping）。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx

from agent_eval.core.exceptions import AgentProtocolError
from agent_eval.execution.channels.base import SUTChannel
from agent_eval.execution.channels.thread_commands import (
    _iter_sse,  # noqa: F401 — SSE 解析迁至 thread_commands，此处重导出保持兼容
    commands_agent_info,
    commands_run,
    commands_stream,
)
from agent_eval.execution.registry import SUTSystemConfig
from agent_eval.execution.utils import extract_by_path

# RunStatus → 执行引擎状态（固定表，§4.0.6-d；协议无 running，pending 直达终态）
STATUS_MAP: dict[str, str] = {
    "success": "success",
    "error": "failed",
    "timeout": "failed",
    "interrupted": "interrupted",
    "pending": "running",
}
TERMINAL_STATUSES = frozenset({"success", "error", "timeout", "interrupted"})


class AgentProtocolChannel(SUTChannel):
    """Agent Protocol 通道：语义级协议调用 + 状态机映射 + 流事件容错聚合。"""

    channel_type = "agent_protocol"

    def __init__(
        self,
        sut: SUTSystemConfig,
        *,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        super().__init__(sut, http_client_factory=http_client_factory)

    # ─── 执行（§4.0.6-a exec_mode） ───

    async def run(
        self,
        input: Any,
        *,
        exec_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行一次 run：wait（默认阻塞）/ background（超时自动 cancel）/ stream。"""
        mode = exec_mode or self.sut.exec_mode
        if self.sut.protocol_flavor == "commands":
            if mode == "stream":
                return await commands_stream(self, input, metadata=metadata)
            return await commands_run(self, input, metadata=metadata)
        if mode == "stream":
            return await self.run_stream(input, metadata=metadata)
        if mode == "wait":
            response = await self.request(
                "POST", "/runs/wait", json_body=self._run_body(input, metadata)
            )
            return self._parse_wait_response(response)
        # background：POST /runs → GET /runs/{id}/wait；我方超时 → cancel(interrupt)
        response = await self.request("POST", "/runs", json_body=self._run_body(input, metadata))
        run_id = self._json(response).get("run_id")
        if not run_id:
            raise AgentProtocolError(
                "background 启动响应缺少 run_id", details={"sut": self.sut.name}
            )
        try:
            wait_response = await self.request("GET", f"/runs/{run_id}/wait")
        except Exception as e:  # noqa: BLE001 — 超时与网络异常都要走取消路径
            if isinstance(getattr(e, "__cause__", None), httpx.TimeoutException):
                await self._safe_cancel(run_id)
                raise AgentProtocolError(
                    f"run pending 超过超时，已主动 cancel(interrupt): {run_id}",
                    details={"sut": self.sut.name, "run_id": run_id},
                ) from e
            raise
        return self._parse_wait_response(wait_response)

    async def run_stream(
        self,
        input: Any,
        *,
        stream_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """runs/stream（SSE）：容错聚合——未知事件原样保留，语义聚合仅依赖 run 终态。"""
        if self.sut.protocol_flavor == "commands":
            return await commands_stream(self, input, metadata=metadata)
        body = {
            **self._run_body(input, metadata),
            "stream_mode": stream_mode or self.sut.stream_mode,
        }
        session = await self.auth.get_session()
        headers = {**session.mount_headers(), "Accept": "text/event-stream"}
        url = f"{self.sut.base_url.rstrip('/')}/runs/stream"
        events: list[dict[str, Any]] = []
        text_parts: list[str] = []
        final_status: str | None = None
        last_values: Any = None
        try:
            async with self.client.stream(
                "POST", url, json=body, headers=headers or None, timeout=self.sut.timeout
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise AgentProtocolError(
                        f"runs/stream 失败（HTTP {response.status_code}）",
                        details={"sut": self.sut.name, "body": response.text[:500]},
                    )
                async for event_name, data_text in _iter_sse(response):
                    try:
                        data: Any = json.loads(data_text) if data_text else {}
                    except json.JSONDecodeError:
                        data = {"raw": data_text}  # 非 JSON 数据原样保留
                    events.append({"event": event_name, "data": data})
                    if not isinstance(data, dict):
                        continue
                    run_obj = data.get("run")
                    if isinstance(run_obj, dict) and run_obj.get("status") in TERMINAL_STATUSES:
                        final_status = run_obj.get("status")
                    if isinstance(data.get("values"), dict):
                        last_values = data["values"]
                    message = data.get("message")
                    if isinstance(message, dict) and isinstance(message.get("content"), str):
                        text_parts.append(message["content"])
        except httpx.HTTPError as e:
            raise AgentProtocolError(
                f"runs/stream 传输失败: {e}", details={"sut": self.sut.name}
            ) from e
        return {
            "status": STATUS_MAP.get(final_status or "pending", "running"),
            "run_status": final_status,
            "text": "\n".join(text_parts),
            "output": self._extract_output(last_values or {}),
            "events": events,
        }

    # ─── Threads 多轮（§4.0.6-e：每 thread 单活跃 run，多轮任务才显式建线程） ───

    async def create_thread(self, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.sut.protocol_flavor == "commands":
            # commands 形态线程由客户端生成 UUID（首个 run.start 隐式建线程）——
            # 本地构造值须显式标注，防止被当作服务端可达的证据
            return {
                "thread_id": str(uuid.uuid4()),
                "source": "local-simulated",
                "note": (
                    "线程 ID 由客户端生成（首个 run.start 隐式建线程）——"
                    "本次未访问服务器，不能作为服务端可达的证据"
                ),
            }
        response = await self.request("POST", "/threads", json_body={"metadata": metadata or {}})
        thread_id = self._json(response).get("thread_id")
        if not thread_id:
            raise AgentProtocolError("创建线程响应缺少 thread_id", details={"sut": self.sut.name})
        return {"thread_id": thread_id}

    async def run_on_thread(
        self,
        thread_id: str,
        input: Any,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.sut.protocol_flavor == "commands":
            return await commands_run(self, input, thread_id=thread_id, metadata=metadata)
        response = await self.request(
            "POST", f"/threads/{thread_id}/runs/wait", json_body=self._run_body(input, metadata)
        )
        return self._parse_wait_response(response)

    async def cancel_run(self, run_id: str, action: str = "interrupt") -> dict[str, Any]:
        """主动取消（interrupt / rollback——rollback 仅在系统声明支持时使用）。"""
        response = await self.request(
            "POST", f"/runs/{run_id}/cancel", json_body={"action": action}
        )
        return {"run_id": run_id, "action": action, "response": self._json(response)}

    # ─── 能力发现与接入自检（§4.0.6-f） ───

    async def get_agent_info(self, agent_id: str | None = None) -> dict[str, Any]:
        """/agents/search + /agents/{id}/schemas 能力与 schema 发现。"""
        if self.sut.protocol_flavor == "commands":
            return commands_agent_info(self, agent_id)
        response = await self.request("POST", "/agents/search", json_body={})
        agents = self._json(response).get("agents") or []
        resolved = agent_id or self.sut.agent_id
        if not resolved and agents:
            resolved = agents[0].get("agent_id")
        if not resolved:
            raise AgentProtocolError(
                "agents/search 未发现任何 agent（且未配置 agent_id）",
                details={"sut": self.sut.name},
            )
        schemas_response = await self.request("GET", f"/agents/{resolved}/schemas")
        schemas = self._json(schemas_response)
        return {
            "agent_id": resolved,
            "agents": [a.get("agent_id") for a in agents if isinstance(a, dict)],
            "schemas": schemas,
            "protocol_version": self.sut.protocol_version,
        }

    async def check_capabilities(self, required: list[str] | None = None) -> dict[str, Any]:
        """接入自检：能力支持度 + output_paths 配置有效性，失败拒绝接入。"""
        info = await self.get_agent_info()
        capabilities = (info["schemas"] or {}).get("capabilities") or {}
        issues: list[str] = []
        for capability in required or []:
            if not capabilities.get(capability):
                issues.append(f"缺少能力: {capability}")
        output_paths = self.sut.output_paths
        if (output_paths.files_field or output_paths.text_field) and not (
            info["schemas"] or {}
        ).get("output_schema"):
            issues.append("配置了 output_paths 但服务未声明 output_schema")
        result = {
            "ok": not issues,
            "issues": issues,
            "agent_id": info["agent_id"],
            "capabilities": capabilities,
            "protocol_version": info["protocol_version"],
        }
        if issues:
            raise AgentProtocolError(
                f"能力自检失败: {'; '.join(issues)}",
                details={"sut": self.sut.name, "issues": issues},
            )
        return result

    async def health_check(self) -> dict[str, Any]:
        """通道健康检查（= 能力自检）。"""
        return await self.check_capabilities()

    # ─── 内部 ───

    def _run_body(self, input: Any, metadata: dict[str, Any] | None) -> dict[str, Any]:
        body: dict[str, Any] = {"input": input}
        if self.sut.agent_id:
            body["assistant_id"] = self.sut.agent_id
        if self.sut.on_completion:
            body["on_completion"] = self.sut.on_completion  # 评估默认 delete：临时线程用完即删
        if metadata:
            body["metadata"] = metadata  # 携带 {eval_run_id, task_id, sut_name} 便于审计
        return body

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload: dict[str, Any] = response.json()
            return payload
        except ValueError as e:
            raise AgentProtocolError(
                f"协议响应不是合法 JSON: {e}",
                details={"sut": self.sut.name, "status_code": response.status_code},
            ) from e

    def _parse_wait_response(self, response: httpx.Response) -> dict[str, Any]:
        payload = self._json(response)
        run_obj = payload.get("run") or {}
        run_status = run_obj.get("status", "pending")
        if run_status == "error":
            error = payload.get("error") or {}
            return {
                "status": "failed",
                "run": run_obj,
                "error": {
                    "code": error.get("code"),
                    "message": error.get("message"),
                },
                "messages": payload.get("messages") or [],
            }
        return {
            "status": STATUS_MAP.get(run_status, "running"),
            "run": run_obj,
            "values": payload.get("values"),
            "messages": payload.get("messages") or [],
            "output": self._extract_output(payload),
        }

    def _extract_output(self, payload: Any) -> dict[str, Any]:
        """按 sut.output_paths 从 RunWaitResponse 提取产出物（files/text）。"""
        output: dict[str, Any] = {}
        paths = self.sut.output_paths
        if paths.files_field and isinstance(payload, dict):
            output["files"] = extract_by_path(payload, paths.files_field)
        if paths.text_field and isinstance(payload, dict):
            output["text"] = extract_by_path(payload, paths.text_field)
        return output

    async def _safe_cancel(self, run_id: str) -> None:
        try:
            await self.cancel_run(run_id, action="interrupt")
        except Exception:  # noqa: BLE001 — 取消失败不掩盖主错误
            pass
