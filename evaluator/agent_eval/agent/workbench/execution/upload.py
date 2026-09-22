"""UploadTool — 运行补传（upload_run）。

薄包 ``cli.cmds.upload.upload_run_core``：进度行经
note 回调，Agent 域传 None 静默（回执自带计数）；URL 真源 =
ObservabilityConfig.run_view_url（upload_run_core 内拼装）。
"""

from __future__ import annotations

from typing import Any


class UploadTool:
    """工具：upload_run——回执数据，无终端渲染。"""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    async def upload_run(self, run_id: str, project: str = "") -> dict[str, Any]:
        from agent_eval.cli.cmds.upload import UploadError, upload_run_core

        if not run_id:
            return {"error": "run_id 必填（list_runs / run_evaluation 返回）"}
        ws = str(self.ctx.workspace_root) if self.ctx.workspace_root is not None else "./workspace"
        try:
            receipt = upload_run_core(run_id, workspace=ws, project=project or None, note=None)
        except UploadError as e:
            self.ctx.log("upload_run", run_id=run_id, kind=e.kind, error=str(e))
            guidance = {
                "missing_run": "run_id 不存在，list_runs 核对",
                "missing_summary": "该 run 未完成评估（无 summary.json），先重跑评测",
                "no_credentials": "设置 AGENT_EVAL_HOST / AGENT_EVAL_API_KEY 后重试（.env 或环境变量）",
            }.get(e.kind, "")
            return {"status": "failed", "kind": e.kind, "error": str(e), "guidance": guidance}
        self.ctx.log(
            "upload_run",
            run_id=run_id,
            sent=receipt.get("sent", 0),
            queued=receipt.get("queued", 0),
        )
        return {
            "status": "done",
            **receipt,
            "note": (
                f"平台报告: {receipt['run_url']}"
                if receipt.get("run_url")
                else "已入离线队列（凭据恢复后自动重放），run_url 见回执"
            ),
        }
