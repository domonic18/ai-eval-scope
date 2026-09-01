"""auth 组单测 — login/status/logout/register（requirement/04 F-C-AUTH）。

探测层用 httpx.MockTransport 注入（网络必须 mock）；.env 落盘经 find_env_path
monkeypatch 到 tmp_path 隔离。
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
import typer
from typer.testing import CliRunner

from agent_eval.cli.cmds.auth import auth_app, login_flow, logout_action, probe_identity

runner = CliRunner()

_WHOAMI = {
    "kind": "apikey",
    "key": {"id": "k1", "name": "cli-test", "scopes": ["ingest"]},
    "project": {"id": "p1", "name": "示例项目", "slug": "demo"},
    "org": {"id": "o1", "name": "示例团队", "slug": "demo-org"},
}


def _transport(status: int, payload: dict | None = None) -> httpx.MockTransport:
    return httpx.MockTransport(lambda req: httpx.Response(status, json=payload or {}))


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 .env 定位钉到 tmp_path（隔离真实仓库 .env）。

    预置空串而非删除：login_flow 会 ``os.environ.update`` 写入进程环境，
    预置才能让 monkeypatch 在 teardown 还原（空串在各读取点均按未配置处理）。
    """
    import agent_eval.cli._env_file as env_file_mod

    path = tmp_path / ".env"
    monkeypatch.setattr(env_file_mod, "find_env_path", lambda: path)
    for key in ("AGENT_EVAL_HOST", "AGENT_EVAL_API_KEY", "AGENT_EVAL_PROJECT"):
        monkeypatch.setenv(key, "")
    return path


# ── probe_identity ─────────────────────────────────────────────────────


def test_probe_parses_identity() -> None:
    identity = probe_identity("http://p", "eval-abc123", transport=_transport(200, _WHOAMI))
    assert identity is not None
    assert (identity.org_name, identity.project_slug, identity.key_name) == (
        "示例团队",
        "demo",
        "cli-test",
    )


def test_probe_invalid_key_raises() -> None:
    from agent_eval.cli.cmds.auth import ProbeError

    with pytest.raises(ProbeError) as ei:
        probe_identity("http://p", "eval-bad", transport=_transport(401))
    assert ei.value.kind == "invalid"


def test_probe_404_falls_back_legacy_and_returns_none() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("whoami"):
            return httpx.Response(404, json={"code": "NOT_FOUND"})
        return httpx.Response(200, json={"secrets": {}})

    identity = probe_identity("http://p", "eval-ok", transport=httpx.MockTransport(handler))
    assert identity is None  # 旧平台：有效但无身份
    assert calls[-1].endswith("/api/public/secrets")


# ── login_flow ─────────────────────────────────────────────────────────


def test_login_with_token_writes_env_and_receipt(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "agent_eval.cli.cmds.auth.probe_identity",
        lambda host, key, **_: probe_identity(host, key, transport=_transport(200, _WHOAMI)),
    )
    identity = login_flow(token="eval-abcdefgh1234", host="http://p")
    assert identity is not None and identity.project_slug == "demo"
    text = env_file.read_text(encoding="utf-8")
    assert "AGENT_EVAL_HOST=http://p" in text
    assert "AGENT_EVAL_API_KEY=eval-abcdefgh1234" in text
    assert "AGENT_EVAL_PROJECT=demo" in text
    assert os.environ["AGENT_EVAL_API_KEY"] == "eval-abcdefgh1234"  # 进程内即时生效


def test_login_invalid_token_from_param_exits_1(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "agent_eval.cli.cmds.auth.probe_identity",
        lambda host, key, **_: probe_identity(host, key, transport=_transport(401)),
    )
    with pytest.raises(typer.Exit) as ei:
        login_flow(token="eval-bad", host="http://p")
    assert ei.value.exit_code == 1
    assert not env_file.exists()  # 失败不落盘


def test_login_no_input_without_token_exits_2(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_EVAL_NO_INPUT", "1")
    with pytest.raises(typer.Exit) as ei:
        login_flow(host="http://p")
    assert ei.value.exit_code == 2


def test_login_unreachable_exits_1(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(
        "agent_eval.cli.cmds.auth.probe_identity",
        lambda host, key, **_: probe_identity(host, key, transport=httpx.MockTransport(boom)),
    )
    with pytest.raises(typer.Exit) as ei:
        login_flow(token="eval-x", host="http://p")
    assert ei.value.exit_code == 1


# ── status / logout / register ─────────────────────────────────────────


def test_status_not_logged_in_exits_1(
    env_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from agent_eval.cli.cmds.auth import status_action

    with pytest.raises(typer.Exit) as ei:
        status_action()
    assert ei.value.exit_code == 1
    assert "auth login" in capsys.readouterr().out


def test_status_ok_renders_identity(
    env_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from agent_eval.cli.cmds.auth import status_action

    monkeypatch.setenv("AGENT_EVAL_HOST", "http://p")
    monkeypatch.setenv("AGENT_EVAL_API_KEY", "eval-abcdefgh1234")
    monkeypatch.setattr(
        "agent_eval.cli.cmds.auth.probe_identity",
        lambda host, key, **_: probe_identity(host, key, transport=_transport(200, _WHOAMI)),
    )
    status_action()
    out = capsys.readouterr().out
    assert "示例团队" in out and "示例项目" in out
    assert "eval-abc…1234" in out  # Key 掩码（前 8 + 后 4）
    assert "eval-abcdefgh1234" not in out  # 完整 Key 不回显


def test_status_invalid_key_exits_1(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_eval.cli.cmds.auth import status_action

    monkeypatch.setenv("AGENT_EVAL_HOST", "http://p")
    monkeypatch.setenv("AGENT_EVAL_API_KEY", "eval-bad")
    monkeypatch.setattr(
        "agent_eval.cli.cmds.auth.probe_identity",
        lambda host, key, **_: probe_identity(host, key, transport=_transport(401)),
    )
    with pytest.raises(typer.Exit) as ei:
        status_action()
    assert ei.value.exit_code == 1


def test_logout_clears_keys_preserving_others(env_file: Path) -> None:
    env_file.write_text(
        "AGENT_EVAL_HOST=http://p\nAGENT_EVAL_API_KEY=eval-x\nKEEP=1\n", encoding="utf-8"
    )
    os.environ["AGENT_EVAL_API_KEY"] = "eval-x"
    logout_action()
    assert env_file.read_text(encoding="utf-8") == "KEEP=1\n"
    assert "AGENT_EVAL_API_KEY" not in os.environ


def test_register_opens_platform_page(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from agent_eval.cli.cmds.auth import register_action

    opened: list[str] = []
    monkeypatch.setattr("agent_eval.cli.cmds.open_url.open_url", opened.append)
    register_action(host="http://p")
    assert opened == ["http://p/register"]
    assert "auth login" in capsys.readouterr().out


# ── 命令绑定 ───────────────────────────────────────────────────────────


def test_cli_login_token_flag(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agent_eval.cli.cmds.auth.probe_identity",
        lambda host, key, **_: probe_identity(host, key, transport=_transport(200, _WHOAMI)),
    )
    result = runner.invoke(
        auth_app, ["login", "--token", "eval-abcdefgh1234", "--host", "http://p"]
    )
    assert result.exit_code == 0
    assert "AGENT_EVAL_API_KEY=eval-abcdefgh1234" in env_file.read_text(encoding="utf-8")
