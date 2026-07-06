"""entrypoint 单元测试 — mock 状态机与下载/执行，断言事件解析与流程。"""

from __future__ import annotations

from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from eval_executor.executor import entrypoint as ep


def test_parse_event_from_local_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVALEXECUTOR_JOB_JSON", '{"job_id": "j1"}')
    assert ep._parse_event() == {"job_id": "j1"}


def test_parse_event_from_scf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCF_CUSTOM_CONTAINER_EVENT", '{"job_id": "j2"}')
    monkeypatch.delenv("EVALEXECUTOR_JOB_JSON", raising=False)
    assert ep._parse_event() == {"job_id": "j2"}


def test_parse_event_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCF_CUSTOM_CONTAINER_EVENT", raising=False)
    monkeypatch.delenv("EVALEXECUTOR_JOB_JSON", raising=False)
    assert ep._parse_event() is None


def test_parse_event_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVALEXECUTOR_JOB_JSON", "not-json")
    assert ep._parse_event() is None


def _patch_sessionmaker(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """mock make_sessionmaker：async with make_sessionmaker()() as session → fake_session。"""
    fake_session = MagicMock()
    async_cm = MagicMock()
    async_cm.__aenter__ = AsyncMock(return_value=fake_session)
    async_cm.__aexit__ = AsyncMock(return_value=None)
    sm_obj = MagicMock(return_value=async_cm)
    mk = MagicMock(return_value=sm_obj)
    monkeypatch.setattr(ep, "make_sessionmaker", mk)
    return mk


async def test_run_single_job_marks_running_then_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sessionmaker(monkeypatch)
    job = MagicMock()
    job.job_id = "j1"
    job.input_object_key = "k"
    job.input_presigned_url = None

    monkeypatch.setattr(ep, "mark_running", AsyncMock(return_value=True))
    monkeypatch.setattr(ep, "get_job", AsyncMock(return_value=job))
    monkeypatch.setattr(ep, "load_input", AsyncMock())
    monkeypatch.setattr(ep, "run_job", AsyncMock())

    await ep._run_single_job({"job_id": "j1", "input_presigned_url": "http://u"})

    ep.mark_running.assert_awaited_once_with(ANY, "j1")
    ep.get_job.assert_awaited_once()
    ep.load_input.assert_awaited_once()
    ep.run_job.assert_awaited_once()


async def test_run_single_job_marks_failed_when_input_load_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sessionmaker(monkeypatch)
    job = MagicMock()
    job.job_id = "j1"
    job.input_object_key = "k"
    job.input_presigned_url = None

    monkeypatch.setattr(ep, "mark_running", AsyncMock(return_value=True))
    monkeypatch.setattr(ep, "get_job", AsyncMock(return_value=job))
    monkeypatch.setattr(ep, "load_input", AsyncMock(side_effect=RuntimeError("net")))
    monkeypatch.setattr(ep, "mark_failed", AsyncMock())
    monkeypatch.setattr(ep, "run_job", AsyncMock())

    await ep._run_single_job({"job_id": "j1", "input_presigned_url": "http://u"})

    ep.mark_failed.assert_awaited_once()
    ep.run_job.assert_not_awaited()


async def test_run_single_job_no_job_id_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sessionmaker(monkeypatch)
    monkeypatch.setattr(ep, "mark_running", AsyncMock())
    await ep._run_single_job({})
    ep.mark_running.assert_not_awaited()


def test_main_dispatches_worker_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """worker_enabled=true 且无 event → 调 _run_worker。"""
    monkeypatch.delenv("SCF_CUSTOM_CONTAINER_EVENT", raising=False)
    monkeypatch.delenv("EVALEXECUTOR_JOB_JSON", raising=False)

    settings = MagicMock()
    settings.worker_enabled = True
    settings.worker_concurrency = 1
    monkeypatch.setattr(ep, "get_settings", lambda: settings)

    called: dict[str, bool] = {"worker": False}

    async def _fake_worker() -> None:
        called["worker"] = True

    monkeypatch.setattr(ep, "_run_worker", _fake_worker)
    ep.main()
    assert called["worker"] is True
