"""agent-eval doctor — 顶层一键自检（requirement/04 F-C-CONFIG-02）。

逐项检查：平台身份 / 模型三角色 / SUT 凭证 / 场景包 / workspace / 可选依赖，
输出 ✅/⚠️/❌ 与修复建议；``--json`` 输出机器可读结果。
"""

from __future__ import annotations

import importlib.util
import os

from agent_eval.cli._common import Table, rprint

__all__ = ["doctor_action", "run_checks"]


def _check_platform() -> dict[str, str]:
    host = os.environ.get("AGENT_EVAL_HOST", "")
    key = os.environ.get("AGENT_EVAL_API_KEY", "")
    if host and key:
        return {"name": "平台", "status": "ok", "detail": host, "fix": ""}
    if host or key:
        return {
            "name": "平台",
            "status": "warn",
            "detail": f"host={host or '缺失'} api_key={'已设' if key else '缺失'}",
            "fix": "补全 AGENT_EVAL_HOST / AGENT_EVAL_API_KEY（.env）",
        }
    return {
        "name": "平台",
        "status": "warn",
        "detail": "未配置（上报不可用，本地评估不受影响）",
        "fix": "Sprint 11: agent-eval auth login",
    }


def _check_models() -> dict[str, str]:
    from agent_eval.config.llm_file import load_llm_file

    cfg = load_llm_file()
    if cfg is None:
        return {"name": "模型", "status": "err", "detail": "未配置", "fix": "agent-eval models set"}
    parts = []
    for role in ("text", "vision", "agent"):
        rc = cfg.roles.get(role)
        parts.append(
            f"{role}={'✅ ' + rc.model if rc else ('⚠️ 回退 text' if role == 'agent' else '❌')}"
        )
    ok = cfg.roles.get("text") or cfg.roles.get("vision")
    return {
        "name": "模型",
        "status": "ok" if ok else "err",
        "detail": "  ".join(parts),
        "fix": "" if ok else "agent-eval models set",
    }


def _check_secrets() -> dict[str, str]:
    from agent_eval.execution.auth.secrets_store import secrets_file_path

    path = secrets_file_path()
    if not path.exists():
        return {
            "name": "凭证",
            "status": "warn",
            "detail": "无 SUT 凭证（需要在线驱动被测系统时再配）",
            "fix": "agent-eval secrets set <ref>.<field>",
        }
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        refs = list(data.keys())
    except (OSError, ValueError):
        refs = []
    return {
        "name": "凭证",
        "status": "ok" if refs else "warn",
        "detail": f"{len(refs)} 个 ref: {', '.join(refs[:5]) or '空'}",
        "fix": "",
    }


def _check_packages() -> dict[str, str]:
    from agent_eval.packages import PackageManager

    pkgs = PackageManager().list()
    builtin = sum(1 for p in pkgs if p.source == "builtin")
    local = sum(1 for p in pkgs if p.source == "local")
    return {
        "name": "场景包",
        "status": "ok" if pkgs else "err",
        "detail": f"内置 {builtin} · 本地仓库 {local}",
        "fix": "" if pkgs else "重装 agent-eval（内置包随 wheel 发布）",
    }


def _check_workspace() -> dict[str, str]:
    from agent_eval.config.paths import paths

    ws = paths.default_workspace
    ws.mkdir(parents=True, exist_ok=True)
    probe = ws / ".doctor_probe"
    try:
        probe.write_text("ping", encoding="utf-8")
        probe.unlink()
    except OSError:
        return {
            "name": "workspace",
            "status": "err",
            "detail": str(ws),
            "fix": "检查目录权限或 WORKSPACE_DIR",
        }
    return {"name": "workspace", "status": "ok", "detail": str(ws), "fix": ""}


def _check_extras() -> dict[str, str]:
    extras = [("agent", "deepagents"), ("llm", "openai")]
    missing = [label for label, mod in extras if importlib.util.find_spec(mod) is None]
    if not missing:
        return {"name": "依赖 extras", "status": "ok", "detail": "[agent] [llm] 已装", "fix": ""}
    detail = " ".join(f"⚠️ [{m}] 缺失" for m in missing)
    return {
        "name": "依赖 extras",
        "status": "warn",
        "detail": detail,
        "fix": f"uv sync --extra {' --extra '.join(missing)}",
    }


def run_checks() -> list[dict[str, str]]:
    """执行全部检查项（纯函数动作）。"""
    return [
        _check_platform(),
        _check_models(),
        _check_secrets(),
        _check_packages(),
        _check_workspace(),
        _check_extras(),
    ]


def doctor_action() -> list[dict[str, str]]:
    """渲染体检表（workbench 复用；--json 由命令层注入）。"""
    from agent_eval.cli.console.output import emit_json, is_json

    checks = run_checks()
    if is_json():
        emit_json({"checks": checks})
        return checks
    icons = {"ok": "[green]✅[/green]", "warn": "[yellow]⚠️[/yellow]", "err": "[red]❌[/red]"}
    table = Table(title="agent-eval doctor")
    table.add_column("检查项", style="bold")
    table.add_column("状态")
    table.add_column("详情")
    table.add_column("修复建议")
    for c in checks:
        table.add_row(c["name"], icons[c["status"]], c["detail"], c["fix"] or "—")
    rprint(table)
    return checks


def has_blocking(checks: list[dict[str, str]]) -> bool:
    """模型未配置视为阻断（评测链路不可用）；平台/凭证/extras 仅告警。"""
    return any(c["name"] == "模型" and c["status"] == "err" for c in checks)
