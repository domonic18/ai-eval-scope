"""响应结构化 — request 返回形态的值回流条件化与失败模式指引。"""

from __future__ import annotations

from typing import Any

from agent_eval.agent.workbench.sut_probe.context import ProbeContext
from agent_eval.agent.workbench.sut_probe.helpers import key_path_tree, mask_secrets, wrap_evidence


def structure_response(
    ctx: ProbeContext,
    verb: str,
    url: str,
    response: Any,
    elapsed_ms: int,
    *,
    masked_text: str,
    credentialed: bool,
    ref: str,
) -> dict[str, Any]:
    """响应结构化（值回流条件化）：值要回流，前提是知道哪些值是凭证。

    - 非 2xx：原文（失败响应无会话凭证，排错需要）；
    - 非凭证请求：原文（会话 token 值已掩）；
    - 凭证请求 2xx 且该 ref 已声明提取：原文（token 值已知名、掩得住）；
    - 凭证请求 2xx 未声明：只回键路径结构树（不知道哪个值是会话凭证）。
    """
    started_result: dict[str, Any] = {}
    tokens = [v.get("token", "") for v in ctx.session_tokens.values()]
    has_token_for_ref = ref.lower() in ctx.session_tokens if ref else False
    if 200 <= response.status_code < 300 and credentialed and not has_token_for_ref:
        try:
            payload = response.json()
            tree = key_path_tree(payload)
        except Exception:  # noqa: BLE001 — 非 JSON 走原文尽力掩码
            payload, tree = None, ""
        if payload is not None:
            started_result["evidence"] = wrap_evidence(
                "响应键路径结构（declare_token 声明提取前不回传响应原文："
                "响应可能含会话凭证，值一律不回流）",
                tree,
            )
        else:
            started_result["evidence"] = wrap_evidence(f"{verb} {url}", masked_text)
    else:
        started_result["evidence"] = wrap_evidence(f"{verb} {url}", masked_text)
    result: dict[str, Any] = {
        "status": response.status_code,
        "elapsed_ms": elapsed_ms,
        "auth_attached": bool(ctx.auth_headers),
        "headers": {
            k: mask_secrets(v, tokens)
            for k, v in response.headers.items()
            if k.lower() != "set-cookie"
        },
        **started_result,
    }
    if verb == "GET" and not credentialed:
        # 抓取缓存只存非凭证请求（凭证响应的未声明 token 值不在掩码清单里，
        # 入缓存会被 search_content 检出——值回流条件化同样约束缓存面）
        ctx.cache_content(url, masked_text)
        result["content_type"] = response.headers.get("content-type", "")
        chain = [str(r.status_code) for r in getattr(response, "history", []) or []]
        result["redirect_chain"] = "→".join(chain) if chain else ""
        ct = result["content_type"]
        if "javascript" in ct or "json" in ct or len(response.text) > 2000:
            result["cached_bytes"] = len(response.text)
            result["search_hint"] = (
                "完整内容已缓存——用 search_content 检索关键片段（模式自拟），"
                "勿凭本次摘要下结论，也勿重复抓取"
            )
        if response.status_code >= 400:
            result["next_step"] = (
                f"HTTP {response.status_code}（GET）：多为「路径未匹配或方法不允许」——"
                "POST-only 接口用 GET 探测即 404（Express 系常见），不代表服务或接口无效；"
                "路径存在性以带真实字段的 POST 实测为准；若在找登录页面：向用户要"
                "登录页面地址后用 discover_login 分析，勿逐路径猜测"
            )
    if response.status_code == 404 and "next_step" not in result:
        result["next_step"] = (
            "404：路径未命中（请求未到认证层，不计入防锁）——换候选路径或"
            "方法再实测，或与用户核对接口地址"
        )
    if response.status_code in (401, 403):
        if credentialed:
            # 带凭证被拒：这才是「凭证被拒」的真信号
            result["next_step"] = (
                "带凭证请求被 401/403 拒绝：凭证值或字段不匹配（该组合已入防锁，"
                "同参数重发会被拦）。核对字段名与凭证来源后用新 body 组成新组合重试；"
                "若响应确为 2xx 的其它接口才是登录入口，改测那个接口"
            )
        elif ctx.auth_headers:
            # 已声明凭证仍被拒（探测不自动重发登录，防锁红线）：token 可能过期
            result["next_step"] = (
                "请求已自动挂载会话凭证但被 401/403 拒绝：凭证可能已过期或对该接口"
                "无权限——重新实测登录（新 body 组合）并 declare_token 重新声明后重试"
            )
        else:
            # 未鉴权假阴性：单一权威 next_step
            result["next_step"] = (
                "本次请求未携带鉴权（会话尚无已声明的会话凭证），401/403 不构成"
                "接口无效的结论——先用 request(ref=…) 实测登录接口，成功后 "
                "declare_token 声明提取（凭证自动挂载）再重试"
            )
    return result
