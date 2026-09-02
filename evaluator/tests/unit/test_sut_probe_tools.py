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
        """404 ≠ 不可达：POST-only 接口 GET 即 404——指引 probe_login 实测或 discover_login 发现。"""

        def not_found(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Cannot GET /", request=request)

        server = _make(http_client_factory=_transport(not_found))
        result = _run(server.probe_url("https://sut.example.com/"))
        assert result["reachable"] is True
        assert "probe_login" in result["next_step"]  # 用户给的登录 API：POST 实测验证
        assert "discover_login" in result["next_step"]  # 找页面：交页面发现
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

    def test_all_forms_returned_without_semantic_filter(self) -> None:
        """语义过滤不进解析层：搜索框（无密码字段）与短信登录表单一并返回，判读交 Agent。"""
        html = (
            "<html><form action='/search'><input name='keyword'></form>"
            "<form action='/sms-login'><input name='phone'><input name='sms_code'></form></html>"
        )
        server = _make(http_client_factory=_ok_transport(html))
        result = _run(server.discover_login("https://sut.example.com/login"))
        forms = [c for c in result["candidates"] if c["source"] == "form"]
        assert {f["path"] for f in forms} == {"/search", "/sms-login"}  # 无密码形态不被漏掉

    def test_supplied_paths_probed_directly(self) -> None:
        """paths 由 Agent 自拟（工具不内置路径清单）：非 404 记为存在。"""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/login":
                return httpx.Response(405, text="method not allowed", request=request)
            return httpx.Response(404, request=request)

        server = _make(http_client_factory=_transport(handler))
        result = _run(
            server.discover_login("https://sut.example.com/login", paths="/api/auth/login|/nope")
        )
        cand = next(c for c in result["candidates"] if c["source"] == "probed_path")
        assert cand["path"] == "/api/auth/login"  # 405 ≠ 404：路径存在

    def test_page_and_scripts_cached_for_search(self) -> None:
        """页面与同域脚本入缓存——前端包分析的存储侧（search_content 消费）。"""
        page = '<html><body><script src="/app.js"></script></body></html>'

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/login":
                return httpx.Response(200, text=page, request=request)
            if request.url.path == "/app.js":
                return httpx.Response(200, text="window.cfg=1", request=request)
            return httpx.Response(404, request=request)

        server = _make(http_client_factory=_transport(handler))
        result = _run(server.discover_login("https://sut.example.com/login"))
        assert "/app.js" in result["scripts"]
        assert "https://sut.example.com/app.js" in result["cached"]
        found = _run(server.search_content("cfg"))
        assert any("window.cfg=1" in m["excerpt"] for m in found["matches"])

    def test_openapi_doc_yields_endpoint_candidate(self) -> None:
        """阶梯③：OpenAPI 文档命中 → POST 端点原样列出（无 login 关键字过滤）+ 文档入缓存。"""
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
        assert "https://sut.example.com/openapi.json" in result["cached"]  # 原文可检索

    def test_no_candidate_guidance_never_asks_field_names(self) -> None:
        """全阶梯落空：兜底指引只向用户要接口地址，字段名由 Agent 拟定。"""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/web/login":  # 无脚本无文档无 paths 的页面
                return httpx.Response(200, text="<html>空页面</html>", request=request)
            return httpx.Response(404, request=request)

        server = _make(http_client_factory=_transport(handler))
        result = _run(server.discover_login("https://sut.example.com/web/login"))
        assert result["candidates"] == []
        assert "登录接口地址" in result["next_step"]
        assert "字段名不要问用户" in result["next_step"]

    def test_api_endpoint_input_notes_direct_probe_login(self) -> None:
        """传入接口地址（响应非 HTML）→ next_step 覆盖为直通 probe_login（单一权威指引）。"""

        def not_found(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Cannot GET /users/login", request=request)

        server = _make(http_client_factory=_transport(not_found))
        result = _run(server.discover_login("https://sut.example.com/users/login"))
        # next_step 直接覆盖（不与兜底指引并存——两套指引方向相反时 Agent 会滑回猜路径）
        assert "权威输入" in result["next_step"]
        assert "probe_login" in result["next_step"]
        assert "不要再用 probe_url" in result["next_step"]

        html_server = _make(http_client_factory=_ok_transport("<html><body>登录页</body></html>"))
        page_result = _run(html_server.discover_login("https://sut.example.com/login"))
        assert "权威输入" not in page_result["next_step"]  # 页面场景保留兜底指引


# ── search_content：前端包分析原语 ───────────────────────────────────


class TestSearchContent:
    def test_requires_cached_content(self) -> None:
        server = _make()
        assert "缓存为空" in _run(server.search_content("login"))["error"]

    def test_finds_case_insensitive_with_context(self) -> None:
        server = _make()
        server._cache_content(  # noqa: SLF001 — 单测直填缓存
            "https://sut.example.com/app.js", "axios.post('/U/Login',{a:1});" + "x" * 50
        )
        result = _run(server.search_content("u/login"))
        assert len(result["matches"]) == 1
        assert "/U/Login" in result["matches"][0]["excerpt"]

    def test_match_cap_and_pattern_validation(self) -> None:
        server = _make()
        server._cache_content("https://sut.example.com/x.js", "ab " * 60)  # noqa: SLF001
        capped = _run(server.search_content("ab"))
        assert 0 < len(capped["matches"]) <= 12
        assert "pattern 不能为空" in _run(server.search_content("  "))["error"]
        assert "过长" in _run(server.search_content("x" * 120))["error"]

    def test_no_match_guides_next_step(self) -> None:
        server = _make()
        server._cache_content("https://sut.example.com/x.js", "nothing here")  # noqa: SLF001
        result = _run(server.search_content("missing"))
        assert result["matches"] == []
        assert "next_step" in result  # 换词重试的指引，而非终结

    def test_new_turn_clears_cache(self) -> None:
        server = _make()
        server._cache_content("https://sut.example.com/x.js", "abc")  # noqa: SLF001
        server.new_turn()
        assert "缓存为空" in _run(server.search_content("abc"))["error"]


# ── 前端包分析：泛化原语组合（真实 SPA 形态模拟） ────────────────────


class TestFrontendAnalysis:
    """抓取入缓存 + Agent 自拟模式检索——工具面不内置任何登录/分包知识。

    模拟真实 SPA：页面单脚本 → 主包只有分块映射与接口基址 → 登录契约在页面分块。
    以下检索词全部由「Agent」侧拟定，工具只做机械的抓取/检索/摘录。
    """

    PAGE = '<html><body><script src="/umi.js"></script></body></html>'
    MAIN = (
        '.u=function(A){return ""+({9258:"login__teacher__index"}[A]||A)+'
        '"."+({9258:"826c0f38"}[A]+".async.js")};'
        'a.interceptors.request.use(function(s){s.baseURL="https://api.sut.example.com";return s})'
    )
    CHUNK = 'le.Z.post("/users/login",{phone:B,captcha:R,platform:FS})'

    def _server(self) -> SUTProbeToolServer:
        js_headers = {"content-type": "application/javascript"}

        def handler(request: httpx.Request) -> httpx.Response:
            routes = {
                "/login": (self.PAGE, {}),
                "/umi.js": (self.MAIN, js_headers),
                "/login__teacher__index.826c0f38.async.js": (self.CHUNK, js_headers),
            }
            hit = routes.get(request.url.path)
            if hit is None:
                return httpx.Response(404, request=request)
            return httpx.Response(200, text=hit[0], headers=hit[1], request=request)

        return _make(http_client_factory=_transport(handler))

    def test_bundle_cached_and_chunk_map_readable(self) -> None:
        server = self._server()
        result = _run(server.probe_url("https://sut.example.com/umi.js"))
        assert result["cached_bytes"] > 0 and "search_hint" in result
        found = _run(server.search_content("async.js"))
        excerpt = found["matches"][0]["excerpt"]
        # 分块映射（名字 + hash + 后缀）可从摘录中读出——推算 chunk URL 由 Agent 完成
        assert "9258" in excerpt and "login__teacher__index" in excerpt

    def test_login_contract_found_via_agent_chosen_patterns(self) -> None:
        server = self._server()
        _run(server.probe_url("https://sut.example.com/login"))
        _run(server.probe_url("https://sut.example.com/umi.js"))
        assert _run(server.search_content("post("))["matches"] == []  # 主包无登录请求字面量
        _run(server.probe_url("https://sut.example.com/login__teacher__index.826c0f38.async.js"))
        hit = _run(server.search_content("post("))["matches"][0]["excerpt"]
        assert "/users/login" in hit and "captcha" in hit  # 契约在页面分块里
        base = _run(server.search_content("baseURL"))["matches"][0]["excerpt"]
        assert "https://api.sut.example.com" in base  # 接口域可检索、与路径组合交 Agent


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
        _run(
            server.ask_user(
                "录入用户名", kind="credential", ref="SUT", field="username", desc="登录账号"
            )
        )
        _run(
            server.ask_user(
                "录入密码", kind="credential", ref="SUT", field="password", desc="登录密码"
            )
        )
        result = _run(server.probe_login(_LOGIN_CFG, "SUT"))
        assert "missing_fields" not in result  # 会话内录入的凭证立即可读
        assert result["aborted"] is True  # 已走到脱敏预览确认（桩选取消）

    def test_preview_shows_full_url_for_user_verification(self) -> None:
        """预览必须显示完整 URL——路径抄错只有在这里用户才看得见（只显 host 等于没校对）。"""
        seen: dict[str, Any] = {}

        def spy(question: str, *, options=None, secret=False):
            seen["q"] = question
            return "取消"

        server, sent = self._server(lambda r: httpx.Response(200, json={}), ask=_ask(spy))
        result = _run(server.probe_login(_LOGIN_CFG, "SUT"))
        assert "https://sut.example.com/api/login" in seen["q"]
        assert "POST" in seen["q"]
        assert result["aborted"] is True and sent == []

    def test_result_carries_verified_url(self) -> None:
        server, _ = self._server(
            lambda r: httpx.Response(200, json={"token": "T"}), ask=_ask(lambda q, **kw: "发送")
        )
        result = _run(server.probe_login(_LOGIN_CFG, "SUT"))
        assert result["url"] == "https://sut.example.com/api/login"

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

    def test_credential_save_unlocks_login_retry(self) -> None:
        """防锁解锁：失败后重新录入凭证（同模板）允许再实测——循环由录入交互限流。"""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(401, json={"error": "bad"}, request=request)

        seq = iter(["发送", "new-pass", "发送"])
        server, _ = self._server(handler, ask=_ask(lambda q, **kw: next(seq)))
        assert _run(server.probe_login(_LOGIN_CFG, "SUT"))["ok"] is False
        assert "防锁" in _run(server.probe_login(_LOGIN_CFG, "SUT"))["error"]
        _run(
            server.ask_user(
                "更正密码", kind="credential", ref="SUT", field="password", desc="登录密码"
            )
        )
        third = _run(server.probe_login(_LOGIN_CFG, "SUT"))
        assert "error" not in third and calls["n"] == 2  # 解锁放行而非拒绝

    def test_status_guidance_distinguishes_404_from_auth_fail(self) -> None:
        """POST 判别语义：404=路径不存在交用户核对；401=接口存在，收集凭证重测。"""

        def gone(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Not Found", request=request)

        server, _ = self._server(gone, ask=_ask(lambda q, **kw: "发送"))
        assert "不存在" in _run(server.probe_login(_LOGIN_CFG, "SUT"))["next_step"]

        def unauthorized(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "bad creds"}, request=request)

        auth_server, _ = self._server(unauthorized, ask=_ask(lambda q, **kw: "发送"))
        auth_result = _run(auth_server.probe_login(_LOGIN_CFG, "SUT"))
        assert "接口存在" in auth_result["next_step"]


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
        result = _run(
            server.ask_user(
                "录入密码", kind="credential", ref="SUT", field="password", desc="登录密码"
            )
        )
        assert result["saved"] is True
        assert "s3cret" not in json.dumps(result)  # 值不回流
        on_disk = secrets_store.load_secrets_file(secrets_store.secrets_file_path())
        assert on_disk["SUT"]["password"] == "s3cret"  # conftest 已把路径钉进 tmp_path

    def test_credential_requires_ref_and_field(self) -> None:
        server = _make(ask_fn=_ask(lambda q, **kw: "x"))
        result = _run(server.ask_user("?", kind="credential"))
        assert "ref" in result["error"] and "field" in result["error"]

    def test_credential_requires_desc_explaining_field(self) -> None:
        """desc 必带：字段实际含义由 Agent 说明（逐站点知识不进代码），否则用户无从输入。"""
        server = _make(ask_fn=_ask(lambda q, **kw: "x"))
        result = _run(server.ask_user("?", kind="credential", ref="SUT", field="captcha"))
        assert "desc" in result["error"]

    def test_credential_prompt_carries_field_meaning(self) -> None:
        """录入提示直达字段语义——实测反馈：只显示「请输入 ref.field」用户不知道在输入什么。"""
        seen: dict[str, Any] = {}

        def spy(question: str, *, options=None, secret=False):
            seen["q"] = question
            return "s3cret"

        server = _make(ask_fn=_ask(spy), credential_store=CredentialStore())
        result = _run(
            server.ask_user(
                "录入",
                kind="credential",
                ref="BJ33",
                field="captcha",
                desc="captcha 字段实际提交的是登录密码（从登录分块代码得出）",
            )
        )
        assert result["saved"] is True
        q = seen["q"]
        assert "BJ33" in q and "captcha" in q
        assert "登录密码" in q  # Agent 传入的字段语义直达用户
        assert "不会回显" in q  # 机械事实：隐藏输入

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

    def test_search_budget_independent_pool(self) -> None:
        server = _make()
        server._cache_content("https://sut.example.com/x.js", "abc")  # noqa: SLF001
        for _ in range(TOOL_BUDGETS["search_content"]):
            assert "matches" in _run(server.search_content("a"))
        assert "上限" in _run(server.search_content("a"))["error"]


# ── PackageAgent 集成（工具注册与预算挂点） ─────────────────────────


class TestPackageAgentIntegration:
    def test_probe_tools_registered(self, tmp_path: Path) -> None:
        from agent_eval.agent.package_agent import PackageAgent

        agent = PackageAgent(tmp_path)
        described = agent._describe_tools()  # noqa: SLF001 — 单测内省
        for name in (
            "probe_url",
            "discover_login",
            "search_content",
            "probe_protocol",
            "probe_login",
            "ask_user",
        ):
            assert name in described
        assert agent.probe.credentials is not None
        assert agent.probe.log_path == agent._log_path  # noqa: SLF001 — 证据随会话日志

    def test_turn_resets_probe_budget(self, tmp_path: Path) -> None:
        from agent_eval.agent.package_agent import PackageAgent

        agent = PackageAgent(tmp_path)
        agent.probe._turn_calls["probe_url"] = TOOL_BUDGETS["probe_url"]  # noqa: SLF001
        agent.probe.new_turn()
        assert agent.probe._turn_calls.get("probe_url", 0) == 0  # noqa: SLF001
