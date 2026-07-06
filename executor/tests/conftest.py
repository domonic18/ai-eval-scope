"""测试全局 fixtures 与 mock。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# 屏蔽可选依赖，避免测试环境缺失时失败（仿 evaluator conftest 范式）
sys.modules.setdefault("langfuse", MagicMock())

from eval_executor.core.logging import setup_logging  # noqa: E402

setup_logging(level="ERROR")


@pytest.fixture(autouse=True)
def mock_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> MagicMock:
    """所有测试统一 mock executor Settings，避免依赖真实 .env。

    patch 各模块局部的 ``get_settings`` 绑定。
    """
    settings = MagicMock()
    settings.database_url = "postgresql://eval:evalpassword@localhost:5432/agent_eval?schema=public"
    settings.key_encryption_key = "dev-insecure-encryption-key"
    settings.worker_enabled = False
    settings.worker_concurrency = 1
    settings.web_base_url = "http://localhost:9000"
    settings.workspace_dir = tmp_path / "workspace"
    settings.poll_interval_sec = 0.1
    settings.http_timeout_sec = 10.0

    for mod in (
        "eval_executor.config.settings",
        "eval_executor.executor.runner",
        "eval_executor.executor.entrypoint",
        "eval_executor.worker.loop",
    ):
        monkeypatch.setattr(f"{mod}.get_settings", lambda s=settings: s)
    return settings


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
    """mock 各模块的 make_sessionmaker。

    runner / entrypoint / loop 用 ``async with make_sessionmaker()() as session``，需三层。
    """
    async_cm = MagicMock()
    async_cm.__aenter__ = AsyncMock(return_value=fake_session)
    async_cm.__aexit__ = AsyncMock(return_value=None)
    sessionmaker_obj = MagicMock(return_value=async_cm)
    mk_func = MagicMock(return_value=sessionmaker_obj)
    monkeypatch.setattr("eval_executor.executor.runner.make_sessionmaker", mk_func)
    monkeypatch.setattr("eval_executor.executor.entrypoint.make_sessionmaker", mk_func)
    monkeypatch.setattr("eval_executor.worker.loop.make_sessionmaker", mk_func)
    return mk_func
