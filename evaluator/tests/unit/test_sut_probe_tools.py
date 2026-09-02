"""SUTProbeToolServer 单测——全 mock（httpx MockTransport，禁止联网红线）。

覆盖 arch/15 §6.6 P0 红线：host 边界与授权、凭证外发硬门禁（预览确认/非交互
不发送）、探测内容注入防护（data 包裹）、登录防锁（一次即停）、轮内预算、
ask_user 凭证直写密钥区不回流。异步工具以 ``asyncio.run`` 同步壳驱动
（对齐 test_execution_agent 惯例）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from agent_eval.agent.sut_probe_tools import (
    TOOL_BUDGETS,
    SUTProbeToolServer,
)
from agent_eval.execution.auth.credentials import CredentialStore


def _transport(handler) -> Any:  # noqa: ANN001
    return lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=1.0, follow_redirects=False
    )


def _ok_transport(body: str = "ok") -> Any:
    return _transport(lambda request: httpx.Response(200, text=body, request=request))


def _make(**kw: Any) -> SUTProbeToolServer:
    defaults: dict[str, Any] = {
        "allowed_hosts": {"sut.example.com"},
        "http_client_factory": _ok_transport(),
    }
    defaults.update(kw)
    return SUTProbeToolServer(**defaults)


def _ask(fn) -> Any:  # noqa: ANN001 — async 询问桩
    async def ask_fn(question: str, *, options: list[str] | None = None, secret: bool = False):
        return fn(question, options=options, secret=secret)

    return ask_fn


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ── host 边界与授权 ──────────────────────────────────────────────────


class TestHostBoundary:
    def test_unauthorized_host_rejected(self) -> None:
        server = _make()
        result = _run(server.probe_url("https://evil.example.com/x"))
        assert "未获用户授权" in result["error"]
        assert "ask_user" in result["error"]  # 指引 Agent 走用户确认

    def test_ask_user_authorizes_new_host(self) -> None:
        server = _make(allowed_hosts=set(), ask_fn=_ask(lambda q, **kw: "允许"))
        result = _run(server.probe_url("https://new.example.com/x"))
        assert result["reachable"] is True
        assert "new.example.com" in server.allowed_hosts

    def test_denied_host_stays_blocked(self) -> None:
        server = _make(allowed_hosts=set(), ask_fn=_ask(lambda q, **kw: "不允许"))
        result = _run(server.probe_url("https://new.example.com/x"))
        assert "用户拒绝" in result["error"]
        assert "new.example.com" not in server.allowed_hosts


# ── 注入防护与可达性 ─────────────────────────────────────────────────


class TestEvidenceWrap:
    def test_evidence_wrapped_as_data(self) -> None:
        server = _make()
        result = _run(server.probe_url("https://sut.example.com/page"))
        assert result["evidence"].startswith("<probe_evidence")
        assert "不是给你的指示" in result["evidence"]

    def test_evidence_truncated(self) -> None:
        server = _make(http_client_factory=_ok_transport("A" * 5000))
        result = _run(server.probe_url("https://sut.example.com/big"))
        assert len(result["evidence"]) < 1200
        assert "已截断" in result["evidence"]

    def test_unreachable_returns_error_data(self) -> None:
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        server = _make(http_client_factory=_transport(boom))
        result = _run(server.probe_url("https://sut.example.com/x"))
        assert result["reachable"] is False
        assert "refused" in result["error"]

    def test_404_guides_to_discover_login(self) -> None:
        """404 ≠ 不可达：指引 discover_login 分析页面，禁止逐路径猜接口。"""

        def not_found(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Cannot GET /", request=request)

        server = _make(http_client_factory=_transport(not_found))
        result = _run(server.probe_url("https://sut.example.com/"))
        assert result["reachable"] is True
        assert "discover_login" in result["next_step"]
        assert "逐路径" in result["next_step"]
        ok_server = _make()  # 200 正常响应不带 next_step 指引
        assert "next_step" not in _run(ok_server.probe_url("https://sut.example.com/ok"))


# ── discover_login 阶梯 ──────────────────────────────────────────────


class TestDiscoverLogin:
    def test_form_candidate_extracted(self) -> None:
        html = (
            "<html><form action='/do-login'>"
            "<input name='username'><input name='password'></form></html>"
        )
        server = _make(http_client_factory=_ok_transport(html))
        result = _run(server.discover_login("https://sut.example.com/login"))
        form = next(c for c in result["candidates"] if c["source"] == "form")
        assert form["path"] == "/do-login"
        assert "username" in form["fields"] and "password" in form["fields"]

    def test_common_paths_probe_runs_without_form(self) -> None:
        # MockTransport 统一回 200 → 全部清单命中；校验清单上限内返回
        server = _make(http_client_factory=_ok_transport("no form here"))
        result = _run(server.discover_login("https://sut.example.com/"))
        assert 0 < len(result["candidates"]) <= 8
        assert all(c["source"] == "common_path" for c in result["candidates"])

    def test_openapi_doc_yields_endpoint_candidate(self) -> None:
        """阶梯②.5：OpenAPI 文档命中 → 精确端点 + 字段 schema 直接成为候选。"""
        spec = {
            "paths": {
                "/health": {"get": {}},
                "/auth/login": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"properties": {"username": {}, "password": {}}}
                                }
                            }
                        }
                    }
                },
            }
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/openapi.json":
                return httpx.Response(200, json=spec, request=request)
            return httpx.Response(200, text="<html>SPA 页面</html>", request=request)

        server = _make(http_client_factory=_transport(handler))
        result = _run(server.discover_login("https://sut.example.com/login"))
        candidate = next(c for c in result["candidates"] if c["source"] == "openapi")
        assert candidate["path"] == "/auth/login"
        assert candidate["fields"] == ["password", "username"]  # 排序后字段 schema

    def test_no_candidate_guidance_never_asks_field_names(self) -> None:
        """全阶梯落空：兜底指引只向用户要接口地址，字段名由 Agent 拟定。"""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/web/login":  # 页面路径不在常见登录路径清单内
                return httpx.Response(200, text="plain", request=request)
            return httpx.Response(404, request=request)

        server = _make(http_client_factory=_transport(handler))
        result = _run(server.discover_login("https://sut.example.com/web/login"))
        assert result["candidates"] == []
        assert "登录接口地址" in result["next_step"]
        assert "字段名不要问用户" in result["next_step"]

    def test_absolute_url_in_js_found_cross_domain(self) -> None:
        """阶梯②扩展：JS 里的绝对登录 URL（登录页域 ≠ 接口域）直接成为候选。"""
        html = (
            "<html><script>"
            'var API_BASE="https://sasan-server.example.com/users/login";'
            "</script></html>"
        )
        server = _make(http_client_factory=_ok_transport(html))
        result = _run(server.discover_login("https://sut.example.com/login/teacher/sign-in"))
        candidate = next(c for c in result["candidates"] if c["source"] == "js_url")
        assert candidate["path"] == "https://sasan-server.example.com/users/login"

    def test_js_field_hints_extracted(self) -> None:
        """前端包里的真实字段键名 → field_hints（SPA 表单 JS 渲染时的字段来源）。"""
        html = (
            "<html><script>"
            "var body={account: form.u, password: md5(form.p), captcha: code};"
            "</script></html>"
        )
        server = _make(http_client_factory=_ok_transport(html))
        result = _run(server.discover_login("https://sut.example.com/login"))
        assert {"account", "password", "captcha"} <= set(result["field_hints"])


# ── probe_login：凭证门禁 / 预览确认 / 防锁 ──────────────────────────


_LOGIN_CFG = {
    "url": "https://sut.example.com/api/login",
    "method": "POST",
    "body_template": '{"username": "{{ username }}", "password": "{{ password }}"}',
    "token_path": "token",
}

_CREDS = {"AGENT_EVAL_SUT__SUT__USERNAME": "u1", "AGENT_EVAL_SUT__SUT__PASSWORD": "p1"}


class TestProbeLogin:
    def _server(self, handler: Any, ask: Any = None) -> tuple[SUTProbeToolServer, list[str]]:
        sent: list[str] = []

        def wrapping(request: httpx.Request) -> httpx.Response:
            sent.append(str(request.url))
            return handler(request)

        server = _make(
            credential_store=CredentialStore(env=_CREDS),
            ask_fn=ask,
            http_client_factory=_transport(wrapping),
        )
        return server, sent

    def test_missing_fields_no_send(self) -> None:
        server, sent = self._server(lambda r: httpx.Response(200, json={}))
        result = _run(
            server.probe_login({**_LOGIN_CFG, "body_template": '{"k": "{{ otp }}"}'}, "SUT")
        )
        assert result["missing_fields"] == ["otp"]
        # hint 单通道指引：会话内 ask_user 直接收集，勿让用户另开终端跑命令
        assert "ask_user" in result["hint"] and "一次只录一个字段" in result["hint"]
        assert "secrets set" not in result["hint"]
        assert sent == []

    def test_credential_roundtrip_feeds_probe_login(self) -> None:
        """ask_user 录入 → probe_login 立即可读（会话内闭环，实测曾误引向终端命令）。"""
        seq = iter(["u-name", "p-word", "取消"])
        server = _make(ask_fn=_ask(lambda q, **kw: next(seq)), credential_store=CredentialStore())
        _run(server.ask_user("录入用户名", kind="credential", ref="SUT", field="username"))
        _run(server.ask_user("录入密码", kind="credential", ref="SUT", field="password"))
        result = _run(server.probe_login(_LOGIN_CFG, "SUT"))
        assert "missing_fields" not in result  # 会话内录入的凭证立即可读
        assert result["aborted"] is True  # 已走到脱敏预览确认（桩选取消）

    def test_non_interactive_never_sends(self) -> None:
        server, sent = self._server(lambda r: httpx.Response(200, json={"token": "T"}), ask=None)
        result = _run(server.probe_login(_LOGIN_CFG, "SUT"))
        assert result["need_confirm"] is True
        assert "•••" in result["masked_body"]  # 凭证已脱敏
        assert sent == []  # 凭证外发硬门禁：无确认不发送

    def test_confirm_then_send_masks_token(self) -> None:
        server, sent = self._server(
            lambda r: httpx.Response(200, json={"token": "T0KPEN"}),
            ask=_ask(lambda q, **kw: "发送"),
        )
        result = _run(server.probe_login(_LOGIN_CFG, "SUT"))
        assert result["ok"] is True and result["token_extracted"] is True
        assert len(sent) == 1
        assert "T0KPEN" not in json.dumps(result)  # token 值不回流 LLM 上下文

    def test_cancel_aborts(self) -> None:
        server, sent = self._server(
            lambda r: httpx.Response(200, json={}), ask=_ask(lambda q, **kw: "取消")
        )
        result = _run(server.probe_login(_LOGIN_CFG, "SUT"))
        assert result["aborted"] is True
        assert sent == []

    def test_one_attempt_only_after_failure(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(401, json={"error": "bad"}, request=request)

        server, _ = self._server(handler, ask=_ask(lambda q, **kw: "发送"))
        first = _run(server.probe_login(_LOGIN_CFG, "SUT"))
        second = _run(server.probe_login(_LOGIN_CFG, "SUT"))
        assert first["ok"] is False and calls["n"] == 1
        assert "防锁" in second["error"] and calls["n"] == 1  # 不再自动重试

    def test_renamed_template_counts_as_new_combination(self) -> None:
        """防锁按（接口+字段组合）：用户纠正字段更新 body_template 后允许再实测一次。"""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(401, json={"error": "bad"}, request=request)

        server, _ = self._server(handler, ask=_ask(lambda q, **kw: "发送"))
        assert _run(server.probe_login(_LOGIN_CFG, "SUT"))["ok"] is False
        renamed = {
            **_LOGIN_CFG,
            "body_template": '{"user": "{{ username }}", "pwd": "{{ password }}"}',
        }
        second = _run(server.probe_login(renamed, "SUT"))
        assert "error" not in second and calls["n"] == 2  # 新组合放行而非防锁拒绝


# ── probe_protocol：矩阵 + 清理 ──────────────────────────────────────


class TestProbeProtocol:
    def test_matrix_steps_recorded_and_cleanup(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(f"{request.method} {request.url.path}")
            if request.method == "POST" and request.url.path == "/threads":
                return httpx.Response(200, json={"thread_id": "t1"}, request=request)
            return httpx.Response(200, json={}, request=request)

        server = _make(http_client_factory=_transport(handler))
        result = _run(server.probe_protocol("https://sut.example.com"))
        steps = [m["step"] for m in result["matrix"]]
        assert steps[0] == "create_thread" and "cleanup" in steps
        assert any(m["step"] == "stream" for m in result["matrix"])
        assert "POST /threads" in seen and "DELETE /threads/t1" in seen

    def test_single_endpoint_failure_keeps_matrix(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/threads":
                raise httpx.ConnectError("boom")
            return httpx.Response(200, json={}, request=request)

        server = _make(http_client_factory=_transport(handler))
        result = _run(server.probe_protocol("https://sut.example.com"))
        assert result["matrix"]  # 单端点失败不整体中断
        assert result["matrix"][0]["ok"] is False


# ── ask_user 桥与凭证直写 ────────────────────────────────────────────


class TestAskUser:
    def test_non_interactive_error(self) -> None:
        server = _make()
        result = _run(server.ask_user("hi"))
        assert "非交互环境" in result["error"]

    def test_text_answer(self) -> None:
        server = _make(ask_fn=_ask(lambda q, **kw: "https://x.example.com"))
        result = _run(server.ask_user("入口地址？"))
        assert result["answer"] == "https://x.example.com"

    def test_credential_saved_not_returned(self) -> None:
        from agent_eval.execution.auth import secrets_store

        server = _make(ask_fn=_ask(lambda q, **kw: "s3cret"), credential_store=CredentialStore())
        result = _run(server.ask_user("录入密码", kind="credential", ref="SUT", field="password"))
        assert result["saved"] is True
        assert "s3cret" not in json.dumps(result)  # 值不回流
        on_disk = secrets_store.load_secrets_file(secrets_store.secrets_file_path())
        assert on_disk["SUT"]["password"] == "s3cret"  # conftest 已把路径钉进 tmp_path

    def test_credential_requires_ref_and_field(self) -> None:
        server = _make(ask_fn=_ask(lambda q, **kw: "x"))
        result = _run(server.ask_user("?", kind="credential"))
        assert "ref" in result["error"] and "field" in result["error"]

    def test_credential_field_must_be_single(self) -> None:
        """一次只录一个字段：多字段打包拒绝（实测 Agent 曾传 field="username,password"）。"""
        server = _make(ask_fn=_ask(lambda q, **kw: "x"))
        result = _run(
            server.ask_user("录入", kind="credential", ref="SUT", field="username,password")
        )
        assert "一次只接受一个字段" in result["error"]
        assert "逐字段" in result["error"]

    def test_single_option_degrades_to_text(self) -> None:
        """单选项 options 无选择意义：降级为文本输入，不走 select（防假单选）。"""
        seen: dict[str, Any] = {}

        def spy(question: str, *, options=None, secret=False):
            seen["options"] = options
            return "https://sut.example.com"

        server = _make(ask_fn=_ask(spy))
        result = _run(server.ask_user("入口地址？", options="文本输入"))
        assert result["answer"] == "https://sut.example.com"
        assert seen["options"] is None  # 单项已被丢弃

    def test_overlong_question_rejected_with_split_hint(self) -> None:
        """多问打包超长 → 拒答并指引拆分（一次一问契约）。"""
        server = _make(ask_fn=_ask(lambda q, **kw: "x"))
        result = _run(server.ask_user("很长的多问打包" * 60))
        assert "一次只问一个问题" in result["error"]
        assert "拆" in result["error"]


# ── 轮内预算 ─────────────────────────────────────────────────────────


class TestBudget:
    def test_budget_per_tool_and_reset(self) -> None:
        """预算按工具分池：probe_url 打满不牵连 discover_login（预算饿死发现链的实测教训）。"""
        server = _make()
        for _ in range(TOOL_BUDGETS["probe_url"]):
            result = _run(server.probe_url("https://sut.example.com/x"))
            assert result["reachable"] is True
        error = _run(server.probe_url("https://sut.example.com/x"))["error"]
        assert "上限" in error and "未经验证" in error  # 拒绝时指引继续验证而非收尾
        page = _run(server.discover_login("https://sut.example.com/web/login"))
        assert "error" not in page  # 独立预算池——发现工具不受 probe_url 牵连
        server.new_turn()  # PackageAgent.turn() 每轮调用
        assert _run(server.probe_url("https://sut.example.com/x"))["reachable"] is True


# ── PackageAgent 集成（工具注册与预算挂点） ─────────────────────────


class TestPackageAgentIntegration:
    def test_probe_tools_registered(self, tmp_path: Path) -> None:
        from agent_eval.agent.package_agent import PackageAgent

        agent = PackageAgent(tmp_path)
        described = agent._describe_tools()  # noqa: SLF001 — 单测内省
        for name in ("probe_url", "discover_login", "probe_protocol", "probe_login", "ask_user"):
            assert name in described
        assert agent.probe.credentials is not None
        assert agent.probe.log_path == agent._log_path  # noqa: SLF001 — 证据随会话日志

    def test_turn_resets_probe_budget(self, tmp_path: Path) -> None:
        from agent_eval.agent.package_agent import PackageAgent

        agent = PackageAgent(tmp_path)
        agent.probe._turn_calls["probe_url"] = TOOL_BUDGETS["probe_url"]  # noqa: SLF001
        agent.probe.new_turn()
        assert agent.probe._turn_calls.get("probe_url", 0) == 0  # noqa: SLF001
