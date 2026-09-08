"""AskUserTool — 文本/单选/凭证三态交互桥（凭证直写密钥区，值不回流）。"""

from __future__ import annotations

from typing import Any

from agent_eval.agent.probe.context import ProbeContext

_MAX_QUESTION_CHARS = 200  # ask_user 单问上限：多问打包会让用户不知从何答起


class AskUserTool:
    """工具：ask_user——Agent 与用户的交互桥（非交互环境 ask_fn 为空 → 拒答）。"""

    def __init__(self, ctx: ProbeContext) -> None:
        self.ctx = ctx

    async def ask_user(
        self,
        question: str,
        options: str = "",
        kind: str = "text",
        ref: str = "",
        field: str = "",
        desc: str = "",
    ) -> dict[str, Any]:
        if self.ctx.ask_fn is None:
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
                value = await self.ctx.ask_fn(
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
            answer = await self.ctx.ask_fn(question, options=opts, secret=False)
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
        self.ctx.login_tried = {k for k in self.ctx.login_tried if k[0] != ref.lower()}
        self.ctx.log("ask_user", event="credential_saved", ref=ref, field=field)
        return {
            "saved": True,
            "ref": ref,
            "field": field.lower(),
            "note": "凭证已入密钥区，不会出现在对话中",
        }
