"""runner 单元测试 — mock eval_packages 与 ResultSink，断言 flush 被显式调用。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_executor.executor import runner as runner_mod
from eval_executor.executor.runner import run_job
from eval_executor.models.db import EvalJob


@pytest.fixture
def sample_job() -> EvalJob:
    return EvalJob(
        job_id="job-1",
        api_key_id="key-1",
        project_id="project-1",
        org_id="org-1",
        status="running",
        input_kind="upload",
        scope="single",
        input_object_key="projects/project-1/eval/jobs/job-1/input.md",
        rule_set_id="coursework-quality",
        package_ref="courseware/courseware:production",
    )


@pytest.fixture
def sample_input(tmp_path: Path) -> Path:
    d = tmp_path / "contents"
    d.mkdir()
    (d / "lesson.md").write_text("# test")
    return d


async def test_run_job_evaluates_and_flushes(
    sample_job: EvalJob,
    sample_input: Path,
    fake_sessionmaker: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 eval_packages 与 ResultSink.flush 被调用，且 job 落 completed。"""
    run_workspace = MagicMock()
    run_workspace.root = sample_input / "ws"
    fake_report = MagicMock()
    fake_report.to_dict.return_value = {"dr": 0.95, "cpr": 0.9}

    fake_result = MagicMock()
    fake_result.run_id = "run-2024"
    fake_result.run_workspace = run_workspace
    fake_result.report = fake_report

    monkeypatch.setattr(runner_mod, "eval_packages", MagicMock(return_value=fake_result))
    monkeypatch.setattr(runner_mod, "_resolve_submit_token", AsyncMock(return_value="eval-token"))

    mock_sink_instance = MagicMock()
    mock_sink_instance.flush = MagicMock()
    monkeypatch.setattr(runner_mod, "ResultSink", MagicMock(return_value=mock_sink_instance))

    with patch.object(runner_mod, "mark_done", new=AsyncMock()) as mock_mark_done:
        await run_job(sample_job, sample_input)

    runner_mod.eval_packages.assert_called_once()
    mock_sink_instance.flush.assert_called_once()
    flush_kwargs = mock_sink_instance.flush.call_args.kwargs
    assert flush_kwargs.get("package_dir") is not None

    mock_mark_done.assert_awaited_once()
    _, kwargs = mock_mark_done.call_args
    assert kwargs["run_id"] == "run-2024"


async def test_run_job_marks_failed_on_exception(
    sample_job: EvalJob,
    sample_input: Path,
    fake_sessionmaker: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_mod, "eval_packages", MagicMock(side_effect=RuntimeError("boom")))

    with patch.object(runner_mod, "mark_failed", new=AsyncMock()) as mock_mark_failed:
        await run_job(sample_job, sample_input)

    mock_mark_failed.assert_awaited_once()
    _, kwargs = mock_mark_failed.call_args
    assert "message" in kwargs["error"]


