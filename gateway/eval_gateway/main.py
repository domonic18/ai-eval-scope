"""FastAPI 应用入口。"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from eval_gateway.api.routes import health, jobs
from eval_gateway.config.settings import get_settings
from eval_gateway.core.exceptions import GatewayError, InputInvalidError
from eval_gateway.core.logging import setup_logging
from eval_gateway.worker.loop import WorkerLoop

app = FastAPI(title="eval-gateway", version="0.1.0")
app.include_router(health.router)
app.include_router(jobs.router)

_worker: WorkerLoop | None = None


@app.on_event("startup")
async def startup() -> None:
    setup_logging()
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    # 注：不在代码里建库。gateway schema/jobs 表由 `make db-init`（db/apply.sh）创建；
    # 启动前须已完成建库，否则 jobs 读写会报错。

    # 启动后台 worker
    global _worker
    _worker = WorkerLoop(concurrency=settings.worker_concurrency)
    _worker.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    global _worker
    if _worker:
        await _worker.stop()
        _worker = None


@app.exception_handler(GatewayError)
async def _gateway_error_handler(_request: object, exc: GatewayError) -> JSONResponse:
    """业务异常 → JSON 响应。"""
    status_code = 400 if isinstance(exc, InputInvalidError) else 500
    return JSONResponse(
        status_code=status_code,
        content={"error": exc.message, "code": exc.__class__.__name__, "details": exc.details},
    )


def run() -> None:
    """CLI 入口：uv run eval-gateway。"""
    settings = get_settings()
    uvicorn.run(
        "eval_gateway.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
