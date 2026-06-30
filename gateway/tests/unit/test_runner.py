"""runner 单元测试 — mock eval_packages 与 ResultSink，断言 flush 被显式调用。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_gateway.models.db import Job
from eval_gateway.worker import runner as runner_mod
from eval_gateway.worker.runner import run_job


@pytest.fixture
def sample_job(tmp_path: Path, mock_settings: MagicMock) -> Job:
    input_dir = tmp_path / "contents"
    input_dir.mkdir()
    (input_dir / "lesson.md").write_text("# test")
    mock_settings.upload_dir = tmp_path / "uploads"
    mock_settings.web_base_url = "http://localhost:9000"

    return Job(
        job_id="job-1",
        project_id="project-1",
        org_id="org-1",
        status="running",
        input_kind="upload",
        scope="single",
        input_ref=str(input_dir),
        rule_set_id="format-only",
    )


async def test_run_job_evaluates_and_flushes(
    sample_job: Job,
    tmp_path: Path,
    fake_sessionmaker: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 eval_packages 与 ResultSink.flush 被调用，且 job 落 completed。"""
    run_workspace = MagicMock()
    run_workspace.root = tmp_path / "workspace"
    fake_report = MagicMock()
    fake_report.to_dict.return_value = {"dr": 0.95, "cpr": 0.9}

    fake_result = MagicMock()
    fake_result.run_id = "run-2024"
    fake_result.run_workspace = run_workspace
    fake_result.report = fake_report

    monkeypatch.setattr(runner_mod, "eval_packages", MagicMock(return_value=fake_result))

    mock_sink_instance = MagicMock()
    mock_sink_instance.flush = MagicMock()
    monkeypatch.setattr(runner_mod, "ResultSink", MagicMock(return_value=mock_sink_instance))
    monkeypatch.setattr(runner_mod, "load_config", MagicMock())

    with patch.object(runner_mod, "mark_done", new=AsyncMock()) as mock_mark_done:
        await run_job(sample_job)

    # eval_packages 被调用
    runner_mod.eval_packages.assert_called_once()

    # ResultSink.flush 被显式调用，且传了 package_dir（源文件制品上传）
    mock_sink_instance.flush.assert_called_once()
    flush_kwargs = mock_sink_instance.flush.call_args.kwargs
    assert flush_kwargs.get("package_dir") is not None

    # mark_done 被调用，带 run_id
    mock_mark_done.assert_awaited_once()
    _, kwargs = mock_mark_done.call_args
    assert kwargs["run_id"] == "run-2024"


async def test_run_job_marks_failed_on_exception(
    sample_job: Job,
    fake_sessionmaker: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_mod, "eval_packages", MagicMock(side_effect=RuntimeError("boom")))

    with patch.object(runner_mod, "mark_failed", new=AsyncMock()) as mock_mark_failed:
        await run_job(sample_job)

    mock_mark_failed.assert_awaited_once()
    _, kwargs = mock_mark_failed.call_args
    assert "message" in kwargs["error"]
