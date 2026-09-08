"""落盘对账门禁 — sut_configs 结论字段逐字段对上本会话实测证据。

机制：探测工具在验证成功时把事实机械登记进证据账本
（``SUTProbeToolServer.verified_login/verified_protocol``）；本门禁用执行器同款
解析逻辑（``resolve_login_url``）把暂存配置还原成「实际会打到哪个 URL / 声明了
什么形态」，与账本逐字段对账——不一致即打回，错误信息携带账本中的权威片段。

实测教训：Agent 实测的是 A 域登录接口（request 200 + declare_token 提取成功），
落盘时却拆成相对 path + 自造 login.base_url（执行器静默丢弃）拼回页面域，且在
「POST /threads 404」的矩阵结论上仍声明 agent_protocol——验证结论在「LLM 转述
落盘」一步变形。凡可机械传递的事实不经转述；必须转述处，由机械对账兜底。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import yaml

from agent_eval.agent.workbench.sut_probe import CORE_STEP, SUTProbeToolServer
from agent_eval.agent.workbench.tools import PackageToolServer
from agent_eval.execution.registry import expand_env_refs, resolve_login_url


def base_url_host(base_url: str) -> str:
    """从 sut.base_url 提取主机（支持 ``${VAR:-https://host}`` env 缺省形态）。"""
    if match := re.search(r":-(.+?)\}", base_url):
        base_url = match.group(1)
    candidate = base_url if "//" in base_url else f"https://{base_url}"
    return (urlparse(candidate).hostname or "").lower()


def sut_evidence_gate(server: PackageToolServer, probe: SUTProbeToolServer) -> list[str]:
    """落盘对账门禁：sut_configs 的结论字段必须逐字段对上本会话的实测证据。"""
    errors: list[str] = []
    for rel, content in sorted(server.view().items()):
        if not rel.startswith("sut_configs/") or not rel.endswith((".yaml", ".yml")):
            continue
        try:
            data = yaml.safe_load(content) or {}
        except yaml.YAMLError:
            continue  # 语法错误由 validate_package 上报
        sut = data.get("sut")
        if not isinstance(sut, dict):
            continue
        try:
            # 执行器同款预处理（SUTRegistry.load：expand_env_refs 后解析）——
            # 对账面对的必须是「运行时会打到的值」，env 缺省形态不误判变形
            sut = expand_env_refs(sut)
        except Exception:  # noqa: BLE001 — 未定义 env 由 validate 层上报
            continue
        errors += _reconcile_protocol(rel, sut, probe)
        errors += _reconcile_login(rel, sut, probe)
    return errors


def _reconcile_protocol(rel: str, sut: dict[str, Any], probe: SUTProbeToolServer) -> list[str]:
    """协议声明 vs 协议账本：host 须实测过，且矩阵核心端点为 ✅。"""
    if str(sut.get("channel", "")).lower() != "agent_protocol":
        return []
    host = base_url_host(str(sut.get("base_url", "")))
    fact = probe.verified_protocol(host) if host else None
    if fact is None:
        # 机械复用会话内证据：登录实测成功的接口域是协议探测的头号候选
        # （接口域与登录域常同域）——先探测候选，全部落空再问用户，
        # 不让用户重复提供本会话已解析出的信息
        candidates = sorted(probe.login_hosts - {host})
        hint = (
            f"候选接口域（本会话登录实测成功）：{'、'.join(candidates)}"
            "——先 probe_protocol 这些域，全部落空再向用户确认"
            if candidates
            else "请先调用 probe_protocol(base_url=…) 探测该主机；探测不通则"
            "复用本会话已验证的接口域证据（登录域/检索到的 baseURL 域）形成候选"
            "逐一实测，全部落空再向用户确认正确的接口域"
        )
        return [
            f"{rel} 声明 channel: agent_protocol，但 base_url 的主机 {host or '?'} "
            "本会话未经 probe_protocol 实测（协议形态与地址必须是验证过的结论）。"
            f"{hint}"
        ]
    flavor = str(sut.get("protocol_flavor", "commands"))
    core = CORE_STEP.get(flavor, "run_wait")
    if not fact["steps"].get(core):
        return [
            f"{rel} 声明 protocol_flavor: {flavor}，但本会话协议矩阵不支持：核心端点 "
            f"{core} 非 ✅（矩阵事实：{fact['steps']}）。重定向与 catch-all 200 不是"
            "协议证据；POST /threads 是否存在不在判据内（执行器契约由客户端生成"
            "线程 ID、首个 run.start 隐式建线程）——核心端点不通说明接口域很可能"
            "不在该主机：先复用会话内证据（登录域/检索到的 baseURL 域）逐一候选"
            "探测，全部落空再向用户确认"
        ]
    return []


def _reconcile_login(rel: str, sut: dict[str, Any], probe: SUTProbeToolServer) -> list[str]:
    """登录配置 vs 登记账本：解析出的最终 URL/字段组合须与实测事实一致。"""
    auth = sut.get("auth")
    if not isinstance(auth, dict) or str(auth.get("type", "none")) not in (
        "api_login",
        "session_cookie",
    ):
        return []
    login = auth.get("login")
    if not isinstance(login, dict) or not str(login.get("path", "")):
        return [
            f"{rel} 声明 auth.type: {auth.get('type')} 但缺 auth.login.path——"
            "登录接口必须出自本会话 request+declare_token 实测（declare_token 成功时"
            "返回 sut_config_auth_snippet，原样写入即可）"
        ]
    ref = str(auth.get("credential_ref") or sut.get("name") or "")
    fact = probe.verified_login(ref)
    actual_url = resolve_login_url(str(sut.get("base_url", "")), str(login.get("path", "")))
    if fact is None:
        return [
            f"{rel} 的登录配置（将请求 {actual_url}，凭证 ref={ref}）未经本会话 "
            "request+declare_token 实测——对账门禁拒绝未验证的登录落盘。请先 "
            f"request 实测该接口（body 带凭证模板 + ref），2xx 后 declare_token 声明"
            f"提取（成功时返回 sut_config_auth_snippet 原样写入）；"
            "若已实测但 ref 不同，请用实测时的 credential_ref"
        ]
    extract = auth.get("extract") or {}
    configured_type = (
        str(extract.get("token_type") or "Bearer") if isinstance(extract, dict) else "Bearer"
    )
    configured_expires = (
        str(extract.get("expires_in_path") or "") if isinstance(extract, dict) else ""
    )
    if str(auth.get("type")) == "session_cookie":
        configured_type = "cookie"  # 执行器同款归一（provider：session_cookie 强制 cookie）
    diffs: list[str] = []
    if fact["url"] != actual_url:
        diffs.append(
            f"登录 URL：配置将请求 {actual_url}，实测成功的是 {fact['url']}"
            "（跨域登录接口把完整 URL 写进 login.path，不要拆成相对路径拼接页面域）"
        )
    if str(login.get("method", "POST")).upper() != fact["method"].upper():
        diffs.append(f"method：配置 {login.get('method')}，实测 {fact['method']}")
    if str(login.get("body_template", "")) != fact["body_template"]:
        diffs.append(
            f"body_template：配置 {login.get('body_template')!r}，实测 {fact['body_template']!r}"
        )
    token_path = str(extract.get("token_path") or "") if isinstance(extract, dict) else ""
    if token_path != fact["token_path"]:
        diffs.append(f"extract.token_path：配置 {token_path!r}，实测 {fact['token_path']!r}")
    if configured_type.lower() != str(fact.get("token_source", "Bearer")).lower():
        diffs.append(
            f"extract.token_type：配置 {configured_type!r}，实测声明 "
            f"{fact.get('token_source')!r}（执行器三态 Bearer | header:<X> | cookie，"
            "以 declare_token 成功返回的 sut_config_auth_snippet 为准）"
        )
    if configured_expires != str(fact.get("expires_in_path") or ""):
        diffs.append(
            f"extract.expires_in_path：配置 {configured_expires!r}，实测声明 "
            f"{str(fact.get('expires_in_path') or '')!r}"
        )
    if not diffs:
        return []
    return [
        f"{rel} 的登录配置与本会话实测证据不一致：{'；'.join(diffs)}。"
        "请把 declare_token 成功时返回的 sut_config_auth_snippet **原样**写入"
        " auth: 段（勿拆分 URL、勿发明字段——执行器没有 login.base_url）。"
        f"权威片段：\n{fact['auth_snippet']}"
    ]
