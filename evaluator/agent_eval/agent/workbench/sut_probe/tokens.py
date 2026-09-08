"""TokenTool — 会话凭证声明式提取（事后声明，不重发请求）。

在服务端缓存的「该 ref 最近一次带凭证请求」上做**事后声明式**提取（不重发请求
就无撞锁风险，声明错了改路径重声明即可）。提取词汇与执行器 SUTSession.mount_headers
三态（Bearer | header:<X> | cookie）同构，snippet 由工具机械渲染（token_type 按
声明——修掉硬编码 Bearer 的宽度裂缝）。

红线：凭证值不回流 LLM 上下文（提取在服务端持有的响应上进行，值只进
session_tokens 与 snippet，不进工具返回）；声明超出执行器宽度的形态（凭证走
请求头、链式认证）显式拒绝——探测可探索、暂不可落盘，不产生假验证。
"""

from __future__ import annotations

import re
from typing import Any

from agent_eval.agent.workbench.sut_probe.context import ProbeContext
from agent_eval.agent.workbench.sut_probe.helpers import key_path_tree, walk_path


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


class TokenTool:
    """工具：declare_token——事后声明式会话凭证提取。"""

    def __init__(self, ctx: ProbeContext) -> None:
        self.ctx = ctx

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
        if budget_err := self.ctx.budget("declare_token"):
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
        fact = self.ctx.last_credential_request.get(ref.lower())
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
        # 执行器宽度守卫：探测可探索、暂不可落盘的形态显式拒绝
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
                walk_path(payload, expires_in_path) if payload is not None else (None, False)
            )
            if not hit or not isinstance(value, (int, float)):
                return {
                    "error": (
                        f"expires_in_path={expires_in_path!r} 未命中数值型字段——可选参数，"
                        "可去掉或按 response_key_paths 修正"
                    ),
                    "response_key_paths": key_path_tree(payload) if payload is not None else "",
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
                    err["response_key_paths"] = key_path_tree(payload)
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
                        "response_key_paths": key_path_tree(payload),
                    }
                return {
                    "error": (
                        "缺少 token_path，且该响应不是 JSON（无法按路径提取）——"
                        "若凭证在 Set-Cookie 里，改用 token_source=cookie:<名字>"
                    )
                }
            token_value, hit = (
                walk_path(payload, token_path) if payload is not None else (None, False)
            )
            effective_path = token_path
            if not hit:
                return {
                    "error": (
                        f"token_path={token_path!r} 未命中响应结构——声明错了改路径重声明"
                        "即可（不重发请求）；以 response_key_paths 键路径树为准"
                    ),
                    "response_key_paths": key_path_tree(payload) if payload is not None else "",
                }
        # 成功：token 服务端持有（自动挂载）；cookie 型落共享 client 的 jar
        # （Set-Cookie 场景登录请求本就发自此 client，jar 已持有——显式 set 幂等）
        self.ctx.store_token(ref, str(token_value), source)
        if source == "cookie":
            client = await self.ctx.client()
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
        self.ctx.record_login(
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
        self.ctx.log(
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
            value, hit = walk_path(payload, token_path)
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
