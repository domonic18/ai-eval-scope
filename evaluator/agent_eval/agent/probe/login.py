"""会话凭证声明式提取 + ask_user — 探测面 v4 的提取原语（arch/15 §6.6 / docs/plan/03 §3.3）。

v4 拆解：probe_login 退役——请求面（凭证模板渲染 / 外发授权 / 防锁）归 request
（fetch.py），本模块只剩两件事：
- declare_token：在服务端缓存的「该 ref 最近一次带凭证请求」上做**事后声明式**
  提取（决策 D2：不重发请求就无撞锁风险，声明错了改路径重声明即可）。提取词汇
  与执行器 SUTSession.mount_headers 三态（Bearer | header:<X> | cookie）同构，
  snippet 由工具机械渲染（token_type 按声明——修掉 v3.x 硬编码 Bearer 的宽度裂缝）；
- ask_user：文本/单选/凭证三态交互桥（凭证直写密钥区，值不回流）。

红线：凭证值不回流 LLM 上下文（提取在服务端持有的响应上进行，值只进
_session_tokens 与 snippet，不进工具返回）；声明超出执行器宽度的形态（凭证走
请求头、链式认证）显式拒绝——探测可探索、暂不可落盘，不产生假验证（§6）。
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from agent_eval.agent.probe.fetch import _key_path_tree

_MAX_QUESTION_CHARS = 200  # ask_user 单问上限：多问打包会让用户不知从何答起


def _normalize_source(raw: str) -> tuple[str, str]:
    """token_source 归一化为执行器形态，返回 (source, cookie_name)。

    接受 bearer（默认）/ header:<X> / cookie 或 cookie:<名字>；输出与执行器
    SUTSession.token_type 同词汇（"Bearer" | "header:<X>" | "cookie"）。
    无法归一化的形态返回空 source（调用方转纠正错误）。
    """
    s = (raw or "").strip()
    if not s or s.lower() == "bearer":
        return "Bearer", ""
    if s.lower().startswith("header:"):
        name = s.split(":", 1)[1].strip()
        return (f"header:{name}" if name else ""), ""
    if s.lower().startswith("cookie"):
        name = s.split(":", 1)[1].strip() if ":" in s else ""
        return "cookie", name
    return "", ""


def _walk_path(payload: Any, path: str) -> tuple[Any, bool]:
    """点分 + 数字下标路径取值（与执行器 extract_by_path 同语义）。"""
    node = payload
    for part in path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None, False
        if node is None:
            return None, False
    return node, True


def _render_auth_snippet(
    *,
    ref: str,
    method: str,
    url: str,
    template: str,
    token_type: str,
    token_path: str = "",
    expires_in_path: str = "",
) -> str:
    """把声明成功的提取事实渲染为可照抄的 ``auth:`` 段 YAML（词汇与执行器同构）。

    token_type 按声明渲染（Bearer / header:<X> / cookie）；cookie 型自 Set-Cookie
    提取（响应体无路径可指）时落 ``type: session_cookie``——执行器靠共享 client
    的 cookie jar 承载登录态，与探测侧同一机制，语义 1:1。
    """
    import yaml

    login = {"method": method, "path": url, "body_template": template}
    if token_type == "cookie" and not token_path:
        snippet: dict[str, Any] = {
            "auth": {"type": "session_cookie", "credential_ref": ref, "login": login}
        }
    else:
        extract: dict[str, str] = {"token_path": token_path, "token_type": token_type}
        if expires_in_path:
            extract["expires_in_path"] = expires_in_path
        snippet = {
            "auth": {
                "type": "api_login",
                "credential_ref": ref,
                "login": login,
                "extract": extract,
            }
        }
    return yaml.safe_dump(snippet, allow_unicode=True, sort_keys=False).strip()


class LoginMixin:
    """工具：declare_token（事后声明式凭证提取）与 ask_user（三态交互桥）。

    协作契约注解：宿主提供 ``_budget/_client/_log``、凭证库（``credentials``）、
    交互桥（``ask_fn``）、防锁与证据账本设施、最近带凭证请求事实
    （``_last_credential_request``）——类级注解仅供类型检查，运行时不创建属性。
    """

    _budget: Callable[[str], dict[str, str] | None]
    _client: Callable[[], Awaitable[Any]]
    _log: Callable[..., None]
    credentials: Any  # CredentialStore（secrets 直写，值不回流）
    ask_fn: Any  # async (question, *, options, secret) -> str | None
    _login_tried: set[tuple[str, str, str]]
    _store_token: Callable[[str, str, str], None]
    _record_login: Callable[[dict[str, str]], None]
    verified_login: Callable[[str], dict[str, str] | None]
    _last_credential_request: dict[str, dict[str, Any]]
    _step_responses: dict[str, Any]

    async def declare_token(
        self,
        ref: str,
        token_path: str = "",
        token_source: str = "Bearer",
        expires_in_path: str = "",
    ) -> dict[str, Any]:
        """事后声明式会话凭证提取：在该 ref 最近一次带凭证 2xx 响应上提取。

        入参词汇与执行器同构：token_source 三态（Bearer | header:<X> | cookie）、
        token_path 点分路径（cookie 型为 Set-Cookie 名）。不重发请求——声明错了
        改路径重声明即可（防锁不适用；受轮内预算约束）。
        """
        if budget_err := self._budget("declare_token"):
            return budget_err
        ref = ref.strip()
        source, cookie_name = _normalize_source(token_source)
        if not source:
            return {
                "error": (
                    "token_source 需为执行器三态之一：Bearer | header:<HeaderName> | "
                    f"cookie[:名字]（收到 {token_source!r}）"
                )
            }
        fact = self._last_credential_request.get(ref.lower())
        if fact is None:
            return {
                "error": (
                    f"ref={ref!r} 没有已登记的带凭证请求——先用 request(ref={ref!r}, "
                    "body=…) 实测登录接口；缺凭证字段时按错误提示先 ask_user"
                    "(kind=credential) 逐字段录入"
                )
            }
        if fact["status"] >= 400:
            return {
                "error": (
                    f"ref={ref!r} 最近一次带凭证请求是 HTTP {fact['status']}（未成功）"
                    "——declare 只对 2xx 响应声明提取。按请求返回的证据修正 body/地址后"
                    "重新 request（防锁：被拒组合不自动重发，新 body 即新组合）"
                )
            }
        # 执行器宽度守卫（§6）：探测可探索、暂不可落盘的形态显式拒绝
        if fact.get("credential_in_headers"):
            return {
                "error": (
                    "该请求把凭证放在请求头（headers 模板变量）——执行器 api_login 当前"
                    "只支持 body 携带凭证，该形态暂不可声明落盘（auth_chain 多步能力"
                    "落地前）。可继续探索，但勿把它写成 auth: 段；或与用户确认改用"
                    " body 携带凭证的登录接口"
                )
            }
        if fact.get("used_chain"):
            return {
                "error": (
                    "该请求引用了链式变量（{{ stepN.… }}）——多步认证链的落盘形态"
                    "（auth_chain）尚未落地，暂不可声明落盘。单步登录接口请直接"
                    " request(body=带凭证模板) 实测后声明"
                )
            }
        payload = fact.get("response_json")
        token_path = re.sub(r"^\$\.?", "", str(token_path or "").strip())
        expires_in_path = re.sub(r"^\$\.?", "", str(expires_in_path or "").strip())
        expires_note = ""
        if expires_in_path:
            value, hit = (
                _walk_path(payload, expires_in_path) if payload is not None else (None, False)
            )
            if not hit or not isinstance(value, (int, float)):
                return {
                    "error": (
                        f"expires_in_path={expires_in_path!r} 未命中数值型字段——可选参数，"
                        "可去掉或按 response_key_paths 修正"
                    ),
                    "response_key_paths": _key_path_tree(payload) if payload is not None else "",
                }
            expires_note = "expires_in_path 已声明（对齐执行器 AuthExtractConfig）"
        # 提取：cookie 型优先 Set-Cookie（token_path 即 cookie 名），其余走响应 JSON
        if source == "cookie":
            token_value, cookie_key, effective_path, extract_err = self._extract_cookie(
                fact, cookie_name, token_path, payload
            )
            if extract_err:
                err: dict[str, Any] = {"error": extract_err}
                if payload is not None:
                    err["response_key_paths"] = _key_path_tree(payload)
                return err
        else:
            if payload is None:
                return {
                    "error": (
                        "该响应不是 JSON，无法按路径提取——若凭证在 Set-Cookie 里，"
                        "改用 token_source=cookie:<名字>"
                    )
                }
            if not token_path:
                if payload is not None:
                    return {
                        "error": (
                            "缺少 token_path：点分路径从登录响应 JSON 中取凭证"
                            "（数组用数字下标，如 data.0.token）——按 response_key_paths 选择"
                        ),
                        "response_key_paths": _key_path_tree(payload),
                    }
                return {
                    "error": (
                        "缺少 token_path，且该响应不是 JSON（无法按路径提取）——"
                        "若凭证在 Set-Cookie 里，改用 token_source=cookie:<名字>"
                    )
                }
            token_value, hit = (
                _walk_path(payload, token_path) if payload is not None else (None, False)
            )
            effective_path = token_path
            if not hit:
                return {
                    "error": (
                        f"token_path={token_path!r} 未命中响应结构——声明错了改路径重声明"
                        "即可（不重发请求）；以 response_key_paths 键路径树为准"
                    ),
                    "response_key_paths": _key_path_tree(payload) if payload is not None else "",
                }
        # 成功：token 服务端持有（自动挂载）；cookie 型落共享 client 的 jar
        # （Set-Cookie 场景登录请求本就发自此 client，jar 已持有——显式 set 幂等）
        self._store_token(ref, str(token_value), source)
        if source == "cookie":
            client = await self._client()
            client.cookies.set(cookie_key, str(token_value))
        snippet = _render_auth_snippet(
            ref=ref,
            method=fact["method"],
            url=fact["url"],
            template=fact["body_template"],
            token_type=source,
            token_path=effective_path,
            expires_in_path=expires_in_path,
        )
        # 证据账本（机械登记，不经 LLM 转述）：落盘对账门禁的事实源
        self._record_login(
            {
                "ref": ref,
                "method": fact["method"],
                "url": fact["url"],
                "body_template": fact["body_template"],
                "token_path": effective_path,
                "token_source": source,
                "expires_in_path": expires_in_path,
                "auth_snippet": snippet,
            }
        )
        self._log(
            "declare_token",
            ref=ref,
            source=source,
            token_path=effective_path,
            via_set_cookie=source == "cookie" and not effective_path,
        )
        return {
            "ok": True,
            "token_source": source,
            "token_path": effective_path,
            "note": "会话凭证已服务端持有并随请求自动挂载（值不在本返回中）"
            + (f"；{expires_note}" if expires_note else ""),
            "sut_config_auth_snippet": snippet,
            "next_step": (
                "把返回的 sut_config_auth_snippet **原样**写进 sut_configs 的 auth: 段"
                "（勿拆分 URL、勿增删字段；凭证仅 credential_ref 引用）；若协议探测曾在"
                "登录成功前失败（authenticated: false），现在重探 probe_protocol"
                "（凭证已自动挂载）"
            ),
        }

    def _extract_cookie(
        self, fact: dict[str, Any], cookie_name: str, token_path: str, payload: Any
    ) -> tuple[str, str, str, str]:
        """cookie 型提取：优先 Set-Cookie 按名取（token_path 即 cookie 名），否则响应体。

        返回 (token_value, cookie 名, 生效路径, 错误)——自 Set-Cookie 提取时生效
        路径为空串（落 session_cookie 形态）；响应体提取时为点分路径
        （落 api_login + extract.token_type=cookie，cookie 名须显式给出）。
        """
        set_cookies: dict[str, str] = fact.get("set_cookies") or {}
        name = cookie_name or token_path
        if not name and len(set_cookies) == 1:
            name = next(iter(set_cookies))  # 唯一 cookie 机械取用，零字段名假设
        if name and name in set_cookies:
            return set_cookies[name], name, "", ""
        # 不在 Set-Cookie：尝试响应体（token_path 为点分路径；cookie 名须显式）
        if cookie_name and token_path and payload is not None:
            value, hit = _walk_path(payload, token_path)
            if hit:
                return str(value), cookie_name, token_path, ""
        available = (
            f"响应 Set-Cookie 名单: {sorted(set_cookies)}" if set_cookies else "响应无 Set-Cookie"
        )
        if not name:
            return (
                "",
                "",
                "",
                f"cookie 型需指明 cookie 名：token_source=cookie:<名字>，或 token_path "
                f"传 cookie 名。{available}",
            )
        hint = (
            f"cookie {name!r} 不在 Set-Cookie 名单（{available}）；若凭证在响应体中，"
            "用 token_source=cookie:<名字> 显式命名并给 token_path"
        )
        return "", "", "", hint

    async def ask_user(
        self,
        question: str,
        options: str = "",
        kind: str = "text",
        ref: str = "",
        field: str = "",
        desc: str = "",
    ) -> dict[str, Any]:
        if self.ask_fn is None:
            return {
                "error": "非交互环境（--yes/CI），ask_user 不可用；请引导用户在交互终端运行或预先 secrets set"
            }
        if len(question) > _MAX_QUESTION_CHARS:
            return {
                "error": (
                    f"问题过长（{len(question)} 字，上限 {_MAX_QUESTION_CHARS}）：一次只问一个问题，"
                    "需要多项信息请拆成多次 ask_user 逐个询问"
                )
            }
        try:
            opts = [o.strip() for o in options.split("|") if o.strip()] if options else None
            if kind == "credential":
                if not (ref and field):
                    return {"error": "kind=credential 需要 ref 与 field 参数"}
                # 一次只录一个字段：多字段打包会整串存成一个键名，request 渲染时
                # 逐字段查不到（实测 Agent 曾传 field="username,password"）
                if len(field.split()) != 1 or any(c in field for c in ",，、;；/"):
                    return {
                        "error": (
                            f"field 一次只接受一个字段名（收到 {field!r}）；"
                            "请逐字段分别调用 ask_user(kind=credential)，每次录一个字段"
                        )
                    }
                # 字段实际含义由 Agent 经 desc 传入（分析完前端包后它最清楚该字段
                # 承载的是密码还是验证码——逐站点知识不写死在代码里）；缺失会让
                # 用户面对「不知道该输入什么」的提示
                if not desc.strip():
                    return {
                        "error": (
                            "kind=credential 需要 desc：用一句话向用户说明该字段实际要输入什么"
                            "（从你的检索摘录/接口语义得出，如该字段实际承载的是密码还是验证码）"
                        )
                    }
                value = await self.ask_fn(
                    f"【录入 {ref} 的凭证字段 {field}】\n"
                    f"该字段是什么：{desc.strip()}\n"
                    "用途：向登录接口发送实测请求需要它；输入内容不会回显，输入后回车提交",
                    options=None,
                    secret=True,
                )
                if not value:
                    return {"aborted": True, "note": "用户未输入，凭证未保存"}
                return self._save_credential(ref, field, value)
            # 单选项无选择意义：降级为文本输入（防「假单选」困惑）
            if opts is not None and len(opts) < 2:
                opts = None
            answer = await self.ask_fn(question, options=opts, secret=False)
            return {"answer": answer or ""}
        except Exception as e:  # noqa: BLE001 — 交互桥异常转错误数据
            return {"error": f"ask_user 失败: {e}"}

    def _save_credential(self, ref: str, field: str, value: str) -> dict[str, Any]:
        """凭证直写密钥区（合并保存，0600）；值只进 secrets store 不进返回值。"""
        from agent_eval.execution.auth.secrets_store import load_secrets_file, save_secrets_file

        secrets = load_secrets_file(None)
        bucket = next((k for k in secrets if k.upper() == ref.upper()), ref)
        secrets.setdefault(bucket, {})[field.lower()] = value
        save_secrets_file(secrets, None)
        # 新凭证录入解锁该 ref 的防锁：一次录入换一次实测
        # （重试循环被「必须经用户录入」天然限流）
        self._login_tried = {k for k in self._login_tried if k[0] != ref.lower()}
        self._log("ask_user", event="credential_saved", ref=ref, field=field)
        return {
            "saved": True,
            "ref": ref,
            "field": field.lower(),
            "note": "凭证已入密钥区，不会出现在对话中",
        }
