"""agent-protocol 符合性矩阵探测 — 含写操作，收尾清理（arch/15 §6.6）。

逐端点事实记录（非二值判定）：建线程 → commands → state → stream，
✅/❌ 矩阵交 Agent 写进 sut_configs 的 protocol_flavor 与端点形态依据；
矩阵机械登记进证据账本（``_record_protocol``），作为落盘对账门禁的事实源
（核心判据 = send_command）。

与执行器契约**同构**（v3.9）：AG-UI 网关族由客户端生成线程 UUID、首个
run.start 隐式建线程——执行器从不调用 POST /threads。故建线程端点失败
不再阻断矩阵（那曾是「探测失败 → 判定不支持 agent_protocol」假阴性的
根因），继续以客户端 UUID 实测 commands/state；命令信封/消息形态/
会话路由头/鉴权头全部复用执行器单源构造（thread_commands + 登录令牌），
探测说的就是执行器说的方言——探测结论直接预测执行行为。

事实质量（v3.6）：3xx 重定向**不是**端点存在的证据（页面服务/catch-all
常见，曾是假 ✅ 的来源）。
"""

from __future__ import annotations

import uuid
from typing import Any

from agent_eval.agent.probe.fetch import _host_of
from agent_eval.agent.tools import truncate
from agent_eval.execution.channels.thread_commands import (
    conversation_headers,
    run_start_envelope,
)

_PROBE_INPUT = "agent-eval-probe"  # 临时线程的探测输入（收尾即清理）
# flavor → 协议判定核心端点（单源）：矩阵步骤名与落盘对账门禁（workbench_agent
# _reconcile_protocol）共用——协议判定只看核心端点，POST /threads 不在判据内
CORE_STEP: dict[str, str] = {"commands": "send_command", "runs": "run_wait"}


