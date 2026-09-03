"""agent-protocol 符合性矩阵探测 — 含写操作，收尾清理（arch/15 §6.6）。

逐端点事实记录（非二值判定）：建临时线程 → commands → state → stream，
✅/❌ 矩阵交 Agent 写进 sut_configs 的 protocol_flavor 与端点形态依据；
矩阵机械登记进证据账本（``_record_protocol``），作为落盘对账门禁的事实源。

事实质量（v3.6）：3xx 重定向**不是**端点存在的证据（页面服务/catch-all 常见，
曾是假 ✅ 的来源）；建线程失败（无 tid）时跳过后续端点——对空 tid 畸形路径的
请求落在 catch-all 上会产出「commands ✅」的假证据，把 Agent 引向错误结论。
"""

from __future__ import annotations

from typing import Any

from agent_eval.agent.probe.fetch import _host_of
from agent_eval.agent.tools import truncate


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
        tid = ""
        steps: list[tuple[str, str, dict[str, Any] | None]] = [
            ("create_thread", "POST /threads", {"metadata": {"source": "agent-eval-probe"}}),
        ]
        if flavor == "commands":
            steps += [
                ("send_command", "POST /threads/{tid}/commands", {"input": "ping"}),
                ("get_state", "GET /threads/{tid}/state", None),
            ]
        else:  # runs 形态
            steps += [
                ("agents_search", "POST /agents/search", {}),
                ("run_wait", "POST /threads/{tid}/runs/wait", {"input": "ping"}),
            ]
        try:
            client_cm = await self._client()
            async with client_cm as client:
                for name, endpoint, body in steps:
                    method = endpoint.split(" ")[0]
                    path = endpoint.split(" ")[1].replace("{tid}", tid)
                    kwargs = {"json": body} if body is not None and method == "POST" else {}
                    try:
                        response = await client.request(method, f"{base}{path}", **kwargs)
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
                            tid = str(response.json().get("thread_id", ""))
                    except Exception as e:  # noqa: BLE001 — 单端点失败记入矩阵继续
                        ok, note = False, truncate(str(e), 200)
                    matrix.append(
                        {
                            "step": name,
                            "endpoint": endpoint.replace("{tid}", tid or "…"),
                            "ok": ok,
                            "note": note,
                        }
                    )
                    if name == "create_thread" and not tid:
                        # 无 tid 时后续端点是对畸形路径（/threads//…）的请求——
                        # 落在 catch-all 上会产出假 ✅；如实记录「未探测」
                        matrix.append(
                            {
                                "step": "skipped",
                                "endpoint": "后续端点",
                                "ok": False,
                                "note": (
                                    "未获得 thread_id（建线程失败）——后续端点未探测；"
                                    "该 host 不能声明 agent_protocol"
                                ),
                            }
                        )
                        break
                if tid:  # stream 端点（只读响应头即断）
                    for spath in (f"/threads/{tid}/stream/events", f"/threads/{tid}/stream"):
                        try:
                            async with client.stream("GET", f"{base}{spath}") as s:
                                matrix.append(
                                    {
                                        "step": "stream",
                                        "endpoint": spath,
                                        "ok": s.status_code < 400,
                                        "note": f"HTTP {s.status_code}",
                                    }
                                )
                                break
                        except Exception as e:  # noqa: BLE001
                            matrix.append(
                                {
                                    "step": "stream",
                                    "endpoint": spath,
                                    "ok": False,
                                    "note": truncate(str(e), 120),
                                }
                            )
                if tid:  # 收尾清理（尽力而为）
                    try:
                        await client.request("DELETE", f"{base}/threads/{tid}")
                        matrix.append(
                            {
                                "step": "cleanup",
                                "endpoint": f"DELETE /threads/{tid}",
                                "ok": True,
                                "note": "临时线程已清理",
                            }
                        )
                    except Exception:  # noqa: BLE001 — 清理失败不影响结论
                        pass
        except Exception as e:  # noqa: BLE001
            return {"error": f"探测失败: {e}"}
        if host := _host_of(base_url):
            self._record_protocol(
                host,
                flavor,
                {m["step"]: m["ok"] for m in matrix if m["step"] != "skipped"},
            )
        self._log("probe_protocol", base_url=base_url, steps=len(matrix))
        return {
            "matrix": matrix,
            "note": (
                "逐端点事实记录，非二值判定；只有建线程与核心端点（commands/runs）"
                "均为 ✅ 才能声明 agent_protocol——重定向与 catch-all 200 不是证据"
            ),
        }
