"""FastAPI 应用入口。"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from eval_gateway.api.routes import health, jobs
from eval_gateway.config.settings import get_settings
from eval_gateway.core.exceptions import GatewayError, InputInvalidError
from eval_gateway.core.logging import setup_logging
from eval_gateway.models.db import Base
from eval_gateway.storage.session import get_engine
from eval_gateway.worker.loop import WorkerLoop

app = FastAPI(title="eval-gateway", version="0.1.0")
app.include_router(health.router)
app.include_router(jobs.router)

_worker: WorkerLoop | None = None


async def _ensure_schema() -> None:
    """幂等创建 gateway schema 与 jobs 表（供 startup 与 make gateway-db-init 复用）。"""
    settings = get_settings()
    engine = get_engine(settings)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS gateway"))
        await conn.run_sync(Base.metadata.create_all)


@app.on_event("startup")
async def startup() -> None:
    setup_logging()
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    await _ensure_schema()

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
