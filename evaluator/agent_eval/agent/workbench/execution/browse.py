"""BrowseTool — 运行浏览（list_runs / show_run）。

薄包 ``cli.cmds.runs`` 提纯函数（Sprint 14b C2）：scan_runs / run_detail
均为纯数据（无 rprint/typer），Agent 域直接消费——「会话内看结果」的只读面。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class BrowseTool:
    """工具：list_runs / show_run——只读，不触网。"""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    def _ws(self) -> Path | None:
        return self.ctx.workspace_root

    async def list_runs(self, limit: int = 10) -> dict[str, Any]:
        from agent_eval.cli.cmds.runs import scan_runs

        if limit <= 0:
            return {"error": f"limit 须为正整数（收到 {limit}）"}
        runs = scan_runs(self._ws())
        self.ctx.log("list_runs", total=len(runs), limit=limit)
        if not runs:
            return {
                "runs": [],
                "total": 0,
                "note": "本地无运行记录——先 run_evaluation，或确认 workspace 目录指向",
            }
        return {
            "runs": runs[:limit],
            "total": len(runs),
            "note": f"共 {len(runs)} 次（新→旧，返回前 {min(limit, len(runs))} 条）；详情 show_run(run_id=...)",
        }

    async def show_run(self, run_id: str) -> dict[str, Any]:
        from agent_eval.cli.cmds.runs import run_detail, scan_runs

        if not run_id:
            return {"error": "run_id 必填（list_runs 查看）"}
        detail = run_detail(run_id, self._ws())
        self.ctx.log("show_run", run_id=run_id, found=detail is not None)
        if detail is None:
            return {
                "error": f"运行不存在: {run_id}（list_runs 查看可用 run_id；workspace 目录 {self._ws()}）"
            }
        summary = detail.get("summary") or {}
        # 诊断补全：执行失败型 run 无 summary——从 scan_runs 同源状态机取失败原因
        status_hint = ""
        if not summary:
            for r in scan_runs(self._ws()):
                if r["run_id"] == run_id:
                    status_hint = f"状态: {r['status']}" + (
                        f"；失败原因: {r['error']}" if r.get("error") else ""
                    )
                    break
        note = "推送平台用 upload_run(run_id=...)" if summary else "该 run 未完成评估，无指标可看"
        return {**detail, "status_hint": status_hint, "note": note}
