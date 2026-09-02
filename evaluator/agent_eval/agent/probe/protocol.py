"""agent-protocol 符合性矩阵探测 — 含写操作，收尾清理（arch/15 §6.6）。

逐端点事实记录（非二值判定）：建临时线程 → commands → state → stream，
✅/❌ 矩阵交 Agent 写进 sut_configs 的 protocol_flavor 与端点形态依据；
实测过的 host 记入 ``_protocol_hosts``，作为落盘门禁的证据源。
"""

from __future__ import annotations

from typing import Any

from agent_eval.agent.probe.fetch import _host_of
from agent_eval.agent.tools import truncate


class ProtocolMixin:
    """工具三：协议符合性矩阵（含写操作，收尾清理）。"""

    @property
    def protocol_hosts(self) -> set[str]:
        """已实测过协议矩阵的 host（小写）——落盘门禁的证据源。"""
        return set(self._protocol_hosts)

    async def probe_protocol(self, base_url: str, flavor: str = "commands") -> dict[str, Any]:
        if budget_err := self._budget("probe_protocol"):
            return budget_err
        if host_err := await self._ensure_host(base_url):
            return {"error": host_err}
        if host := _host_of(base_url):
            self._protocol_hosts.add(host.lower())
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
                        ok = response.status_code < 400
                        note = (
                            truncate(response.text, 200) if ok else f"HTTP {response.status_code}"
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
        self._log("probe_protocol", base_url=base_url, steps=len(matrix))
        return {
            "matrix": matrix,
            "note": "逐端点事实记录，非二值判定；把 ✅ 端点集合作为 protocol_flavor 与端点形态依据写进 sut_configs",
        }
