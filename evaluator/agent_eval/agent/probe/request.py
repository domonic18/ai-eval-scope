"""RequestTool — 门控请求原语 request：抓取与接口调试（含登录实测）同一出口。

薄原语 + 厚思考——请求构造的格式多样性（任意 method/headers/body 模板、多步链）
交 Agent；代码只保留门禁（host 边界 / 凭证外发授权 / 防锁）与值保管（凭证与链式
值服务端注入，值不经对话；响应按值回流条件化呈现）。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from agent_eval.agent.probe.context import ProbeContext
from agent_eval.agent.probe.helpers import host_of, mask_secrets
from agent_eval.agent.probe.response import structure_response

# request：跨平台无 shell（httpx 直发，Windows/mac/linux 一致）；
# 鉴权头禁手传——会话凭证由服务端自动挂载，凭证不经 LLM 上下文
_HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
_FORBIDDEN_HEADERS = ("authorization", "cookie")
_MAX_HEADERS = 10
# 渲染后残留占位符（${var} 等 shell 风格）一律拒发——实测事故：${phone} 原样发出，
# 服务端报「格式不是手机号」被误读为用户输入错误。守卫的是本工具的模板渲染语义
# （与 StrictUndefined 同类），不是对 SUT 报文格式的假设
_UNRENDERED_PLACEHOLDER_RE = re.compile(r"\$\{[^}]*\}")


class RequestTool:
    """工具：门控请求原语 request（GET=抓取 / 非 GET=接口调试）。"""

    def __init__(self, ctx: ProbeContext) -> None:
        self.ctx = ctx

    def _render_template(
        self, sources: list[str], ref: str
    ) -> tuple[dict[str, str], list[str], list[str], list[str]]:
        """渲染 body/headers 模板（StrictUndefined）：凭证字段服务端注入 + 链式变量。

        返回（渲染结果 dict（与 sources 同序）, 凭证字段, 已用链式步骤, 缺录字段）。
        渲染上下文 = 已声明步骤的响应 JSON（``{{ stepN.路径 }}``，值服务端流动不经
        对话）+ ref 的凭证字段值（``{{ 字段 }}``，密钥区直读）。模板变量三分类是
        机械判定（find_undeclared_variables 只回根名）——命中已声明步骤名 → 链式
        变量；其余一律视为 ref 的凭证字段（零字段名白名单：字段存在性由密钥区
        回答，不在密钥区的进「缺录」由调用方转纠正提示）。StrictUndefined（jinja2
        默认 Undefined 静默渲染空串——拼错变量发出空参请求是本原语必须消灭的
        静默失败）。
        """
        from jinja2 import Environment, StrictUndefined, Template, meta

        known_steps = set(self.ctx.step_responses)
        cred_fields: set[str] = set()
        step_vars: set[str] = set()
        for src in sources:
            if not (src and "{" in src and "}" in src):
                continue
            for name in meta.find_undeclared_variables(Environment().parse(src)):
                (step_vars if name in known_steps else cred_fields).add(name)
        values: dict[str, str] = {}
        for field in sorted(cred_fields):
            value = (
                self.ctx.credential_store.get(ref, field)
                if self.ctx.credential_store is not None
                else None
            )
            if value is not None:
                values[field] = value
        missing = sorted(cred_fields - set(values))
        if missing:
            # 缺录先于渲染返回——StrictUndefined 会把同一问题以模板异常形态抛出，
            # 抢在友好纠错（ask_user 指引）之前变成「渲染失败」误导排查方向
            return {}, sorted(cred_fields), sorted(step_vars), missing
        context: dict[str, Any] = {**self.ctx.step_responses, **values}
        rendered: dict[str, str] = {}
        for i, src in enumerate(sources):
            rendered[str(i)] = (
                Template(src, undefined=StrictUndefined).render(**context) if src else ""
            )
        return rendered, sorted(cred_fields), sorted(step_vars), missing

    async def request(
        self,
        method: str,
        url: str,
        headers: str = "",
        body: str = "",
        ref: str = "",
        step: str = "",
    ) -> dict[str, Any]:
        """门控请求原语——抓取与接口调试（含登录实测）同一出口。

        - GET 即「抓取入缓存」（完整响应体供 search_content 检索）；非 GET 即接口
          调试（响应头/体直读，405 的 Allow、400 的业务错误消息不再被截掉）；
        - body/headers 支持 Jinja2 模板：凭证变量 ``{{ 字段 }}``（ref 必带，密钥区
          直注入）与链式变量 ``{{ stepN.路径 }}``（引用此前 step 步骤的响应值，
          多步认证链；值全程服务端流动）；
        - 红线面：host 边界逐请求必经；凭证注入请求按 (host, ref) 组合首次外发
          授权一次（预览即同意）、每次外发留痕；防锁按 (ref, url, body)；
        - 值回流条件化：带凭证请求的 2xx 响应在 declare_token 声明提取前只回
          键路径结构（响应可能含会话凭证，值不回流）。
        """
        if budget_err := self.ctx.budget("request"):
            return budget_err
        if host_err := await self.ctx.ensure_host(url):
            return {"error": host_err}
        verb = method.strip().upper()
        if verb not in _HTTP_METHODS:
            return {"error": f"method 仅支持 {_HTTP_METHODS}，得到: {method!r}"}
        if isinstance(body, (dict, list)):
            # LLM 会把 body 写成 JSON 对象而非字符串（jinja2 对 dict 源 parse
            # 兼容 render 才炸，旧文案误导修语法）——dict/list 是唯一有明确
            # 字符串形态的输入：机械序列化（凡可机械传递的变形不经 LLM 转述），
            # 生效模板随账本事实回显
            try:
                body = json.dumps(body, ensure_ascii=False)
            except (TypeError, ValueError) as e:
                return {"error": f"body 无法序列化为模板字符串（{e}）——请传 JSON 文本"}
        raw_headers: list[str] = []
        header_names: list[
            str
        ] = []  # 模板源与 req_headers 的对齐清单（Content-Type 自动补齐不入源）
        req_headers: dict[str, str] = {}
        if headers.strip():
            for pair in headers.split("|"):
                if ":" not in pair:
                    return {"error": f'headers 格式："Key: Value"，多项用 | 分隔——得到: {pair!r}'}
                key, _, value = pair.partition(":")
                key = key.strip()
                if key.lower() in _FORBIDDEN_HEADERS:
                    return {"error": f"{key} 头禁手传：会话凭证已自动挂载（凭证不经 LLM）"}
                if len(req_headers) >= _MAX_HEADERS:
                    return {"error": f"headers 上限 {_MAX_HEADERS} 个"}
                req_headers[key] = value.strip()
                raw_headers.append(f"{key}: {value.strip()}")
                header_names.append(key)
        if body and not any(k.lower() == "content-type" for k in req_headers):
            req_headers["Content-Type"] = "application/json"
        # 模板渲染（StrictUndefined；凭证字段与链式变量在服务端注入）
        try:
            rendered_map, cred_fields, step_vars, missing = self._render_template(
                [body, *raw_headers], ref.strip()
            )
        except Exception as e:  # noqa: BLE001 — 模板语法错误转纠正提示
            return {
                "error": (
                    f"模板渲染失败（{e}）。变量形态：凭证 {{{{ 字段 }}}}（需带 ref 参数）；"
                    "链式 {{{{ stepN.路径 }}}}（stepN 须是此前 request(step=…) 声明过的步骤）"
                )
            }
        if missing:
            ref_hint = (
                f"ref={ref!r}" if ref.strip() else "本请求带了模板变量但未带 ref（凭证注入必须带）"
            )
            return {
                "error": (
                    f"变量 {missing} 不在密钥区（{ref_hint}）。若是凭证字段："
                    f"ask_user(kind=credential, ref=…, field=<字段名>) 逐个录入；"
                    "若是链式变量：须先用 request(step=…) 声明来源步骤（链式变量以声明的"
                    "步骤名为根，如 {{{{ step1.data.token }}}}）"
                )
            }
        rendered_body = rendered_map["0"]
        # 渲染值必须压过 req_headers 的模板原文（原文含 {{ 变量 }}，直发即泄漏）
        rendered_headers = {k: rendered_map[str(i + 1)] for i, k in enumerate(header_names)}
        cred_in_headers = any(f in h for h in raw_headers for f in cred_fields)
        if residual := _UNRENDERED_PLACEHOLDER_RE.findall(rendered_body):
            return {
                "error": (
                    f"body 渲染后仍残留占位符 {residual[:3]}——请求未发送。变量写 Jinja2 形态"
                    " {{{{ 字段 }}}}（凭证字段配 ref；链式变量以声明过的 step 名为根）"
                )
            }
        # 凭证注入请求的门禁面（非凭证请求只过 host 门禁）
        if cred_fields:
            if not ref.strip():
                return {
                    "error": (
                        f"body/headers 含凭证变量 {cred_fields}——凭证由服务端从密钥区注入，"
                        "需带 ref 参数（与包的 credential_ref 同值）；纯链式步骤引用则无需 ref"
                    )
                }
            host = host_of(url)
            # 组合级凭证外发授权：同 (host, ref) 首次外发前确认一次；预览展示
            # 模板原文——占位符形态天然不含凭证值（值在服务端注入，不落对话）
            if (host, ref.lower()) not in self.ctx.credential_grants:
                if self.ctx.ask_fn is None:
                    return {"error": "非交互环境不外发凭证；请以交互模式运行，由用户确认授权"}
                answer = await self.ctx.ask_fn(
                    f"即将向 {host} 外发凭证（ref={ref}，字段 {cred_fields}，值经服务端注入"
                    "不显示）。授权后本会话向该 host 以该 ref 外发不再逐次确认（每次外发留痕）。\n"
                    f"  {verb} {url}\n  body: {body or '（无）'}\n确认授权？",
                    options=["允许", "取消"],
                    secret=False,
                )
                if not answer or "允许" not in answer:
                    self.ctx.log("request", event="credential_grant_denied", host=host, ref=ref)
                    return {"aborted": True, "note": "用户未授权凭证外发，未发送"}
                self.ctx.credential_grants.add((host, ref.lower()))
                self.ctx.log("credential_grant", host=host, ref=ref, fields=cred_fields)
            # 防锁：同 (ref, url, body) 组合被认证层拒绝过（4xx/5xx）不自动重发
            if (ref.lower(), url, body) in self.ctx.login_tried:
                return {
                    "error": (
                        "该接口与字段组合已被认证层拒绝过（防锁红线：4xx/5xx 拒绝的组合"
                        "不自动重发，防真实系统撞锁）。改动地址或 body 即为新组合；"
                        "2xx 响应的组合不入锁——declare_token 声明/修正提取不重发请求"
                    )
                }
        started = time.monotonic()
        try:
            client = await self.ctx.client()
            response = await client.request(
                verb,
                url,
                headers={**req_headers, **rendered_headers, **self.ctx.auth_headers},
                content=rendered_body.encode() if rendered_body else None,
            )
        except Exception as e:  # noqa: BLE001 — 网络面异常统一转错误数据
            self.ctx.log("request", method=verb, url=url, event="failed", error=str(e)[:200])
            return {"status": 0, "error": f"请求失败: {e}"}
        elapsed_ms = round((time.monotonic() - started) * 1000)
        status = response.status_code
        # 防锁红线（认证层拒绝语义）：带凭证组合被 4xx/5xx 拒绝即入锁不自动重发；
        # 404 = 请求未到认证层不入锁（探索不误伤），2xx/网络失败同不入锁
        if cred_fields and status >= 400 and status != 404:
            self.ctx.login_tried.add((ref.lower(), url, body))
        # 链式步骤登记（值服务端持有，只进渲染上下文不进返回）
        if step.strip():
            try:
                self.ctx.step_responses[step.strip()] = response.json()
            except Exception:  # noqa: BLE001 — 非 JSON 步骤存文本形态
                self.ctx.step_responses[step.strip()] = {"text": response.text}
        tokens = [v.get("token", "") for v in self.ctx.session_tokens.values()]
        # 凭证请求事实登记（declare_token 的事实源；值全部服务端保管，不经返回回流）
        if cred_fields:
            try:
                response_json: Any = response.json()
            except Exception:  # noqa: BLE001 — 非 JSON 响应存 None，提取走文本形态
                response_json = None
            self.ctx.last_credential_request[ref.lower()] = {
                "ref": ref,
                "method": verb,
                "url": url,
                "body_template": body,
                "credential_in_headers": cred_in_headers,
                "used_chain": bool(step_vars),
                "status": status,
                "response_text": response.text,
                "response_json": response_json,
                # set-cookie 名值对（必须 get_list，.get 会把多个 cookie 逗号合并）
                "set_cookies": {
                    pair.split("=", 1)[0].strip(): pair.split("=", 1)[1].split(";")[0].strip()
                    for pair in response.headers.get_list("set-cookie")
                    if "=" in pair
                },
            }
        self.ctx.log("request", method=verb, url=url, status=status, ref=ref, step=step)
        return structure_response(
            self.ctx,
            verb,
            url,
            response,
            elapsed_ms,
            masked_text=mask_secrets(response.text, tokens),
            credentialed=bool(cred_fields),
            ref=ref.lower(),
        )
