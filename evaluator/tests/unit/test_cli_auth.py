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
def platform_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """密钥区 platform.json 与 .env 残留检测均钉到 tmp_path（隔离真实文件）。

    预置空串而非删除：login_flow 会 ``os.environ.update`` 写入进程环境，
    预置才能让 monkeypatch 在 teardown 还原（空串在各读取点均按未配置处理）。
    """
    import agent_eval.cli._env_file as env_file_mod

    platform = tmp_path / "platform.json"
    monkeypatch.setenv("AGENT_EVAL_PLATFORM_CONFIG", str(platform))
    monkeypatch.setattr(env_file_mod, "find_env_path", lambda: tmp_path / ".env")
    for key in ("AGENT_EVAL_HOST", "AGENT_EVAL_API_KEY", "AGENT_EVAL_PROJECT"):
        monkeypatch.setenv(key, "")
    return platform


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


def test_login_with_token_writes_platform_file(
    platform_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "agent_eval.cli.cmds.auth.probe_identity",
        lambda host, key, **_: probe_identity(host, key, transport=_transport(200, _WHOAMI)),
    )
    identity = login_flow(token="eval-abcdefgh1234", host="http://p")
    assert identity is not None and identity.project_slug == "demo"
    from agent_eval.config.platform_file import load_platform_file

    cfg = load_platform_file(platform_env)
    assert cfg is not None
    assert (cfg.host, cfg.api_key, cfg.project) == ("http://p", "eval-abcdefgh1234", "demo")
    assert os.environ["AGENT_EVAL_API_KEY"] == "eval-abcdefgh1234"  # 进程内即时生效


