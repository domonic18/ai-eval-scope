"""测试全局 fixtures 与 mock。"""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

# 屏蔽可选依赖，避免测试环境缺失时失败（仿 evaluator conftest 范式）
sys.modules.setdefault("langfuse", MagicMock())

from eval_gateway.auth.deps import Tenant  # noqa: E402
from eval_gateway.core.logging import setup_logging  # noqa: E402

setup_logging(level="ERROR")


@pytest.fixture
def tenant() -> Tenant:
    """默认测试租户。"""
    return Tenant(
        api_key_id="ak-1",
        project_id="project-1",
        org_id="org-1",
        scopes=["ingest"],
    )


@pytest.fixture(autouse=True)
def mock_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> MagicMock:
    """所有测试统一 mock gateway Settings，避免依赖真实 .env。

    patch 所有 `from eval_gateway.config.settings import get_settings` 的模块局部绑定。
    """
    settings = MagicMock()
    settings.database_url = "postgresql://eval:evalpassword@localhost:5432/agent_eval?schema=public"
    settings.key_encryption_key = "dev-insecure-encryption-key"
    settings.port = 9000
    settings.worker_concurrency = 1
    settings.max_upload_mb = 50
    settings.web_base_url = "http://localhost:9000"
    settings.upload_dir = tmp_path / "uploads"
    settings.poll_interval_sec = 0.1

    for mod in (
        "eval_gateway.config.settings",
        "eval_gateway.worker.runner",
        "eval_gateway.api.routes.jobs",
    ):
        monkeypatch.setattr(f"{mod}.get_settings", lambda s=settings: s)
    return settings


@pytest.fixture(autouse=True)
def disable_worker_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试时禁止 worker 真实启动/轮询。"""

    class NoopLoop:
        def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    monkeypatch.setattr("eval_gateway.main.WorkerLoop", NoopLoop)


@pytest.fixture
def fake_session() -> MagicMock:
    """一个带 async 方法的 mock AsyncSession。"""
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.get = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def fake_sessionmaker(fake_session: MagicMock, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """mock runner 模块的 make_sessionmaker（runner 用 from import 绑定）。

    runner 用 `async with make_sessionmaker()() as session`，故需三层：
      make_sessionmaker()        → sessionmaker 对象
      sessionmaker()             → async context manager
      async cm __aenter__        → fake_session
    """
    async_cm = MagicMock()
    async_cm.__aenter__ = AsyncMock(return_value=fake_session)
    async_cm.__aexit__ = AsyncMock(return_value=None)
    sessionmaker_obj = MagicMock(return_value=async_cm)
    mk_func = MagicMock(return_value=sessionmaker_obj)
    monkeypatch.setattr("eval_gateway.worker.runner.make_sessionmaker", mk_func)
    return mk_func


@pytest.fixture
def app(tenant: Tenant, fake_session: MagicMock) -> FastAPI:
    """构造测试用 FastAPI app，用 dependency_overrides 覆盖鉴权与 DB 依赖。"""
    from eval_gateway.api.routes import health, jobs
    from eval_gateway.auth.deps import verify_api_key
    from eval_gateway.storage.session import get_async_session

    async def _override_auth() -> Tenant:
        return tenant

    async def _override_session() -> AsyncGenerator[MagicMock, None]:
        yield fake_session

    app_ = FastAPI()
    app_.include_router(health.router)
    app_.include_router(jobs.router)
    app_.dependency_overrides[verify_api_key] = _override_auth
    app_.dependency_overrides[get_async_session] = _override_session
    return app_


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """httpx AsyncClient 用于测试 FastAPI app。"""
    from httpx import ASGITransport

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def sample_md(tmp_path: Path) -> Path:
    """创建一个示例 Markdown 文件。"""
    path = tmp_path / "lesson-01.md"
    path.write_text("# 分数入门\n\n这是第一节内容。\n", encoding="utf-8")
    return path
