"""登录实测 — 预览确认 + 防锁 + 凭证旁路 + ask_user（arch/15 §6.6 红线域）。

红线：凭证外发硬门禁（发送前必出脱敏预览并经用户确认，预览即凭证外发同意）、
登录防锁（**失败语义分层**：仅认证层拒绝（4xx/5xx）入锁——同 ref+URL+模板组合
不自动重试，防真实系统撞锁；404 未到认证层、网络失败、**登录成功（2xx，凭证已
验证有效，更正 token_path 的重测无撞锁风险）** 均不入锁，受轮内预算约束）、
凭证值不回流 LLM 上下文（凭证直写密钥区，账密与响应 token 一并脱敏）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from agent_eval.agent.probe.fetch import _mask, _wrap_evidence
from agent_eval.agent.tools import TEMPLATE_SYNTAX_HINT

# 登录模板语法纠偏：probe_login 用 Jinja2 渲染 body_template，实测曾出现 shell 风格
# ${var} 占位符原样发出（服务端报「格式不是手机号」被误读为用户输入错误）——
# 渲染后残留占位符一律拒发
_TEMPLATE_SYNTAX_HINT = TEMPLATE_SYNTAX_HINT
_UNRENDERED_PLACEHOLDER_RE = re.compile(r"\$\{[^}]*\}|\{\{[^}]*?\}\}|\{%[^%]*?%\}")
_MAX_QUESTION_CHARS = 200  # ask_user 单问上限：多问打包会让用户不知从何答起


def _render_auth_snippet(*, ref: str, method: str, url: str, template: str, token_path: str) -> str:
    """把实测成功的登录事实渲染为可照抄的 ``auth:`` 段 YAML。

    装配在证据产生处完成一次（工具机械渲染，非经 LLM 转述）——这是「验证结果
    正确落到场景包文件」的第一环：词汇与执行器 ``auth.login`` 同构，落盘时
    原样粘贴即可，无需任何字段翻译。
    """
    import yaml

    snippet = {
        "auth": {
            "type": "api_login",
            "credential_ref": ref,
            "login": {"method": method, "path": url, "body_template": template},
            "extract": {"token_path": token_path, "token_type": "Bearer"},
        }
    }
    return yaml.safe_dump(snippet, allow_unicode=True, sort_keys=False).strip()


class LoginMixin:
    """工具四（登录实测）与工具五（ask_user：文本/单选/凭证，值不回流）。

    协作契约注解：宿主提供 ``_budget/_client/_log``、凭证库（``credentials``）、
    交互桥（``ask_fn``）、防锁与证据账本设施——类级注解仅供类型检查，运行时
    不创建属性。
    """

    _budget: Callable[[str], dict[str, str] | None]
    _client: Callable[[], Awaitable[Any]]
    _log: Callable[..., None]
    credentials: Any  # CredentialStore（secrets 直写，值不回流）
    ask_fn: Any  # async (question, *, options, secret) -> str | None
    _login_tried: set[tuple[str, str, str]]
    _store_token: Callable[[str, str], None]
    _record_login: Callable[[dict[str, str]], None]
    verified_login: Callable[[str], dict[str, str] | None]

    async def probe_login(self, login_cfg: dict[str, Any], ref: str) -> dict[str, Any]:
        if budget_err := self._budget("probe_login"):
            return budget_err
        from jinja2 import Environment, Template, meta

        # 词汇同构（v3.6）：login_cfg 与执行器 sut_configs 的 auth.login 同形——
        # path 承载完整 URL。不再接受 base_url 拼接：那正是「实测完整 URL 在
        # 探测工具里、落盘时拆成 path+base_url 被执行器静默丢弃」的变形源头
        url = str(login_cfg.get("path") or login_cfg.get("url") or "")
        if url and not url.startswith(("http://", "https://")):
            return {
                "error": (
                    "login_cfg.path 需为完整 http(s):// URL（与 sut_configs 的 "
                    "auth.login.path 同形——跨域登录接口直接写完整地址）。本工具没有 "
                    "base_url 字段，不要把已发现的接口域拆成 path + base_url 两段"
                )
            }
        template = login_cfg.get("body_template", "")
        # v3.14：LLM 会把 body_template 写成 JSON 对象（dict）而非字符串——
        # jinja2 对非字符串源抛 TypeError「Can't compile non template nodes」，
        # 旧错误文案套「Jinja2 语法纠正」话术，误导 Agent 去修「语法」而实际是
        # 「类型」（实测会话空转一轮才悟出「应该是 JSON 字符串」）。dict/list 是
        # 唯一有明确字符串形态的输入：机械序列化（凡可机械传递的事实不经 LLM
        # 转述），生效模板随结果回显，落盘以工具渲染的 sut_config_auth_snippet 为准
        template_note = ""
        if isinstance(template, (dict, list)):
            try:
                template = json.dumps(template, ensure_ascii=False)
            except (TypeError, ValueError) as e:
                return {"error": f"body_template 无法序列化为模板字符串（{e}）——请传 JSON 文本"}
            template_note = (
                "body_template 传的是对象，已机械序列化为字符串："
                + template
                + " ——重试与落盘以此字符串形态传参（成功返回的 sut_config_auth_snippet"
                " 已是该形态）"
            )
        elif not isinstance(template, str):
            return {
                "error": (
                    f"body_template 需为 JSON 文本字符串（收到 {type(template).__name__}）："
                    '模板是字符串不是对象，如 \'{"phone": "{{ username }}"}\'——'
                    "对象内的变量按 Jinja2 语法写 {{ 字段名 }}，常量字段写字面值"
                )
            }
        fields = sorted(meta.find_undeclared_variables(Environment().parse(template)))
        values: dict[str, str] = {}
        if self.credentials is not None:
            values = {f: self.credentials.get(ref, f) or "" for f in fields}
        missing = [f for f in fields if not values.get(f)]
        if missing:
            result: dict[str, Any] = {
                "missing_fields": missing,
                "hint": (
                    f"凭证缺失：逐字段 ask_user(kind=credential, ref={ref!r}, field=<字段名>, "
                    "desc=<该字段实际要输入什么>) 收集——一次只录一个字段且 desc 必带"
                    "（用户据此知道输入什么，从你的检索摘录/接口语义得出）；"
                    "会话内隐藏输入直接完成（勿让用户另开终端执行命令，那是非交互/CI 的"
                    "备用通道）；收齐后重新调用本工具"
                ),
            }
            if template_note:
                result["note"] = template_note
            return result
        if not url:
            return {"error": "login_cfg 缺少 url/path"}
        # 防锁按（ref+完整 URL+模板）：同 host 不同路径是不同组合——实测曾因键缺
        # 路径，猜错路径的失败连坐了用户随后给出的正确地址
        key = (ref.lower(), url, str(template))
        if key in self._login_tried:
            return {
                "error": (
                    "该接口与字段组合已被认证层拒绝过（防锁红线：4xx/5xx 拒绝的组合不"
                    "自动重试，防真实系统撞锁），同一配置不再发送。更新 body_template 或"
                    "地址后即为新组合可再试；登录成功（2xx）与 404 的组合不入锁——"
                    "更正 token_path 后可直接重测"
                )
            }
        # 占位符语法校验：渲染后残留 ${var}/{{var}} 即模板写错——拒发（预览即最终
        # 报文的核对由工具兜底，不依赖人眼发现占位符没被替换）
        try:
            rendered = Template(template).render(**values)
        except Exception as e:  # noqa: BLE001 — 模板语法错误转纠正提示
            return {"error": f"body_template 渲染失败（{e}）。{_TEMPLATE_SYNTAX_HINT}"}
        if residual := _UNRENDERED_PLACEHOLDER_RE.findall(rendered):
            return {
                "error": (
                    f"body_template 渲染后仍残留占位符 {residual[:3]}——请求未发送。"
                    f"{_TEMPLATE_SYNTAX_HINT}"
                )
            }

        body = _mask(rendered, list(values.values()))
        method = login_cfg.get("method", "POST").upper()
        # 脱敏预览 + 凭证外发同意（红线 2/预览即同意）：非交互形态一律不发送。
        # 预览必须显示完整 URL——路径抄错只有在这里用户才看得见（只显 host 等于没校对）
        preview = (
            "即将发送登录实测请求（发送前请核对接口地址与字段，凭证已脱敏）：\n"
            f"  方法: {method}\n"
            f"  URL: {url}\n"
            f"  body: {body}\n"
            "确认发送？"
        )
        if self.ask_fn is None:
            result = {
                "need_confirm": True,
                "url": url,
                "method": method,
                "masked_body": body,
                "note": "非交互环境不发送登录请求；请用户交互运行确认后重试",
            }
            if template_note:
                result["note"] = f"{template_note}；{result['note']}"
            return result
        answer = await self.ask_fn(preview, options=["发送", "取消"], secret=False)
        if not answer or "发送" not in answer:
            self._log("probe_login", ref=ref, event="user_aborted")
            return {"aborted": True, "note": "用户取消，未发送"}
        try:
            client_cm = await self._client()
            async with client_cm as client:
                response = await client.request(
                    method,
                    url,
                    content=rendered,
                    headers={"Content-Type": "application/json"},
                )
        except Exception as e:  # noqa: BLE001
            # 请求未达服务端：无撞锁风险，不入锁（同组合可经用户确认后重发）
            self._log("probe_login", ref=ref, event="request_failed", error=str(e)[:200])
            return {"ok": False, "error": f"登录请求失败: {e}"}
        token_path = login_cfg.get("token_path", "")
        token_extracted = False
        token_value = ""
        payload: dict[str, Any] = {}
        try:
            payload = response.json()
            if token_path:
                node: Any = payload
                for part in token_path.split("."):
                    if not isinstance(node, dict):
                        node = None
                        break
                    node = node.get(part)
                if node is not None:
                    token_extracted = True
                    token_value = str(node)
        except Exception:  # noqa: BLE001 — 非 JSON/提取失败记为未提取
            pass
        self._log(
            "probe_login", ref=ref, status=response.status_code, token_extracted=token_extracted
        )
        # 凭证旁路：账密与响应 token 一并脱敏——值不得回流 LLM 上下文
        mask_values = [*values.values(), token_value] if token_value else list(values.values())
        status = response.status_code
        if status == 404:
            # 失败语义分层（防锁不误伤探索）：404 = 请求未到认证层（无凭证校验即无
            # 撞锁风险）——不入锁，换路径探索是正当行为；防锁只拦「已到认证层的失败」
            # （4xx/5xx）的同组合自动重试
            guidance = (
                "404：该路径不存在（请求未到认证层，不计入防锁）——换下一候选路径继续"
                "实测（候选依据 discover_login 返回与前端包分析结论，openapi/form 候选"
                "优先；勿凭空拼凑路径清单——catch-all 服务上 GET 200 不代表存在，以"
                "实测为准）；或把证据呈现给用户核对地址。受轮内预算约束，勿单轮扫路径"
            )
        elif status < 400:
            # 登录成功（2xx）：凭证已被认证层验证有效——重测（如更正 token_path）
            # 无撞锁风险，不入锁；重试受轮内预算 + 每次发送需预览确认约束
            if token_extracted:
                # 证据账本 + 装配片段：事实在产生处机械转换一次（YAML 由工具渲染，
                # 非经 LLM 转述）——落盘时原样使用即可，变形会被对账门禁打回
                self._store_token(ref, token_value)  # 服务端持有，探测请求挂鉴权（不回流）
                self._record_login(
                    {
                        "ref": ref,
                        "method": method,
                        "url": url,
                        "body_template": template,
                        "token_path": token_path,
                        "auth_snippet": _render_auth_snippet(
                            ref=ref,
                            method=method,
                            url=url,
                            template=template,
                            token_path=token_path,
                        ),
                    }
                )
                guidance = (
                    "成功→把返回的 sut_config_auth_snippet **原样**写进 sut_configs"
                    " 的 auth: 段（勿拆分 URL、勿增删字段；凭证仅 credential_ref 引用）；"
                    "落盘对账门禁会用执行器同款逻辑与实测证据逐字段比对；若协议探测曾在"
                    "本登录成功前失败（authenticated: false），现在重探 probe_protocol"
                    "（token 已自动挂载）"
                )
            else:
                guidance = (
                    "登录成功但未提取到 token（token_path 与响应结构不符）——按响应证据"
                    "更正 token_path 后重测即可：登录已成功、凭证已验证有效，重测不受"
                    "防锁限制（无撞锁风险）；以最终实测通过的 sut_config_auth_snippet 落盘"
                )
        else:
            # 认证层拒绝（4xx/5xx）：同组合不自动重试——防的是真实撞锁风险
            # （2xx 成功与 404 均不入锁：前者凭证已验证有效，后者未到认证层）
            self._login_tried.add(key)
            guidance = (
                f"HTTP {status}：接口存在（路由已匹配，校验/鉴权未过）——按证据核对字段名，"
                "逐字段 ask_user(kind=credential) 收集/更正凭证后重测（新凭证录入即解锁"
                "一次重试），或按证据更正 body_template（模板变化亦为新组合）"
            )
        result = {
            "ok": status < 400 and token_extracted,
            "status": status,
            "url": url,
            "token_extracted": token_extracted,
            "evidence": _wrap_evidence("登录响应（已脱敏）", _mask(response.text, mask_values)),
            "next_step": guidance,
        }
        if template_note:
            result["note"] = template_note
        if status < 400 and token_extracted and (fact := self.verified_login(ref)):
            result["sut_config_auth_snippet"] = fact["auth_snippet"]
        return result

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
                # 一次只录一个字段：多字段打包会整串存成一个键名，probe_login 逐字段
                # 查不到（实测 Agent 曾传 field="username,password"）
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
        # 新凭证录入解锁该 ref 的登录防锁：一次录入换一次实测
        # （重试循环被「必须经用户录入」天然限流）
        self._login_tried = {k for k in self._login_tried if k[0] != ref.lower()}
        self._log("ask_user", event="credential_saved", ref=ref, field=field)
        return {
            "saved": True,
            "ref": ref,
            "field": field.lower(),
            "note": "凭证已入密钥区，不会出现在对话中",
        }
