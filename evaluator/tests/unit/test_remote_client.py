"""HttpRemotePackageClient 单元测试（S2-B）—— mock httpx，禁止联网。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_eval.packages import get_remote_client
from agent_eval.packages.remote_client import HttpRemotePackageClient


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        return self._payload


def _pkg_payload(version: str = "1.0.0", labels: list[str] | None = None) -> dict[str, Any]:
    return {
        "package": {
            "version": version,
            "labels": labels or ["production"],
            "content": {
                "manifest": {
                    "id": "quality",
                    "scenario": "courseware",
                    "version": version,
                    "name": "课件质量",
                },
                "files": {
                    "rules/quality.yaml": "rules: []",
                    "prompts/info_accuracy.yaml": "template_id: info_accuracy",
                },
            },
        }
    }


def test_get_remote_client_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_EVAL_REGISTRY_URL", raising=False)
    assert get_remote_client() is None

    monkeypatch.setenv("AGENT_EVAL_REGISTRY_URL", "http://localhost:9000/")
    client = get_remote_client()
    assert isinstance(client, HttpRemotePackageClient)
    assert client.base_url == "http://localhost:9000"  # 末尾斜杠被去除


def test_fetch_by_version(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_get(url, params=None, timeout=None):  # noqa: ANN001
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse(200, _pkg_payload("1.2.0"))

    monkeypatch.setattr("agent_eval.packages.remote_client.httpx.get", fake_get)
    client = HttpRemotePackageClient("http://reg")
    remote = client.fetch("courseware/quality:1.2.0")

    assert captured["url"].endswith("/api/v1/scenarios/courseware/packages/quality")
    assert captured["params"] == {"version": "1.2.0"}
    assert remote.manifest.id == "quality"
    assert remote.manifest.version == "1.2.0"
    assert b"rules: []" == remote.files["rules/quality.yaml"]


def test_fetch_by_label(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_get(url, params=None, timeout=None):  # noqa: ANN001
        captured["params"] = params
        return _FakeResponse(200, _pkg_payload("1.0.0", ["production"]))

    monkeypatch.setattr("agent_eval.packages.remote_client.httpx.get", fake_get)
    HttpRemotePackageClient("http://reg").fetch("courseware/quality:production")
    assert captured["params"] == {"label": "production"}


def test_fetch_default_latest_no_param(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_get(url, params=None, timeout=None):  # noqa: ANN001
        captured["params"] = params
        return _FakeResponse(200, _pkg_payload("1.0.0"))

    monkeypatch.setattr("agent_eval.packages.remote_client.httpx.get", fake_get)
    HttpRemotePackageClient("http://reg").fetch("courseware/quality")
    assert captured["params"] == {}


def test_fetch_404_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agent_eval.packages.remote_client.httpx.get",
        lambda *a, **k: _FakeResponse(404, text="not found"),
    )
    with pytest.raises(FileNotFoundError):
        HttpRemotePackageClient("http://reg").fetch("courseware/missing:1.0.0")


def test_fetch_missing_manifest_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agent_eval.packages.remote_client.httpx.get",
        lambda *a, **k: _FakeResponse(200, {"package": {"content": {"files": {}}}}),
    )
    with pytest.raises(RuntimeError, match="缺少 manifest"):
        HttpRemotePackageClient("http://reg").fetch("courseware/quality")


def test_cli_pull_with_remote_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--remote <base_url> 直接构造 HTTP 客户端（mock httpx）→ install 到本地缓存。"""
    from typer.testing import CliRunner

    from agent_eval.cli.cmds.scenario import scenario_app

    monkeypatch.setenv("AGENT_EVAL_PACKAGE_DIR", str(tmp_path / "cache"))

    def fake_get(url, params=None, timeout=None):  # noqa: ANN001
        return _FakeResponse(200, _pkg_payload("1.0.0"))

    monkeypatch.setattr("agent_eval.packages.remote_client.httpx.get", fake_get)

    runner = CliRunner()
    result = runner.invoke(
        scenario_app, ["pull", "courseware/quality:1.0.0", "--remote", "http://reg"]
    )
    assert result.exit_code == 0, result.output
    assert "已拉取" in result.output
    installed = tmp_path / "cache" / "courseware" / "quality" / "1.0.0"
    assert (installed / "agent_eval.yaml").exists()
    assert (installed / "rules" / "quality.yaml").exists()