def test_flush_result_recomputes_enabled_with_per_job_token(
    sample_job: EvalJob,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回归：部署未配 AGENT_EVAL_API_KEY 时 base_cfg.enabled=False；per-job token 覆盖
    api_key 后必须把派生字段 enabled 重算为 True。"""
    monkeypatch.delenv("AGENT_EVAL_API_KEY", raising=False)

    captured: dict[str, object] = {}

    def _capture_sink(cfg: object) -> MagicMock:
        captured["cfg"] = cfg
        inst = MagicMock()
        inst.flush = MagicMock(
            return_value=MagicMock(enabled=True, error=None, sent=1, queued=0, artifacts_uploaded=0)
        )
        return inst

    monkeypatch.setattr(runner_mod, "ResultSink", _capture_sink)

    result = MagicMock()
    result.run_workspace = None

    runner_mod._flush_result(result, tmp_path / "pkg", sample_job, "eval-token", tmp_path / "out")

    cfg = captured["cfg"]
    assert cfg.enabled is True  # type: ignore[union-attr]
    assert cfg.api_key == "eval-token"  # type: ignore[union-attr]
    assert cfg.project == sample_job.project_id  # type: ignore[union-attr]


def test_flush_result_skips_without_token(
    sample_job: EvalJob,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无凭据（token=None）→ 不构造 ResultSink，返回 None。"""
    monkeypatch.setattr(
        runner_mod, "ResultSink", MagicMock(side_effect=AssertionError("不应构造 sink"))
    )
    report = runner_mod._flush_result(MagicMock(), tmp_path / "pkg", sample_job, None, tmp_path)
    assert report is None


def _job(**overrides) -> EvalJob:
    """构造 EvalJob，默认带合法 package_ref（courseware 内置包）。"""
    base = dict(
        job_id="j",
        api_key_id="key-1",
        project_id="project-1",
        org_id="org-1",
        status="running",
        input_kind="upload",
        scope="single",
        input_object_key="projects/project-1/eval/jobs/j/input.md",
        rule_set_id="coursework-quality",
        package_ref="courseware/courseware:production",
    )
    base.update(overrides)
    return EvalJob(**base)


def test_resolve_rejects_legacy_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """无 package_ref 的历史 job 被拒绝（LegacyJobRejectedError），不再回退 _BUILTIN。"""
    from eval_executor.core.exceptions import LegacyJobRejectedError

    monkeypatch.delenv("AGENT_EVAL_REGISTRY_URL", raising=False)
    job = _job(package_ref=None)
    with pytest.raises(LegacyJobRejectedError):
        runner_mod._resolve_rule_set_path(job)


def test_resolve_builtin_package_by_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """package_ref 解析内置 courseware 包，rule_set_id 选定包内规则集文件。"""
    monkeypatch.delenv("AGENT_EVAL_REGISTRY_URL", raising=False)
    path = runner_mod._resolve_rule_set_path(_job(rule_set_id="coursework-quality"))
    assert path.endswith("coursework-quality.yaml")


def test_resolve_default_rule_set_from_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    """未指定 rule_set_id → 取包清单 default_rule_set（courseware=coursework-vision）。"""
    monkeypatch.delenv("AGENT_EVAL_REGISTRY_URL", raising=False)
    path = runner_mod._resolve_rule_set_path(_job(rule_set_id=""))
    assert path.endswith("coursework-vision.yaml")


def test_resolve_unknown_package_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """未知 package_ref（无远端配置）→ 解析失败抛错，而非跑错规则集。"""
    from agent_eval.core.exceptions import ScenarioPackageNotFoundError

    monkeypatch.delenv("AGENT_EVAL_REGISTRY_URL", raising=False)
    with pytest.raises(ScenarioPackageNotFoundError):
        runner_mod._resolve_rule_set_path(_job(package_ref="courseware/nope:1.0.0"))


async def test_run_job_marks_failed_on_legacy_job(
    sample_input: Path,
    fake_sessionmaker: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无 package_ref 的历史 job → mark_failed（含 legacy job rejected）。"""
    monkeypatch.delenv("AGENT_EVAL_REGISTRY_URL", raising=False)
    job = _job(job_id="legacy-job", package_ref=None)

    with patch.object(runner_mod, "mark_failed", new=AsyncMock()) as mock_mark_failed:
        await run_job(job, sample_input)

    mock_mark_failed.assert_awaited_once()
    _, kwargs = mock_mark_failed.call_args
    assert "legacy job rejected" in kwargs["error"]["message"]


def test_format_only_path_for_smoke() -> None:
    """纯格式冒烟规则集路径仍可取（CI 直接路径调用，不经 package_ref 解析）。"""
    from eval_executor.rules.registry import format_only_path

    assert format_only_path().name == "format_only.yaml"


# ── refresh_input_url：领取后重签输入下载 URL（B2b）─────────────────────


class _FakeResp:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


def _patch_http(
    monkeypatch: pytest.MonkeyPatch, resp: _FakeResp | None
) -> tuple[MagicMock, MagicMock]:
    """mock httpx.AsyncClient：返回 (client, async_context_manager)。

    runner.refresh_input_url 在函数体内 ``import httpx``，patch 全局 httpx 模块即可命中。
    resp=None 时构造 AsyncClient 即抛异常（模拟网络故障）。
    """
    import httpx

    client = MagicMock()
    client.get = AsyncMock(return_value=resp)  # type: ignore[arg-type]
    async_cm = MagicMock()
    async_cm.__aenter__ = AsyncMock(return_value=client)
    async_cm.__aexit__ = AsyncMock(return_value=None)
    if resp is None:
        monkeypatch.setattr(
            httpx, "AsyncClient", MagicMock(side_effect=RuntimeError("connect failed"))
        )
    else:
        monkeypatch.setattr(httpx, "AsyncClient", MagicMock(return_value=async_cm))
    return client, async_cm


def _patch_refresh_env(
    monkeypatch: pytest.MonkeyPatch,
    token: str | None = "eval-token",
    host: str = "http://web:9000",
) -> None:
    monkeypatch.setattr(runner_mod, "_resolve_submit_token", AsyncMock(return_value=token))
    cfg = MagicMock()
    cfg.host = host
    monkeypatch.setattr(runner_mod, "load_config", MagicMock(return_value=cfg))


async def test_refresh_input_url_returns_fresh_url(
    sample_job: EvalJob, monkeypatch: pytest.MonkeyPatch
) -> None:
    """200 + url → 返回新 URL，且以提交者 token 打 web 重签端点。"""
    _patch_refresh_env(monkeypatch)
    client, _ = _patch_http(monkeypatch, _FakeResp(200, {"url": "http://minio:9000/fresh?sig=1"}))

    url = await runner_mod.refresh_input_url(sample_job)

    assert url == "http://minio:9000/fresh?sig=1"
    client.get.assert_awaited_once()
    call_url = client.get.call_args.args[0]
    assert call_url == f"http://web:9000/api/v1/jobs/{sample_job.job_id}/input-url"
    assert client.get.call_args.kwargs["headers"] == {"Authorization": "Bearer eval-token"}


async def test_refresh_input_url_none_on_bad_status(
    sample_job: EvalJob, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非 200（如 404 / 403）→ None，调用方回退 job 上的原 URL。"""
    _patch_refresh_env(monkeypatch)
    _patch_http(monkeypatch, _FakeResp(404, {}))

    assert await runner_mod.refresh_input_url(sample_job) is None


async def test_refresh_input_url_none_on_empty_url(
    sample_job: EvalJob, monkeypatch: pytest.MonkeyPatch
) -> None:
    """200 但 payload 无 url / 非 str → None。"""
    _patch_refresh_env(monkeypatch)
    _patch_http(monkeypatch, _FakeResp(200, {"url": ""}))

    assert await runner_mod.refresh_input_url(sample_job) is None


async def test_refresh_input_url_none_on_network_error(
    sample_job: EvalJob, monkeypatch: pytest.MonkeyPatch
) -> None:
    """网络异常 → None（不向上抛，不阻断任务）。"""
    _patch_refresh_env(monkeypatch)
    _patch_http(monkeypatch, None)

    assert await runner_mod.refresh_input_url(sample_job) is None


async def test_refresh_input_url_none_without_token(
    sample_job: EvalJob, monkeypatch: pytest.MonkeyPatch
) -> None:
    """提交者 Key 不可用（token=None）→ None，且不发起 HTTP 请求。"""
    _patch_refresh_env(monkeypatch, token=None)
    client, _ = _patch_http(monkeypatch, _FakeResp(200, {"url": "http://x"}))

    assert await runner_mod.refresh_input_url(sample_job) is None
    client.get.assert_not_awaited()
