"""鉴权架构测试（arch/03 §4.0）：CredentialStore / SUTSession / SessionStore / AuthProvider。"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from agent_eval.core.exceptions import SUTAuthError, SUTChannelError
from agent_eval.execution.auth.credentials import CredentialStore, preflight_sut_credentials
from agent_eval.execution.auth.provider import AuthProvider
from agent_eval.execution.auth.session import SessionStore, SUTSession
from agent_eval.execution.registry import (
    AuthConfig,
    AuthExtractConfig,
    AuthLoginConfig,
    SUTSystemConfig,
)

# api_login 提取规则（token 路径属系统配置，须显式声明；形态同 arch/03 §4.0.3 示例）
EXTRACT = AuthExtractConfig(token_path="data.access_token", expires_in_path="data.expires_in")


def _sut(auth: AuthConfig) -> SUTSystemConfig:
    return SUTSystemConfig(
        name="courseware-agent",
        channel="agent_protocol",
        base_url="https://sut.example.com",
        auth=auth,
    )


def _factory(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ─── CredentialStore ───


def test_credential_store_env_naming() -> None:
    store = CredentialStore(
        env={
            "AGENT_EVAL_SUT__COURSEWARE_AGENT__TOKEN": "tk-1",
            "AGENT_EVAL_SUT__COURSEWARE_AGENT__USERNAME": "u",
        }
    )
    assert store.get("COURSEWARE_AGENT", "token") == "tk-1"
    assert store.require("COURSEWARE_AGENT", "username") == "u"
    assert store.get("COURSEWARE_AGENT", "password") is None
    with pytest.raises(SUTAuthError, match="AGENT_EVAL_SUT__COURSEWARE_AGENT__PASSWORD"):
        store.require("COURSEWARE_AGENT", "PASSWORD")


# ─── SUTSession ───


def test_session_mount_headers_forms() -> None:
    bearer = SUTSession(sut_name="s", token="tk")
    assert bearer.mount_headers() == {"Authorization": "Bearer tk"}

    custom_header = SUTSession(sut_name="s", token="tk", token_type="header:X-Api-Key")
    assert custom_header.mount_headers() == {"X-Api-Key": "tk"}

    cookie = SUTSession(sut_name="s", token="tk", token_type="cookie")
    assert cookie.mount_headers() == {}  # cookie 由共享 client jar 承载

    none_token = SUTSession(sut_name="s", token=None)
    assert none_token.mount_headers() == {}


def test_session_expiry() -> None:
    expired = SUTSession(sut_name="s", token="tk", expires_at=time.time() - 1)
    assert expired.is_expired()
    future = SUTSession(sut_name="s", token="tk", expires_at=time.time() + 3600)
    assert not future.is_expired()
    assert not SUTSession(sut_name="s", token="tk").is_expired()  # 无过期时间


def test_session_store_roundtrip_and_cleanup(tmp_path) -> None:
    store = SessionStore(tmp_path)
    session = SUTSession(sut_name="sys-a", token="tk", expires_at=time.time() + 600)
    path = store.save(session)
    assert path.exists()
    loaded = store.load("sys-a")
    assert loaded is not None and loaded.token == "tk"

    store.invalidate("sys-a")
    assert store.load("sys-a") is None

    # 过期会话读取时自动清理
    store.save(SUTSession(sut_name="sys-b", token="tk", expires_at=time.time() - 1))
    assert store.load("sys-b") is None
    assert not (tmp_path / "sys-b.json").exists()


def test_session_store_sanitizes_unsafe_names(tmp_path) -> None:
    store = SessionStore(tmp_path)
    store.save(SUTSession(sut_name="../../etc/passwd", token="tk"))
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert ".." not in files[0].name


# ─── AuthProvider ───


def test_provider_static_token() -> None:
    provider = AuthProvider(
        _sut(AuthConfig(type="static_token", credential_ref="SYS")),
        credential_store=CredentialStore(env={"AGENT_EVAL_SUT__SYS__TOKEN": "long-term"}),
    )
    session = asyncio.run(provider.get_session())
    assert session.mount_headers() == {"Authorization": "Bearer long-term"}


def test_provider_api_login_flow() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/login"
        assert b'"username": "u1"' in request.content
        return httpx.Response(200, json={"data": {"access_token": "fresh-tk", "expires_in": 1800}})

    provider = AuthProvider(
        _sut(
            AuthConfig(
                type="api_login",
                credential_ref="SYS",
                login=AuthLoginConfig(
                    method="POST",
                    path="/api/login",
                    body_template='{"username": "{{ username }}", "password": "{{ password }}"}',
                ),
                extract=EXTRACT,
            )
        ),
        credential_store=CredentialStore(
            env={"AGENT_EVAL_SUT__SYS__USERNAME": "u1", "AGENT_EVAL_SUT__SYS__PASSWORD": "p1"}
        ),
        http_client_factory=lambda: _factory(handler),
    )
    session = asyncio.run(provider.get_session())
    assert session.token == "fresh-tk"
    assert session.mount_headers() == {"Authorization": "Bearer fresh-tk"}
    assert not session.is_expired()


def test_provider_api_login_missing_token_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unrelated": True})

    provider = AuthProvider(
        _sut(
            AuthConfig(
                type="api_login",
                credential_ref="SYS",
                login=AuthLoginConfig(path="/api/login"),
            )
        ),
        credential_store=CredentialStore(
            env={"AGENT_EVAL_SUT__SYS__USERNAME": "u", "AGENT_EVAL_SUT__SYS__PASSWORD": "p"}
        ),
        http_client_factory=lambda: _factory(handler),
    )
    with pytest.raises(SUTChannelError, match="未提取到 token"):
        asyncio.run(provider.get_session())


def test_provider_login_http_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "bad credentials"})

    provider = AuthProvider(
        _sut(
            AuthConfig(
                type="api_login",
                credential_ref="SYS",
                login=AuthLoginConfig(path="/api/login"),
                extract=AuthExtractConfig(token_path="data.access_token"),
            )
        ),
        credential_store=CredentialStore(
            env={"AGENT_EVAL_SUT__SYS__USERNAME": "u", "AGENT_EVAL_SUT__SYS__PASSWORD": "p"}
        ),
        http_client_factory=lambda: _factory(handler),
    )
    with pytest.raises(SUTAuthError, match="登录失败"):
        asyncio.run(provider.get_session())


def test_provider_reuses_disk_session_and_force_relogin(tmp_path) -> None:
    login_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        login_count["n"] += 1
        return httpx.Response(200, json={"data": {"access_token": f"tk-{login_count['n']}"}})

    provider = AuthProvider(
        _sut(
            AuthConfig(
                type="api_login",
                credential_ref="SYS",
                login=AuthLoginConfig(path="/api/login"),
                extract=AuthExtractConfig(token_path="data.access_token"),
            )
        ),
        credential_store=CredentialStore(
            env={"AGENT_EVAL_SUT__SYS__USERNAME": "u", "AGENT_EVAL_SUT__SYS__PASSWORD": "p"}
        ),
        session_store=SessionStore(tmp_path),
        http_client_factory=lambda: _factory(handler),
    )
    first = asyncio.run(provider.get_session())
    second = asyncio.run(provider.get_session())  # 落盘复用，不重复登录
    assert second.token == first.token == "tk-1"
    assert login_count["n"] == 1

    forced = asyncio.run(provider.get_session(force=True))
    assert forced.token == "tk-2"
    assert login_count["n"] == 2


def test_provider_auto_relogin_rate_limit() -> None:
    provider = AuthProvider(
        _sut(AuthConfig(type="static_token", credential_ref="SYS", relogin_window_s=1800))
    )
    assert provider.auto_relogin_allowed()
    provider.mark_auto_relogin()
    assert not provider.auto_relogin_allowed()  # 30 分钟窗口内拒绝再次自动重登


def test_session_store_default_in_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """W5：缺省会话目录迁至 workspace/sut_sessions（旧目录自动搬迁）。"""
    import agent_eval.execution.auth.session as session_mod

    workspace = tmp_path / "ws"
    workspace.mkdir()
    legacy = tmp_path / "home" / ".agent_eval" / "sut_sessions"
    legacy.mkdir(parents=True)
    (legacy / "sys-a.json").write_text("{}", encoding="utf-8")

    from agent_eval.config.paths import ProjectPaths

    monkeypatch.setattr(session_mod, "LEGACY_SESSION_DIR", legacy)  # 导入期常量，patch 模块属性
    monkeypatch.setattr(ProjectPaths, "default_workspace", workspace)  # 覆盖 property
    monkeypatch.delenv("AGENT_EVAL_SUT_SESSION_DIR", raising=False)

    store = session_mod.SessionStore()
    assert store.base_dir == workspace / "sut_sessions"
    assert (workspace / "sut_sessions" / "sys-a.json").exists()  # 旧会话已搬迁
    assert not (legacy / "sys-a.json").exists()


# ── 执行前凭证预检（fail fast，不进 Agent 循环烧轮次）───────────────────────

_LOGIN = AuthLoginConfig(
    method="POST",
    path="/api/login",
    body_template='{"u": "{{ username }}", "p": "{{ password }}"}',
)


def test_preflight_passes_when_credentials_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_EVAL_SUT__AGENT_SERVER__USERNAME", "u")
    monkeypatch.setenv("AGENT_EVAL_SUT__AGENT_SERVER__PASSWORD", "p")
    sut = _sut(AuthConfig(type="api_login", credential_ref="AGENT_SERVER", login=_LOGIN))
    preflight_sut_credentials(sut)  # 不抛即通过


def test_preflight_missing_credential_raises_with_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_EVAL_SUT__AGENT_SERVER__USERNAME", raising=False)
    sut = _sut(AuthConfig(type="api_login", credential_ref="AGENT_SERVER", login=_LOGIN))
    with pytest.raises(SUTAuthError) as ei:
        preflight_sut_credentials(sut)
    assert "凭证未配置" in str(ei.value)
    assert "secrets set AGENT_SERVER." in str(ei.value)  # 可操作引导（缺哪个字段报哪个）


def test_preflight_noop_for_auth_none_and_flags_missing_ref() -> None:
    preflight_sut_credentials(_sut(AuthConfig(type="none")))  # 无凭证要求 → no-op
    with pytest.raises(SUTAuthError, match="credential_ref"):
        preflight_sut_credentials(_sut(AuthConfig(type="static_token", credential_ref=None)))


def test_preflight_fields_declared_by_template_not_enumerated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 通用 KV（06 §4.7）：模板写 {{ account }}/{{ api_key }} 就要求这两个字段——
    # username/password 未录也不报错（字段集由配置声明，非代码枚举）
    login = AuthLoginConfig(
        method="POST",
        path="/api/login",
        body_template='{"a": "{{ account }}", "k": "{{ api_key }}"}',
    )
    sut = _sut(AuthConfig(type="api_login", credential_ref="SYS", login=login))
    from agent_eval.execution.auth.credentials import required_credential_fields

    assert sorted(required_credential_fields(sut)) == ["ACCOUNT", "API_KEY"]
    monkeypatch.setenv("AGENT_EVAL_SUT__SYS__ACCOUNT", "a")
    monkeypatch.setenv("AGENT_EVAL_SUT__SYS__API_KEY", "k")
    preflight_sut_credentials(sut)  # 不抛：所需字段齐（username/password 无关）


def test_provider_login_custom_template_fields() -> None:
    # 模板变量即凭证键名：{{ account }}/{{ pwd }} 取 ref.account / ref.pwd（通用 KV）
    def handler(request: httpx.Request) -> httpx.Response:
        assert b'"account": "acc-1"' in request.content
        assert b'"pwd": "pw-1"' in request.content
        return httpx.Response(200, json={"data": {"access_token": "tk-custom", "expires_in": 600}})

    provider = AuthProvider(
        _sut(
            AuthConfig(
                type="api_login",
                credential_ref="SYS",
                login=AuthLoginConfig(
                    method="POST",
                    path="/api/login",
                    body_template='{"account": "{{ account }}", "pwd": "{{ pwd }}"}',
                ),
                extract=EXTRACT,
            )
        ),
        credential_store=CredentialStore(
            env={"AGENT_EVAL_SUT__SYS__ACCOUNT": "acc-1", "AGENT_EVAL_SUT__SYS__PWD": "pw-1"}
        ),
        http_client_factory=lambda: _factory(handler),
    )
    session = asyncio.run(provider.get_session())
    assert session.token == "tk-custom"