def test_login_warns_stale_env_entries(
    platform_env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """.env 残留平台配置：仅提示（env 优先将覆盖本次登录），不代为删改。"""
    (tmp_path / ".env").write_text("AGENT_EVAL_API_KEY=eval-old\n", encoding="utf-8")
    monkeypatch.setattr(
        "agent_eval.cli.cmds.auth.probe_identity",
        lambda host, key, **_: probe_identity(host, key, transport=_transport(200, _WHOAMI)),
    )
    login_flow(token="eval-abcdefgh1234", host="http://p")
    out = capsys.readouterr().out
    assert ".env 中仍有 1 项平台配置" in out and "AGENT_EVAL_API_KEY" in out
    assert (tmp_path / ".env").read_text(
        encoding="utf-8"
    ) == "AGENT_EVAL_API_KEY=eval-old\n"  # 未被改动


def test_login_invalid_token_from_param_exits_1(
    platform_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "agent_eval.cli.cmds.auth.probe_identity",
        lambda host, key, **_: probe_identity(host, key, transport=_transport(401)),
    )
    with pytest.raises(typer.Exit) as ei:
        login_flow(token="eval-bad", host="http://p")
    assert ei.value.exit_code == 1
    assert not platform_env.exists()  # 失败不落盘


def test_login_no_input_without_token_exits_2(
    platform_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_EVAL_NO_INPUT", "1")
    with pytest.raises(typer.Exit) as ei:
        login_flow(host="http://p")
    assert ei.value.exit_code == 2


def test_login_unreachable_exits_1(platform_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    platform_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from agent_eval.cli.cmds.auth import status_action

    with pytest.raises(typer.Exit) as ei:
        status_action()
    assert ei.value.exit_code == 1
    assert "auth login" in capsys.readouterr().out


def test_status_ok_renders_identity_and_storage(
    platform_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from agent_eval.cli.cmds.auth import status_action
    from agent_eval.config.platform_file import (
        PlatformFileConfig,
        save_platform_file,
    )

    save_platform_file(
        PlatformFileConfig(host="http://p", api_key="eval-abcdefgh1234", project="demo"),
        path=platform_env,
    )
    monkeypatch.setattr(
        "agent_eval.cli.cmds.auth.probe_identity",
        lambda host, key, **_: probe_identity(host, key, transport=_transport(200, _WHOAMI)),
    )
    status_action()  # 内部 apply_platform_env 从密钥区注入（env 空串补位）
    out = capsys.readouterr().out
    assert "示例团队" in out and "示例项目" in out
    assert "存储" in out and "platform.json" in out  # 来源 = 密钥区文件（rich 折行，断文件名）
    assert "eval-abc…1234" in out  # Key 掩码（前 8 + 后 4）
    assert "eval-abcdefgh1234" not in out  # 完整 Key 不回显


def test_status_invalid_key_exits_1(platform_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_logout_removes_platform_file_and_env(
    platform_env: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    from agent_eval.config.platform_file import PlatformFileConfig, save_platform_file

    save_platform_file(
        PlatformFileConfig(host="http://p", api_key="eval-x", project="demo"), path=platform_env
    )
    (tmp_path / ".env").write_text("AGENT_EVAL_API_KEY=eval-x\nKEEP=1\n", encoding="utf-8")
    os.environ["AGENT_EVAL_API_KEY"] = "eval-x"
    logout_action()
    assert not platform_env.exists()  # 密钥区文件已删
    assert "AGENT_EVAL_API_KEY" not in os.environ
    out = capsys.readouterr().out
    assert "已清除" in out
    assert ".env 中仍有 1 项" in out  # .env 不代删，仅提示残留
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "AGENT_EVAL_API_KEY=eval-x\nKEEP=1\n"


def test_logout_without_file_hints(platform_env: Path, capsys: pytest.CaptureFixture) -> None:
    logout_action()
    assert "未配置平台凭证" in capsys.readouterr().out


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


def test_cli_login_token_flag(platform_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agent_eval.cli.cmds.auth.probe_identity",
        lambda host, key, **_: probe_identity(host, key, transport=_transport(200, _WHOAMI)),
    )
    result = runner.invoke(
        auth_app, ["login", "--token", "eval-abcdefgh1234", "--host", "http://p"]
    )
    assert result.exit_code == 0
    from agent_eval.config.platform_file import load_platform_file

    cfg = load_platform_file(platform_env)
    assert cfg is not None and cfg.api_key == "eval-abcdefgh1234"


# ── 空输入与非 2xx 归类（实测反馈：空粘贴 → 畸形 Bearer 头 → 400 traceback）──


def test_probe_empty_key_raises_invalid() -> None:
    from agent_eval.cli.cmds.auth import ProbeError

    with pytest.raises(ProbeError) as ei:
        probe_identity("http://p", "")
    assert ei.value.kind == "invalid"
    assert "Key 为空" in str(ei.value)


@pytest.mark.parametrize("status", [400, 403, 429, 500])
def test_probe_non_2xx_classified_no_traceback(status: int) -> None:
    """任何非 2xx（含空 Key 触发的 400）都必须归类为 ProbeError，不裸抛 httpx。"""
    from agent_eval.cli.cmds.auth import ProbeError

    with pytest.raises(ProbeError) as ei:
        probe_identity("http://p", "eval-x", transport=_transport(status))
    assert ei.value.kind == "server"
    assert str(status) in str(ei.value)


def test_probe_fallback_bad_status_not_misreported_unreachable() -> None:
    """旧平台回退分支的 4xx/5xx 归类为 server，不再误报「平台不可达」。"""
    from agent_eval.cli.cmds.auth import ProbeError

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("whoami"):
            return httpx.Response(404, json={})
        return httpx.Response(400, json={})  # 网关拒绝（如畸形头/限流）

    with pytest.raises(ProbeError) as ei:
        probe_identity("http://p", "eval-x", transport=httpx.MockTransport(handler))
    assert ei.value.kind == "server"


def test_login_empty_paste_cancels_without_probe(
    platform_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """浏览器通道粘贴处直接回车 = 取消：不探测、不写 .env、不抛异常。"""
    from agent_eval.cli.console import prompts

    probed: list[str] = []
    monkeypatch.setattr("agent_eval.cli.cmds.auth.probe_identity", lambda *a: probed.append("x"))
    monkeypatch.setattr(
        prompts, "select", lambda label, options, **kw: "打开平台页面创建（浏览器）"
    )
    monkeypatch.setattr(prompts, "ask", lambda label, **kw: "")
    monkeypatch.setattr("agent_eval.cli.cmds.open_url.open_url", lambda url: None)

    assert login_flow(host="http://p") is None
    assert probed == []
    assert not platform_env.exists()
    assert "已取消" in capsys.readouterr().out


def test_login_retry_empty_paste_cancels(
    platform_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """无效 Key 重试粘贴处直接回车 = 取消（不再发起第三次探测）。"""
    from agent_eval.cli.console import prompts

    asks = iter(["eval-bad", ""])  # 首次粘贴 → 401 后重试回车取消
    monkeypatch.setattr(prompts, "select", lambda label, options, **kw: "直接粘贴已有 Key")
    monkeypatch.setattr(prompts, "ask", lambda label, **kw: next(asks))
    monkeypatch.setattr(
        "agent_eval.cli.cmds.auth.probe_identity",
        lambda host, key, **_: probe_identity(host, key, transport=_transport(401)),
    )

    assert login_flow(host="http://p") is None
    assert not platform_env.exists()
    assert "已取消" in capsys.readouterr().out