class ProtocolMixin:
    """工具三：协议符合性矩阵（含写操作，收尾清理）。"""

    @property
    def protocol_hosts(self) -> set[str]:
        """已实测过协议矩阵的 host（小写）——证据账本的 host 集合视图。"""
        return set(self._verified_protocols)

    async def probe_protocol(self, base_url: str, flavor: str = "commands") -> dict[str, Any]:
        if budget_err := self._budget("probe_protocol"):
            return budget_err
        if host_err := await self._ensure_host(base_url):
            return {"error": host_err}
        base = base_url.rstrip("/")
        matrix: list[dict[str, Any]] = []
        # 执行器契约：线程 ID 客户端生成，首个 run.start 隐式建线程（v3.9 同构）
        tid = str(uuid.uuid4())
        auth = self.auth_headers
        # (步骤名, 端点模板, body, 附加头)——线程级请求带会话路由头（执行器同款）
        if flavor == "commands":
            steps: list[tuple[str, str, dict[str, Any] | None, dict[str, str]]] = [
                (
                    "create_thread",
                    "POST /threads",
                    {"metadata": {"source": "agent-eval-probe"}},
                    {},
                ),
                (
                    "send_command",
                    "POST /threads/{tid}/commands",
                    run_start_envelope(_PROBE_INPUT),
                    conversation_headers(tid),
                ),
                ("get_state", "GET /threads/{tid}/state", None, conversation_headers(tid)),
            ]
        else:  # runs 形态
            steps = [
                ("agents_search", "POST /agents/search", {}, {}),
                (
                    "run_wait",
                    "POST /threads/{tid}/runs/wait",
                    run_start_envelope(_PROBE_INPUT),
                    conversation_headers(tid),
                ),
            ]
        try:
            client_cm = await self._client()
            async with client_cm as client:
                for name, endpoint, body, extra_headers in steps:
                    method = endpoint.split(" ")[0]
                    path = endpoint.split(" ")[1].replace("{tid}", tid)
                    kwargs: dict[str, Any] = (
                        {"json": body} if body is not None and method == "POST" else {}
                    )
                    status = 0
                    try:
                        response = await client.request(
                            method, f"{base}{path}", headers={**auth, **extra_headers}, **kwargs
                        )
                        status = response.status_code
                        ok = 200 <= response.status_code < 300
                        if 300 <= response.status_code < 400:
                            # 重定向 ≠ 端点存在：catch-all/页面服务的回退不是协议证据
                            ok = False
                            note = (
                                f"HTTP {response.status_code} 重定向——页面服务/catch-all"
                                " 常见，不是协议端点的证据"
                            )
                        else:
                            note = (
                                truncate(response.text, 200)
                                if ok
                                else f"HTTP {response.status_code}"
                            )
                        if name == "create_thread" and ok:
                            # 服务端建线程形态（langgraph 平台风格）：采信服务端 tid
                            try:
                                tid = str(response.json().get("thread_id", "")) or tid
                            except Exception:  # noqa: BLE001 — tid 解析失败保留客户端 UUID
                                pass
                    except Exception as e:  # noqa: BLE001 — 单端点失败记入矩阵继续
                        ok, note = False, truncate(str(e), 200)
                    matrix.append(
                        {
                            "step": name,
                            "endpoint": endpoint.replace("{tid}", tid[:8]),
                            "ok": ok,
                            "status": status,
                            "note": note,
                        }
                    )
                if matrix and matrix[0]["step"] == "create_thread" and not matrix[0]["ok"]:
                    # 建线程端点失败 ≠ 协议不支持：执行器从不调用 POST /threads
                    matrix[0]["note"] = (
                        f"{matrix[0]['note']}——AG-UI 网关族（执行器契约）由客户端生成"
                        "线程 ID、首个 run.start 隐式建线程，已按该契约以客户端 UUID"
                        "继续实测；协议判定以 send_command/get_state 为准"
                    )
                if tid:  # stream 端点（只读响应头即断）
                    for spath in (f"/threads/{tid}/stream/events", f"/threads/{tid}/stream"):
                        try:
                            async with client.stream(
                                "GET",
                                f"{base}{spath}",
                                headers={**auth, **conversation_headers(tid)},
                            ) as s:
                                matrix.append(
                                    {
                                        "step": "stream",
                                        "endpoint": spath.replace(tid, tid[:8]),
                                        "ok": s.status_code < 400,
                                        "note": f"HTTP {s.status_code}",
                                    }
                                )
                                break
                        except Exception as e:  # noqa: BLE001
                            matrix.append(
                                {
                                    "step": "stream",
                                    "endpoint": spath.replace(tid, tid[:8]),
                                    "ok": False,
                                    "note": truncate(str(e), 120),
                                }
                            )
                if tid:  # 收尾清理（尽力而为）
                    try:
                        await client.request(
                            "DELETE",
                            f"{base}/threads/{tid}",
                            headers={**auth, **conversation_headers(tid)},
                        )
                        matrix.append(
                            {
                                "step": "cleanup",
                                "endpoint": f"DELETE /threads/{tid[:8]}…",
                                "ok": True,
                                "note": "临时线程已清理",
                            }
                        )
                    except Exception:  # noqa: BLE001 — 清理失败不影响结论
                        pass
        except Exception as e:  # noqa: BLE001
            return {"error": f"探测失败: {e}"}
        # 鉴权状态与失败模式化指引：协议端点若需认证，未鉴权请求可能 401/403
        # 也可能被网关静默 404——「未登录先探测」会产出假阴性（实测会话里 Agent
        # 在登录完成前探测协议、判死两域后放弃转抄示例）。authenticated 必须随
        # 结果显式呈现，失败分支各给单一权威 next_step（工具指引会被 LLM 当指令）
        authenticated = bool(auth)
        core = CORE_STEP.get(flavor, "run_wait")
        core_ok = any(m["step"] == core and m["ok"] for m in matrix)
        next_step = ""
        if not core_ok:
            auth_rejected = any(m.get("status") in (401, 403) for m in matrix)
            if not authenticated:
                next_step = (
                    "本次探测未携带鉴权（本会话尚无登录实测成功的 token）——协议端点"
                    "若需认证，未鉴权请求可能被拒（401/403）也可能被网关静默 404："
                    "先完成 probe_login 登录实测（成功后 token 自动挂载），再重探本工具"
                )
            elif auth_rejected:
                next_step = (
                    "已携带登录 token 但核心端点被拒绝（401/403）——确认该账号对 agent "
                    "接口是否有权限，或重新录入凭证登录后再探"
                )
            else:
                next_step = (
                    "携带登录 token 核心端点仍不通——接口域很可能不在该主机：用 "
                    "search_content 在已缓存的前端 JS 里找聊天/Agent 页面分块的真实"
                    "请求构造（URL 与载荷形态），或对会话内候选域逐一重探；全部落空"
                    "把证据呈报用户确认，勿按参照包示例臆造端点落盘"
                )
        if host := _host_of(base_url):
            self._record_protocol(
                host,
                flavor,
                {m["step"]: m["ok"] for m in matrix if m["step"] != "skipped"},
            )
        self._log("probe_protocol", base_url=base_url, steps=len(matrix))
        result: dict[str, Any] = {
            "matrix": matrix,
            "authenticated": authenticated,
            "note": (
                "逐端点事实记录，非二值判定；矩阵与执行器契约同构（线程 ID 客户端生成、"
                "run.start 信封、会话路由头与鉴权头自动挂载）——协议判定以 send_command/"
                "get_state 为准，POST /threads 是否存在不影响判定；重定向与 catch-all 200"
                " 不是证据"
            ),
        }
        if next_step:
            result["next_step"] = next_step
        return result
