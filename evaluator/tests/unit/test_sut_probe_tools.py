"""SUTProbeToolServer 单测——全 mock（httpx MockTransport，禁止联网红线）。

覆盖 arch/15 §6.5 P0 红线（v4 探测面，docs/plan/03）：host 边界与授权、凭证外发
授权（(host, ref) 组合级首次确认/每次留痕/非交互不发送）、探测内容注入防护
（data 包裹）、凭证请求防锁（4xx/5xx 一次即停）、值回流条件化（2xx 提取前只回
键路径树）、declare_token 事后声明式提取（三态 token_source + 证据账本）、轮内
预算、ask_user 凭证直写密钥区不回流。异步工具以 ``asyncio.run`` 同步壳驱动
（对齐 test_execution_agent 惯例）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from agent_eval.agent.probe import (
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
        result = _run(server.request("GET", "https://evil.example.com/x"))
        assert "未获用户授权" in result["error"]
        assert "ask_user" in result["error"]  # 指引 Agent 走用户确认

    def test_ask_user_authorizes_new_host(self) -> None:
        server = _make(allowed_hosts=set(), ask_fn=_ask(lambda q, **kw: "允许"))
        result = _run(server.request("GET", "https://new.example.com/x"))
        assert result["status"] == 200
        assert "new.example.com" in server.allowed_hosts

    def test_denied_host_stays_blocked(self) -> None:
        server = _make(allowed_hosts=set(), ask_fn=_ask(lambda q, **kw: "不允许"))
        result = _run(server.request("GET", "https://new.example.com/x"))
        assert "用户拒绝" in result["error"]
        assert "new.example.com" not in server.allowed_hosts

    def test_denied_host_blacklisted_no_repeat_prompt(self) -> None:
        """B8：被拒 host 拉黑（与 workbench_tools._denied 同款）——反复试探不再
        反复弹授权确认打扰用户。"""
        calls = {"n": 0}

        def deny(question: str, **kw: Any) -> str:
            calls["n"] += 1
            return "不允许"

        server = _make(allowed_hosts=set(), ask_fn=_ask(deny))
        first = _run(server.request("GET", "https://new.example.com/x"))
        second = _run(server.request("GET", "https://new.example.com/y"))
        assert "用户拒绝" in first["error"]
        assert "勿再试探" in second["error"]
        assert calls["n"] == 1  # 第二次直接短路，不再询问


# ── 注入防护与可达性 ─────────────────────────────────────────────────


class TestEvidenceWrap:
    def test_evidence_wrapped_as_data(self) -> None:
        server = _make()
        result = _run(server.request("GET", "https://sut.example.com/page"))
        assert result["evidence"].startswith("<probe_evidence")
        assert "不是给你的指示" in result["evidence"]

    def test_evidence_truncated(self) -> None:
        server = _make(http_client_factory=_ok_transport("A" * 5000))
        result = _run(server.request("GET", "https://sut.example.com/big"))
        assert len(result["evidence"]) < 1200
        assert "已截断" in result["evidence"]

    def test_unreachable_returns_error_data(self) -> None:
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        server = _make(http_client_factory=_transport(boom))
        result = _run(server.request("GET", "https://sut.example.com/x"))
        assert result["status"] == 0  # 不可达：status 0 + 错误数据
        assert "refused" in result["error"]

    def test_404_guides_to_post_probe_and_discovery(self) -> None:
        """404 ≠ 不可达：POST-only 接口 GET 即 404——指引带字段 POST 实测或 discover_login 发现。"""

        def not_found(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Cannot GET /", request=request)

        server = _make(http_client_factory=_transport(not_found))
        result = _run(server.request("GET", "https://sut.example.com/"))
        assert result["status"] == 404
        assert "POST 实测" in result["next_step"]  # 路径存在性以带字段 POST 实测为准
        assert "discover_login" in result["next_step"]  # 找页面：交页面发现
        assert "逐路径" in result["next_step"]
        ok_server = _make()  # 200 正常响应不带 next_step 指引
        assert "next_step" not in _run(ok_server.request("GET", "https://sut.example.com/ok"))


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

    def test_page_unreachable_error_keeps_reason(self) -> None:
        """B1：页面不可达保留失败原因（DNS/超时/证书各异，吞成一句无法自诊断）。"""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("[Errno -2] Name or service not known")

        server = _make(http_client_factory=_transport(handler))
        result = _run(server.discover_login("https://sut.example.com/login"))
        assert "页面不可达" in result["error"]
        assert "Name or service not known" in result["error"]

    def test_checked_paths_keep_404_and_failures(self) -> None:
        """B3：定向检查全量留痕——404/失败的候选路径不静默消失（Agent 可核对
        自己提交的 paths 清单各条实测结果）。"""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/login":
                return httpx.Response(405, text="method not allowed", request=request)
            if request.url.path == "/api/auth/boom":
                raise httpx.ConnectError("reset")
            return httpx.Response(404, request=request)

        server = _make(http_client_factory=_transport(handler))
        result = _run(
            server.discover_login(
                "https://sut.example.com/login",
                paths="/api/auth/login|/api/auth/boom|/nope",
            )
        )
        by_path = {c["path"]: c for c in result["checked_paths"]}
        assert by_path["/api/auth/login"]["status"] == 405
        assert by_path["/nope"]["status"] == 404
        assert by_path["/api/auth/boom"]["status"] == 0
        assert {c["path"] for c in result["candidates"] if c["source"] == "probed_path"} == {
            "/api/auth/login"
        }

    def test_candidates_truncation_flagged(self) -> None:
        """B3：候选截断显式化（truncated + total）——静默丢弃会让 Agent 以为看全了。"""
        server = _make(
            http_client_factory=_transport(
                lambda request: httpx.Response(200, text="ok", request=request)
            )
        )
        paths = "|".join(f"/p{i}" for i in range(10))
        result = _run(server.discover_login("https://sut.example.com/login", paths=paths))
        assert result["candidates_truncated"] is True
        assert result["candidates_total"] == 10
        assert len(result["candidates"]) == 8

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

    def test_api_endpoint_input_notes_direct_probe(self) -> None:
        """传入接口地址（响应非 HTML）→ next_step 覆盖为直通登录实测（单一权威指引）。"""

        def not_found(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Cannot GET /users/login", request=request)

        server = _make(http_client_factory=_transport(not_found))
        result = _run(server.discover_login("https://sut.example.com/users/login"))
        # next_step 直接覆盖（不与兜底指引并存——两套指引方向相反时 Agent 会滑回猜路径）
        assert "权威输入" in result["next_step"]
        assert "登录实测" in result["next_step"]
        assert "不要再用 request" in result["next_step"]

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

    def test_context_non_integer_rejected_with_guidance(self) -> None:
        """B7：context 非整数转结构化错误（旧实现裸 int() 抛 ValueError，经导出层
        兜底成无工具语境的通用 failed——丢失本工具其余分支都有的纠正指引）。"""
        server = _make()
        result = _run(server.search_content("token", context="abc"))
        assert "context" in result["error"] and "整数" in result["error"]

    def test_no_match_guides_next_step(self) -> None:
        server = _make()
        server._cache_content("https://sut.example.com/x.js", "nothing here")  # noqa: SLF001
        result = _run(server.search_content("missing"))
        assert result["matches"] == []
        assert "next_step" in result  # 换词重试的指引，而非终结

    def test_new_turn_keeps_cache_and_resets_budget(self) -> None:
        """缓存跨轮保留：预算报错指引「开新轮续查」——若连缓存清空，新轮要先重抓
        重搜前端主包才能回到原地，放大的预算也先耗在重复劳动上。预算照常重置。"""
        server = _make()
        server._cache_content("https://sut.example.com/x.js", "abc")  # noqa: SLF001
        server.new_turn()
        found = _run(server.search_content("abc"))
        assert any("abc" in m["excerpt"] for m in found["matches"])  # 新轮直接续查


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
        result = _run(server.request("GET", "https://sut.example.com/umi.js"))
        assert result["cached_bytes"] > 0 and "search_hint" in result
        found = _run(server.search_content("async.js"))
        excerpt = found["matches"][0]["excerpt"]
        # 分块映射（名字 + hash + 后缀）可从摘录中读出——推算 chunk URL 由 Agent 完成
        assert "9258" in excerpt and "login__teacher__index" in excerpt

    def test_login_contract_found_via_agent_chosen_patterns(self) -> None:
        server = self._server()
        _run(server.request("GET", "https://sut.example.com/login"))
        _run(server.request("GET", "https://sut.example.com/umi.js"))
        assert _run(server.search_content("post("))["matches"] == []  # 主包无登录请求字面量
        _run(
            server.request("GET", "https://sut.example.com/login__teacher__index.826c0f38.async.js")
        )
        hit = _run(server.search_content("post("))["matches"][0]["excerpt"]
        assert "/users/login" in hit and "captcha" in hit  # 契约在页面分块里
        base = _run(server.search_content("baseURL"))["matches"][0]["excerpt"]
        assert "https://api.sut.example.com" in base  # 接口域可检索、与路径组合交 Agent


# ── request 登录实测：凭证模板 / 外发授权 / 防锁 ─────────────────────


_LOGIN_URL = "https://sut.example.com/api/login"
_LOGIN_BODY = '{"username": "{{ username }}", "password": "{{ password }}"}'
_CREDS = {"AGENT_EVAL_SUT__SUT__USERNAME": "u1", "AGENT_EVAL_SUT__SUT__PASSWORD": "p1"}


class TestRequestLoginFlow:
    """登录实测走 request 原语（v4）：凭证模板服务端注入、组合级外发授权、防锁。"""

    def _server(
        self, handler: Any, ask: Any = None, creds: Any = None
    ) -> tuple[SUTProbeToolServer, list[httpx.Request]]:
        sent: list[httpx.Request] = []

        def wrapping(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return handler(request)

        server = _make(
            credential_store=creds if creds is not None else CredentialStore(env=_CREDS),
            ask_fn=ask,
            http_client_factory=_transport(wrapping),
        )
        return server, sent

    def test_missing_credential_field_rejected_no_send(self) -> None:
        server, sent = self._server(lambda r: httpx.Response(200, json={}))
        result = _run(server.request("POST", _LOGIN_URL, body='{"k": "{{ otp }}"}', ref="SUT"))
        assert "otp" in result["error"] and "不在密钥区" in result["error"]
        assert "ask_user" in result["error"]  # 单通道指引：会话内直接录入
        assert "secrets set" not in result["error"]
        assert sent == []

    def test_ask_user_roundtrip_feeds_request(self) -> None:
        """ask_user 录入 → request 立即可读（会话内闭环，实测曾误引向终端命令）。"""
        seq = iter(["u-name", "p-word", "允许"])
        server, sent = self._server(
            lambda r: httpx.Response(200, json={"token": "T"}),
            ask=_ask(lambda q, **kw: next(seq)),
            creds=CredentialStore(),
        )
        miss = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert "不在密钥区" in miss["error"]  # 先按提示录入
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
        ok = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert ok["status"] == 200 and len(sent) == 1

    def test_grant_preview_shows_full_url_and_template(self) -> None:
        """授权预览必须显示完整 URL 与模板 body——路径抄错只有在这里用户才看得见；
        预览是模板原文（占位符形态天然不含凭证值，值在服务端注入）。"""
        seen: dict[str, str] = {}

        def spy(question: str, *, options=None, secret=False):
            seen["q"] = question
            return "取消"

        server, sent = self._server(lambda r: httpx.Response(200, json={}), ask=_ask(spy))
        result = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert "https://sut.example.com/api/login" in seen["q"]
        assert "POST" in seen["q"]
        assert "{{ username }}" in seen["q"] and "u1" not in seen["q"]  # 模板原文，无凭证值
        assert result["aborted"] is True and sent == []

    def test_grant_once_per_host_and_ref(self) -> None:
        """组合级授权：同 (host, ref) 首次确认后本会话不再逐次问（每次外发留痕）。"""
        asks = {"n": 0}

        def ask(question: str, *, options=None, secret=False):
            asks["n"] += 1
            return "允许"

        server, sent = self._server(
            lambda r: httpx.Response(200, json={"token": "T"}), ask=_ask(ask)
        )
        first = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        second = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert first["status"] == 200 and second["status"] == 200
        assert asks["n"] == 1 and len(sent) == 2

    def test_non_interactive_never_sends_credentials(self) -> None:
        server, sent = self._server(lambda r: httpx.Response(200, json={}), ask=None)
        result = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert "非交互环境不外发凭证" in result["error"]
        assert sent == []  # 凭证外发硬门禁：无确认不发送

    def test_credential_values_injected_server_side_only(self) -> None:
        """凭证值只出现在发出去的请求里，不回流工具返回（值回流条件化：2xx 未声明
        只回键路径树）。"""
        server, sent = self._server(
            lambda r: httpx.Response(200, json={"token": "T0KPEN"}),
            ask=_ask(lambda q, **kw: "允许"),
        )
        result = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert result["status"] == 200
        body = sent[0].content.decode()
        assert '"u1"' in body and '"p1"' in body  # 服务端注入生效
        assert "{{" not in body
        assert "u1" not in json.dumps(result) and "p1" not in json.dumps(result)
        assert "T0KPEN" not in json.dumps(result)  # 未声明，token 值不回流

    def test_typo_variable_rejected_not_sent_as_empty(self) -> None:
        """StrictUndefined（V3 验证：jinja2 默认 Undefined 渲染空串——拼错变量发出
        空参请求是必须消灭的静默失败）。v4 机械三分类下拼错变量落凭证字段类，
        被「不在密钥区」拦下并给出可用字段纠错。"""
        server, sent = self._server(lambda r: httpx.Response(200, json={}))
        result = _run(
            server.request("POST", _LOGIN_URL, body='{"username": "{{ usrename }}"}', ref="SUT")
        )
        assert "usrename" in result["error"] and sent == []

    def test_unrendered_placeholder_rejected_not_sent(self) -> None:
        """${var} 等 shell 风格占位符渲染后残留 → 拒发（实测：${phone} 原样发出，
        服务端报「格式不是手机号」被误归因用户输入）。"""
        server, sent = self._server(lambda r: httpx.Response(200, json={}))
        result = _run(
            server.request(
                "POST", _LOGIN_URL, body='{"phone": "${phone}", "captcha": "${captcha}"}'
            )
        )
        assert "残留占位符" in result["error"] and "未发送" in result["error"]
        assert sent == []

    def test_body_dict_mechanically_serialized(self) -> None:
        """LLM 把 body 写成 JSON 对象而非字符串（v3.14 实测：jinja2 对 dict 源
        parse 兼容 render 才炸）——dict 机械序列化，凡可机械传递的变形不经 LLM 转述。"""
        server, sent = self._server(
            lambda r: httpx.Response(200, json={"token": "T0KPEN"}),
            ask=_ask(lambda q, **kw: "允许"),
        )
        result = _run(
            server.request(
                "POST",
                _LOGIN_URL,
                body={"phone": "{{ username }}", "platform": "fs"},
                ref="SUT",
            )
        )
        assert result["status"] == 200
        assert json.loads(sent[0].content) == {"phone": "u1", "platform": "fs"}

    def test_lockout_key_distinguishes_endpoints(self) -> None:
        """防锁按 (ref, 完整 URL, body) 组合：同 host 不同路径是不同组合（实测教训：
        键缺路径时，猜错路径的失败连坐了用户随后给出的正确地址）。"""
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(401, json={"error": "bad"}, request=request)

        server, _ = self._server(handler, ask=_ask(lambda q, **kw: "允许"))
        guessed = "https://sut.example.com/api/auth/login"
        correct = "https://sut.example.com/users/login"
        r1 = _run(server.request("POST", guessed, body=_LOGIN_BODY, ref="SUT"))
        r2 = _run(server.request("POST", correct, body=_LOGIN_BODY, ref="SUT"))
        r3 = _run(server.request("POST", guessed, body=_LOGIN_BODY, ref="SUT"))
        assert r1["status"] == 401 and r2["status"] == 401  # 不同路径放行
        assert "防锁" in r3["error"]
        assert calls == ["/api/auth/login", "/users/login"]

    def test_one_attempt_only_after_auth_rejection(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(401, json={"error": "bad"}, request=request)

        server, _ = self._server(handler, ask=_ask(lambda q, **kw: "允许"))
        first = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        second = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert first["status"] == 401 and calls["n"] == 1
        assert "防锁" in second["error"] and calls["n"] == 1  # 不再自动重试

    def test_renamed_body_counts_as_new_combination(self) -> None:
        """防锁按（接口+字段组合）：用户纠正字段更新 body 后允许再实测一次。"""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(401, json={"error": "bad"}, request=request)

        server, _ = self._server(handler, ask=_ask(lambda q, **kw: "允许"))
        first = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        renamed = '{"user": "{{ username }}", "pwd": "{{ password }}"}'
        second = _run(server.request("POST", _LOGIN_URL, body=renamed, ref="SUT"))
        assert first["status"] == 401 and second["status"] == 401 and calls["n"] == 2  # 新组合放行

    def test_404_not_locked_allows_path_probing(self) -> None:
        """失败语义分层：404 = 请求未到认证层不入锁——同组合可继续实测（探索不误伤）；
        防锁只拦认证层已介入（4xx/5xx 非 404）失败的同组合自动重试。"""
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(404, json={"detail": "Not Found"}, request=request)

        server, _ = self._server(handler, ask=_ask(lambda q, **kw: "允许"))
        first = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert first["status"] == 404
        assert "不计入防锁" in first["next_step"]
        second = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert second["status"] == 404  # 同组合 404 后仍可再发
        assert calls == ["/api/login", "/api/login"]

    def test_network_error_not_locked(self) -> None:
        """请求未达服务端（网络失败）无撞锁风险不入锁——同组合可重发。"""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            raise httpx.ConnectError("connection refused", request=request)

        server, _ = self._server(handler, ask=_ask(lambda q, **kw: "允许"))
        first = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert "请求失败" in first["error"] and calls["n"] == 1
        second = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert "请求失败" in second["error"] and calls["n"] == 2

    def test_credential_save_unlocks_login_retry(self) -> None:
        """防锁解锁：失败后重新录入凭证（同模板）允许再实测——重试循环由录入交互限流。"""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(401, json={"error": "bad"}, request=request)

        seq = iter(["允许", "new-pass"])
        server, _ = self._server(handler, ask=_ask(lambda q, **kw: next(seq)))
        first = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert first["status"] == 401
        locked = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert "防锁" in locked["error"]
        _run(
            server.ask_user(
                "更正密码", kind="credential", ref="SUT", field="password", desc="登录密码"
            )
        )
        third = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert third["status"] == 401 and calls["n"] == 2  # 解锁放行而非拒绝

    def test_chain_variables_render_from_step_responses(self) -> None:
        """多步认证链探索：step 响应服务端持有，{{ stepN.路径 }} 链式渲染（值全程
        服务端流动，不经返回回流）。"""
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path == "/api/csrf":
                return httpx.Response(200, json={"t": "CSRFTOK"}, request=request)
            return httpx.Response(200, json={"token": "T0KPEN"}, request=request)

        server, sent = self._server(handler, ask=_ask(lambda q, **kw: "允许"))
        s1 = _run(server.request("GET", "https://sut.example.com/api/csrf", step="step1"))
        assert s1["status"] == 200
        req = _run(
            server.request(
                "POST",
                _LOGIN_URL,
                body='{"csrf": "{{ step1.t }}", "u": "{{ username }}"}',
                ref="SUT",
            )
        )
        assert req["status"] == 200
        assert json.loads(sent[1].content) == {"csrf": "CSRFTOK", "u": "u1"}


class TestDeclareToken:
    """declare_token：事后声明式提取（D2：不重发请求就无撞锁风险）。"""

    def _server(
        self, handler: Any, ask: Any = None
    ) -> tuple[SUTProbeToolServer, list[httpx.Request]]:
        sent: list[httpx.Request] = []

        def wrapping(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return handler(request)

        server = _make(
            credential_store=CredentialStore(env=_CREDS),
            ask_fn=ask if ask is not None else _ask(lambda q, **kw: "允许"),
            http_client_factory=_transport(wrapping),
        )
        return server, sent

    def _did_login(self, handler: Any) -> tuple[SUTProbeToolServer, list[httpx.Request]]:
        """先走一次成功的登录实测（grant 默认放行），返回 (server, sent)。"""
        server, sent = self._server(handler)
        result = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert result["status"] == 200
        return server, sent

    def test_without_prior_request_directed_to_request_first(self) -> None:
        server, sent = self._server(lambda r: httpx.Response(200, json={}))
        result = _run(server.declare_token("SUT", token_path="token"))
        assert "request" in result["error"] and "ask_user" in result["error"]
        assert sent == []

    def test_after_401_rejected(self) -> None:
        server, _ = self._server(lambda r: httpx.Response(401, json={"error": "bad"}))
        _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        result = _run(server.declare_token("SUT", token_path="token"))
        assert "401" in result["error"] and "2xx" in result["error"]

    def test_success_snippet_ledger_and_mounting(self) -> None:
        """声明成功三件事：token 服务端持有（自动挂载）、机械渲染可照抄 auth 段、
        事实登记证据账本（落盘对账门禁的事实源）。"""
        server, _ = self._did_login(lambda r: httpx.Response(200, json={"token": "T0KPEN"}))
        result = _run(server.declare_token("SUT", token_path="token"))
        assert result["ok"] is True
        assert "T0KPEN" not in json.dumps(result)  # token 值不回流 LLM 上下文
        snippet = result["sut_config_auth_snippet"]
        assert "token_path: token" in snippet and "credential_ref: SUT" in snippet
        assert "token_type: Bearer" in snippet
        assert server.auth_headers == {"Authorization": "Bearer T0KPEN"}
        fact = server.verified_login("SUT")
        assert fact is not None
        assert fact["url"] == _LOGIN_URL and fact["body_template"] == _LOGIN_BODY
        assert fact["token_path"] == "token" and fact["token_source"] == "Bearer"
        # 同构直接证明：片段并入 sut_config 后通过执行器 schema 校验（零修改）
        import yaml

        from agent_eval.execution.registry import validate_sut_config_document

        doc = {
            "sut": {
                "name": "s",
                "channel": "agent_protocol",
                "base_url": "https://sut.example.com",
                **yaml.safe_load(snippet),
            }
        }
        assert validate_sut_config_document(doc) == []

    def test_failed_declare_not_recorded_in_ledger(self) -> None:
        """账本只记成功事实：401 失败不构成「验证过的登录配置」。"""
        server, _ = self._server(lambda r: httpx.Response(401, json={"error": "bad"}))
        _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        _run(server.declare_token("SUT", token_path="token"))
        assert server.verified_login("SUT") is None

    def test_wrong_path_returns_tree_and_retry_needs_no_new_request(self) -> None:
        """路径不命中回键路径树（值不外显）；改路径重声明不重发请求（D2：无撞锁
        风险，防锁不适用）。"""
        server, sent = self._did_login(
            lambda r: httpx.Response(200, json={"data": {"token": "T0KPEN"}})
        )
        miss = _run(server.declare_token("SUT", token_path="wrong.path"))
        assert "wrong.path" in miss["error"]
        assert "T0KPEN" not in json.dumps(miss)
        assert "data.token" in miss["response_key_paths"]
        assert server.verified_login("SUT") is None  # 未声明成功不入账本
        ok = _run(server.declare_token("SUT", token_path="data.token"))
        assert ok["ok"] is True
        assert len(sent) == 1  # 声明阶段零请求

    def test_dollar_prefix_normalized(self) -> None:
        """``$.data.token`` 等价写法机械归一化——归一化值落 snippet 与账本。"""
        server, _ = self._did_login(
            lambda r: httpx.Response(200, json={"data": {"token": "T0KPEN"}})
        )
        result = _run(server.declare_token("SUT", token_path="$.data.token"))
        assert result["ok"] is True and result["token_path"] == "data.token"
        assert "token_path: data.token" in result["sut_config_auth_snippet"]
        assert server.verified_login("SUT")["token_path"] == "data.token"  # noqa: SLF001

    def test_array_index_path(self) -> None:
        """walker 与执行器 extract_by_path 同语义（点分 + 数字下标）。"""
        server, _ = self._did_login(lambda r: httpx.Response(200, json={"tokens": ["T0KPEN"]}))
        result = _run(server.declare_token("SUT", token_path="tokens.0"))
        assert result["ok"] is True

    def test_missing_token_path_returns_tree(self) -> None:
        server, _ = self._did_login(
            lambda r: httpx.Response(200, json={"data": {"token": "T0KPEN"}})
        )
        result = _run(server.declare_token("SUT"))
        assert "token_path" in result["error"]
        assert "data.token" in result["response_key_paths"]
        assert "T0KPEN" not in json.dumps(result)

    def test_non_json_response_distinct_error(self) -> None:
        """2xx 非 JSON 响应单独分层（旧实现与提取失败共用一条文案）。"""
        server, _ = self._did_login(
            lambda r: httpx.Response(
                200, text="<html><body>ok</body></html>", headers={"content-type": "text/html"}
            )
        )
        result = _run(server.declare_token("SUT", token_path="token"))
        assert "不是 JSON" in result["error"]
        assert "response_key_paths" not in result

    def test_credential_in_headers_rejected_before_ledger(self) -> None:
        """执行器宽度守卫（§6）：凭证走请求头的形态探测可探索、暂不可声明落盘——
        不产生假验证。"""
        server, _ = self._did_login(lambda r: httpx.Response(200, json={"token": "T0KPEN"}))
        # 重放一个 header 携带凭证的请求覆盖事实
        _run(server.request("POST", _LOGIN_URL, headers="X-API-Key: {{ username }}", ref="SUT"))
        result = _run(server.declare_token("SUT", token_path="token"))
        assert "请求头" in result["error"]
        assert server.verified_login("SUT") is None

    def test_chain_variable_request_rejected(self) -> None:
        """执行器宽度守卫（§6）：链式认证链的落盘形态（auth_chain）未落地前
        显式拒绝声明。"""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/csrf":
                return httpx.Response(200, json={"t": "CSRFTOK"}, request=request)
            return httpx.Response(200, json={"token": "T0KPEN"}, request=request)

        server, _ = self._server(handler)
        _run(server.request("GET", "https://sut.example.com/api/csrf", step="step1"))
        result = _run(server.declare_token("SUT", token_path="token"))
        assert "request" in result["error"]  # 登录请求尚未发生

        _run(
            server.request(
                "POST",
                _LOGIN_URL,
                body='{"csrf": "{{ step1.t }}", "u": "{{ username }}"}',
                ref="SUT",
            )
        )
        result = _run(server.declare_token("SUT", token_path="token"))
        assert "链式" in result["error"]
        assert server.verified_login("SUT") is None

    def test_cookie_from_set_cookie_yields_session_cookie_snippet(self) -> None:
        """自 Set-Cookie 提取落 session_cookie 形态——执行器靠共享 client 的 cookie
        jar 承载登录态，与探测侧同一机制（词汇 1:1）；jar 持有后后续请求自动带 Cookie。"""
        server, sent = self._did_login(
            lambda r: httpx.Response(
                200,
                json={"ok": True},
                headers=[("set-cookie", "session_id=ABC123; Path=/; HttpOnly")],
            )
        )
        result = _run(server.declare_token("SUT", token_source="cookie"))
        assert result["ok"] is True and result["token_path"] == ""  # 唯一 cookie 机械取用
        snippet = result["sut_config_auth_snippet"]
        assert "type: session_cookie" in snippet and "credential_ref: SUT" in snippet
        assert "ABC123" not in json.dumps(result)  # 值不回流
        assert server.auth_headers == {}  # cookie 型不挂 Authorization 头
        _run(server.request("GET", "https://sut.example.com/api/me"))
        assert "session_id=ABC123" in sent[1].headers.get("cookie", "")

    def test_cookie_from_body_requires_explicit_name(self) -> None:
        """响应体提取须 cookie:<名字> 显式命名——零字段名假设由声明参数承担。"""
        server, _ = self._did_login(lambda r: httpx.Response(200, json={"sid": "ABC123"}))
        miss = _run(server.declare_token("SUT", token_source="cookie", token_path="sid"))
        assert "cookie" in miss["error"] and "Set-Cookie" in miss["error"]
        ok = _run(server.declare_token("SUT", token_source="cookie:sid", token_path="sid"))
        assert ok["ok"] is True
        snippet = ok["sut_config_auth_snippet"]
        assert "type: api_login" in snippet
        assert "token_type: cookie" in snippet and "token_path: sid" in snippet
        assert server.auth_headers == {}

    def test_header_source_mounts_named_header(self) -> None:
        """header:X 三态：token 挂到指定头（与执行器 mount_headers 同构）。"""
        server, _ = self._did_login(lambda r: httpx.Response(200, json={"access_token": "T0KPEN"}))
        result = _run(
            server.declare_token(
                "SUT", token_path="access_token", token_source="header:X-Auth-Token"
            )
        )
        assert result["ok"] is True and result["token_source"] == "header:X-Auth-Token"
        assert server.auth_headers == {"X-Auth-Token": "T0KPEN"}
        assert "token_type: header:X-Auth-Token" in result["sut_config_auth_snippet"]

    def test_expires_in_path_number_required(self) -> None:
        server, _ = self._did_login(
            lambda r: httpx.Response(200, json={"token": "T0KPEN", "expires_in": 3600})
        )
        ok = _run(server.declare_token("SUT", token_path="token", expires_in_path="expires_in"))
        assert ok["ok"] is True
        assert "expires_in_path: expires_in" in ok["sut_config_auth_snippet"]
        bad = _run(server.declare_token("SUT", token_path="token", expires_in_path="token"))
        assert "未命中数值型字段" in bad["error"]

    def test_unknown_source_rejected(self) -> None:
        server, _ = self._did_login(lambda r: httpx.Response(200, json={"token": "T"}))
        result = _run(server.declare_token("SUT", token_path="token", token_source="session"))
        assert "Bearer" in result["error"] and "cookie" in result["error"]

    def test_declared_ref_request_returns_masked_raw(self) -> None:
        """值回流条件化双态闭环：声明前只回结构树；声明后重测同接口，原文回流
        （token 值已知名、掩得住），业务字段照常可见。"""
        server, _ = self._server(
            lambda r: httpx.Response(200, json={"token": "T0KPEN", "user": "someone"})
        )
        first = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert "T0KPEN" not in json.dumps(first)  # 未声明：值不回流
        assert "token" in first["evidence"]  # 结构树指路
        declared = _run(server.declare_token("SUT", token_path="token"))
        assert declared["ok"] is True
        second = _run(server.request("POST", _LOGIN_URL, body=_LOGIN_BODY, ref="SUT"))
        assert second["status"] == 200  # 2xx 组合不入锁
        assert "T0KPEN" not in second["evidence"] and "•••" in second["evidence"]  # 掩码回流
        assert "someone" in second["evidence"]  # 业务字段照常可见


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

    def test_probed_hosts_recorded_for_commit_gate(self) -> None:
        """探测过的 host 记录供落盘门禁（agent_protocol 通道必须出自实测证据）。"""
        server = _make()
        assert server.protocol_hosts == set()
        _run(server.probe_protocol("https://sut.example.com"))
        assert server.protocol_hosts == {"sut.example.com"}

    def test_redirect_is_not_protocol_evidence(self) -> None:
        """事实质量：3xx 重定向不是端点存在的证据（页面服务/catch-all 常见，
        曾被 status<400 记成 ✅ 误导 Agent 声明 agent_protocol）。"""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/threads":
                return httpx.Response(200, json={"thread_id": "t1"}, request=request)
            if request.url.path.endswith("/commands"):
                return httpx.Response(301, headers={"location": "/web/"}, request=request)
            return httpx.Response(200, json={}, request=request)

        server = _make(http_client_factory=_transport(handler))
        result = _run(server.probe_protocol("https://sut.example.com"))
        cmd = next(m for m in result["matrix"] if m["step"] == "send_command")
        assert cmd["ok"] is False and "重定向" in cmd["note"]
        assert server.verified_protocol("sut.example.com")["steps"]["send_command"] is False

    def test_stream_redirect_is_not_evidence(self) -> None:
        """B4：stream 端点与其余端点同红线——3xx 重定向不记 ✅（旧实现
        status<400 把重定向误计为存在，同一矩阵内自相矛盾）。"""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/threads":
                return httpx.Response(200, json={"thread_id": "t1"}, request=request)
            if "/stream" in request.url.path:
                return httpx.Response(302, headers={"location": "/web/"}, request=request)
            return httpx.Response(200, json={}, request=request)

        server = _make(http_client_factory=_transport(handler))
        result = _run(server.probe_protocol("https://sut.example.com"))
        stream = next(m for m in result["matrix"] if m["step"] == "stream")
        assert stream["ok"] is False and "重定向" in stream["note"]

    def test_cleanup_failure_visible_in_matrix(self) -> None:
        """B5：写操作收尾失败留痕（临时线程残留被测系统，Agent/用户须可见）。"""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "DELETE":
                raise httpx.ConnectError("cleanup refused")
            return httpx.Response(200, json={"thread_id": "t1"}, request=request)

        server = _make(http_client_factory=_transport(handler))
        result = _run(server.probe_protocol("https://sut.example.com"))
        cleanup = next(m for m in result["matrix"] if m["step"] == "cleanup")
        assert cleanup["ok"] is False and "残留" in cleanup["note"]

    def test_create_thread_404_continues_with_client_uuid(self) -> None:
        """建线程端点失败 ≠ 协议不支持（v3.9 同构）：执行器契约由客户端生成线程
        UUID、首个 run.start 隐式建线程（POST /threads 不在执行路径上）——旧实现
        因 POST /threads 404 直接跳过后续端点，把兼容执行器契约的服务误判为
        「不能声明 agent_protocol」（bj33 探测失败的根因）。"""
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(f"{request.method} {request.url.path}")
            return httpx.Response(404, request=request)

        server = _make(http_client_factory=_transport(handler))
        result = _run(server.probe_protocol("https://sut.example.com"))
        assert [m["step"] for m in result["matrix"]] == [
            "create_thread",
            "send_command",
            "get_state",
            "stream",
            "cleanup",
        ]
        assert "隐式建线程" in result["matrix"][0]["note"]
        assert "客户端生成" in result["matrix"][0]["note"]
        assert any(
            c.startswith("POST /threads/") and c.endswith("/commands") for c in calls
        )  # 客户端 UUID 继续实测 commands
        assert not any("//" in c for c in calls)  # 不再对畸形路径发请求
        fact = server.verified_protocol("sut.example.com")
        assert fact["steps"]["create_thread"] is False  # 「探测过但未支持」也是事实
        assert fact["steps"]["send_command"] is False  # 404 服务下的真实结论

    def test_probe_speaks_executor_dialect(self) -> None:
        """信封/消息形态/请求头与执行器单源同构（v3.9）：run.start 信封 +
        LangChain `type: human` 消息（role: user 会被 AG-UI 网关静默丢弃）+
        会话路由头。"""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.method == "POST" and request.url.path == "/threads":
                return httpx.Response(404, request=request)
            return httpx.Response(200, json={"thread_id": "t1"}, request=request)

        server = _make(http_client_factory=_transport(handler))
        _run(server.probe_protocol("https://sut.example.com"))
        cmd = next(r for r in seen if r.url.path.endswith("/commands"))
        body = json.loads(cmd.content)
        assert body["method"] == "run.start"  # 执行器同款 JSON-RPC 信封
        msg = body["params"]["input"]["messages"][0]
        assert msg["type"] == "human" and msg["content"] == "agent-eval-probe"
        assert cmd.headers["makers-conversation-id"] == cmd.url.path.split("/")[2]

    def test_probe_attaches_bearer_from_verified_login(self) -> None:
        """探测请求挂登录实测提取的 Bearer（与执行器 mount_headers 同构——鉴权后
        端点裸探会假阴性）；token 值不回流工具输出。"""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"thread_id": "t1"}, request=request)

        server = _make(http_client_factory=_transport(handler))
        server._store_token("SUT", "T0KPEN")  # noqa: SLF001 — 模拟 declare_token 成功登记
        result = _run(server.probe_protocol("https://sut.example.com"))
        cmd = next(r for r in seen if r.url.path.endswith("/commands"))
        assert cmd.headers["Authorization"] == "Bearer T0KPEN"
        assert "T0KPEN" not in json.dumps(result)

    def test_unauthenticated_failure_next_step_requests_login_first(self) -> None:
        """未鉴权探测失败 → next_step 指向先登录再重探（实测会话：Agent 在登录
        完成前探测协议，对 auth-gated 网关得到静默 404 假阴性后判死两域、放弃
        转抄示例）。矩阵条目须携带 HTTP 状态码。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, request=request)

        server = _make(http_client_factory=_transport(handler))
        result = _run(server.probe_protocol("https://sut.example.com"))
        assert result["authenticated"] is False
        assert "declare_token" in result["next_step"] and "重探" in result["next_step"]
        assert all("status" in m for m in result["matrix"][:3])  # 主步骤携带状态码

    def test_authenticated_failure_next_step_hunts_frontend_evidence(self) -> None:
        """已带 token 仍不通 → next_step 指向前端 JS 真实请求构造，禁止按示例臆造。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, request=request)

        server = _make(http_client_factory=_transport(handler))
        server._store_token("SUT", "T0K")  # noqa: SLF001
        result = _run(server.probe_protocol("https://sut.example.com"))
        assert result["authenticated"] is True
        assert "search_content" in result["next_step"]
        assert "示例" in result["next_step"]

    def test_auth_rejected_next_step_points_to_credential(self) -> None:
        """携带 token 被拒（401/403）→ next_step 指向账号权限/重新录入凭证。"""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/commands"):
                return httpx.Response(403, json={"detail": "forbidden"}, request=request)
            return httpx.Response(200, json={"thread_id": "t1"}, request=request)

        server = _make(http_client_factory=_transport(handler))
        server._store_token("SUT", "T0K")  # noqa: SLF001
        result = _run(server.probe_protocol("https://sut.example.com"))
        assert result["authenticated"] is True
        assert "权限" in result["next_step"] and "凭证" in result["next_step"]

    def test_param_rejected_next_step_announces_endpoint_found(self) -> None:
        """带 token 得 400（缺业务参数）→ next_step 宣布端点已找到并指引补
        configurable（实测：正确网关缺 modelId 时回 400「必须指定模型(modelId)」，
        补参重探即 2xx——把它当「协议不支持」会把已找到的端点判死）。"""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/commands"):
                return httpx.Response(400, json={"error": "必须指定模型(modelId)"}, request=request)
            return httpx.Response(200, json={"thread_id": "t1"}, request=request)

        server = _make(http_client_factory=_transport(handler))
        server._store_token("SUT", "T0K")  # noqa: SLF001
        result = _run(server.probe_protocol("https://sut.example.com"))
        assert result["authenticated"] is True
        assert "已找到" in result["next_step"] and "configurable" in result["next_step"]
        cmd = next(m for m in result["matrix"] if m["step"] == "send_command")
        assert "必须指定模型" in cmd["note"]  # 失败条目携带响应体摘录（不再只给状态码）

    def test_configurable_replay_passes_gate(self) -> None:
        """带 configurable 重探（v3.13，修复落盘门禁死锁）：网关要求业务参数
        （实测 bj33 必须指定 modelId）时，裸探测 send_command 永 400 → 账本永远
        记不到核心端点 ✅ → 配置完全正确也会被对账门禁打回。probe_protocol 接受
        configurable 后，「写配置 → 带参探测一次通过」成为可能——信封参数走
        params.config.configurable（执行器同款下发路径）。"""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/commands"):
                body = json.loads(request.content)
                if body["params"].get("config", {}).get("configurable", {}).get("modelId"):
                    return httpx.Response(200, json={"run_id": "r1"}, request=request)
                return httpx.Response(400, json={"error": "必须指定模型(modelId)"}, request=request)
            return httpx.Response(200, json={"thread_id": "t1"}, request=request)

        server = _make(http_client_factory=_transport(handler))
        server._store_token("SUT", "T0K")  # noqa: SLF001

        bare = _run(server.probe_protocol("https://sut.example.com"))
        bare_cmd = next(m for m in bare["matrix"] if m["step"] == "send_command")
        assert bare_cmd["ok"] is False  # 裸探被拒：账本记不到 ✅（死锁面）
        assert "configurable" in bare["next_step"]

        replay = _run(
            server.probe_protocol("https://sut.example.com", configurable={"modelId": "19"})
        )
        replay_cmd = next(m for m in replay["matrix"] if m["step"] == "send_command")
        assert replay_cmd["ok"] is True and replay_cmd["status"] == 200
        steps = server.verified_protocol("sut.example.com")["steps"]
        assert steps["send_command"] is True  # 核心端点 ✅ 入账本 → 对账门禁可过

    def test_configurable_reaches_envelope(self) -> None:
        """configurable 下发位置与执行器一致：params.config.configurable（单源
        run_start_envelope——探测与执行同构造，永不漂移）。"""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"thread_id": "t1"}, request=request)

        server = _make(http_client_factory=_transport(handler))
        _run(server.probe_protocol("https://sut.example.com", configurable={"modelId": "19"}))
        cmd = next(r for r in seen if r.url.path.endswith("/commands"))
        body = json.loads(cmd.content)
        assert body["params"]["config"]["configurable"] == {"modelId": "19"}
        assert body["method"] == "run.start"


# ── request：门控请求原语（抓取 + 接口调试同一出口，跨平台无 shell） ──


class TestRequestPrimitives:
    def test_raw_response_surfaced(self) -> None:
        """裸请求原语的价值：原始状态/响应头/响应体可见——聚合工具的矩阵摘要
        会截掉的信息（405 的 Allow 头、业务错误消息、重定向 Location）这里直读。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                405, headers={"allow": "POST"}, text="Cannot GET /threads/x/stream", request=request
            )

        server = _make(http_client_factory=_transport(handler))
        result = _run(server.request("GET", "https://sut.example.com/threads/x/stream"))
        assert result["status"] == 405
        assert result["headers"]["allow"] == "POST"
        assert "Cannot GET" in result["evidence"]

    def test_post_body_sent_as_is_with_default_content_type(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"run_id": "r1"}, request=request)

        server = _make(http_client_factory=_transport(handler))
        envelope = '{"id":1,"method":"run.start"}'
        result = _run(
            server.request("post", "https://sut.example.com/threads/t/commands", body=envelope)
        )
        assert result["status"] == 200
        req = seen[0]
        assert req.headers["content-type"] == "application/json"  # 缺省补齐
        assert json.loads(req.content) == json.loads(envelope)  # body 原样直发

    def test_host_boundary_and_header_guards(self) -> None:
        server = _make()
        assert "未获用户授权" in _run(server.request("GET", "https://evil.example.com/x"))["error"]
        # 凭证旁路：Authorization/Cookie 禁手传（token 由服务端自动挂载，不经 LLM）
        result = _run(
            server.request("GET", "https://sut.example.com/x", headers="Authorization: Bearer x")
        )
        assert "禁手传" in result["error"]
        assert (
            "method 仅支持" in _run(server.request("bash -c", "https://sut.example.com"))["error"]
        )
        assert (
            "Key: Value"
            in _run(server.request("GET", "https://sut.example.com", headers="NoColon"))["error"]
        )

    def test_session_token_mounted_and_masked(self) -> None:
        """登录 token 自动挂载到裸请求（与执行器同构）；响应回显的 token 值掩码不回流。"""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"token": "T0KPEN", "echo": "T0KPEN"}, request=request)

        server = _make(http_client_factory=_transport(handler))
        server._store_token("SUT", "T0KPEN")  # noqa: SLF001
        result = _run(server.request("GET", "https://sut.example.com/me"))
        assert seen[0].headers["Authorization"] == "Bearer T0KPEN"  # 自动挂载
        assert "T0KPEN" not in json.dumps(result)  # 响应体里的 token 值已掩码

    def test_unauthenticated_401_distinguished_with_auth_attached(self) -> None:
        """B2：401/403 回显 auth_attached——未挂鉴权的被拒不构成接口无效结论
        （v3.11 教训在裸请求原语的同源补齐，两种失败 next_step 相反）。"""

        def unauthorized(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "auth"}, request=request)

        server = _make(http_client_factory=_transport(unauthorized))
        result = _run(server.request("POST", "https://sut.example.com/api/chat"))
        assert result["auth_attached"] is False
        assert (
            "未携带鉴权" in result["next_step"]
            and "declare_token" in result["next_step"]
            and "request(ref" in result["next_step"]
        )

        server._store_token("SUT", "T0KPEN")  # 登录成功后 token 服务端持有
        result2 = _run(server.request("POST", "https://sut.example.com/api/chat"))
        assert result2["auth_attached"] is True
        assert "未携带鉴权" not in result2.get("next_step", "")

    def test_get_fetch_semantics_cached_and_guided(self) -> None:
        """GET = 抓取（原 probe_url 语义）：完整体入缓存可检索；脚本响应带
        cached_bytes/search_hint；GET 404 带 POST-only 语义指引（不逐路径猜）。"""
        js_headers = {"content-type": "application/javascript"}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/app.js":
                return httpx.Response(200, text="window.cfg=1", headers=js_headers, request=request)
            return httpx.Response(404, text="Cannot GET /", request=request)

        server = _make(http_client_factory=_transport(handler))
        fetched = _run(server.request("GET", "https://sut.example.com/app.js"))
        assert fetched["cached_bytes"] > 0 and "search_hint" in fetched
        assert _run(server.search_content("cfg"))["matches"]
        not_found = _run(server.request("GET", "https://sut.example.com/missing"))
        assert "POST 实测" in not_found["next_step"]
        assert "discover_login" in not_found["next_step"] and "逐路径" in not_found["next_step"]

    def test_budget_pool_registered(self) -> None:
        """预算分池必须登记（漏登记 = 该工具无轮内上限）。"""
        assert "request" in TOOL_BUDGETS


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
        """预算按工具分池：request 打满不牵连 discover_login（预算饿死发现链的实测教训）。"""
        server = _make()
        for _ in range(TOOL_BUDGETS["request"]):
            result = _run(server.request("GET", "https://sut.example.com/x"))
            assert result["status"] == 200
        error = _run(server.request("GET", "https://sut.example.com/x"))["error"]
        assert "上限" in error and "未经验证" in error  # 拒绝时指引继续验证而非收尾
        page = _run(server.discover_login("https://sut.example.com/web/login"))
        assert "error" not in page  # 独立预算池——发现工具不受 request 牵连
        server.new_turn()  # WorkbenchAgent.turn() 每轮调用
        assert _run(server.request("GET", "https://sut.example.com/x"))["status"] == 200

    def test_search_budget_independent_pool(self) -> None:
        server = _make()
        server._cache_content("https://sut.example.com/x.js", "abc")  # noqa: SLF001
        for _ in range(TOOL_BUDGETS["search_content"]):
            assert "matches" in _run(server.search_content("a"))
        assert "上限" in _run(server.search_content("a"))["error"]


# ── WorkbenchAgent 集成（工具注册与预算挂点） ─────────────────────────


class TestWorkbenchAgentIntegration:
    def test_probe_tools_registered(self, tmp_path: Path) -> None:
        from agent_eval.agent.workbench_agent import WorkbenchAgent

        agent = WorkbenchAgent(tmp_path)
        described = agent._describe_tools()  # noqa: SLF001 — 单测内省
        for name in (
            "request",
            "discover_login",
            "search_content",
            "probe_protocol",
            "declare_token",
            "ask_user",
        ):
            assert name in described
        assert agent.probe.credentials is not None
        assert agent.probe.log_path == agent._log_path  # noqa: SLF001 — 证据随会话日志

    def test_turn_resets_probe_budget(self, tmp_path: Path) -> None:
        from agent_eval.agent.workbench_agent import WorkbenchAgent

        agent = WorkbenchAgent(tmp_path)
        agent.probe._turn_calls["request"] = TOOL_BUDGETS["request"]  # noqa: SLF001
        agent.probe.new_turn()
        assert agent.probe._turn_calls.get("request", 0) == 0  # noqa: SLF001
