"""WorkbenchSession — 向导会话：上下文 + 域导航 + preflight（arch/15 §3.1）。

Ctrl-C / 取消优雅回落主菜单，不破坏 workspace 已落盘产物（NF-C-03）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import typer
from rich import print as rprint

from agent_eval.cli.console.prompts import select

_DOMAIN_LABELS = {
    "agent": "工作台 Agent（对话式·推荐）",  # 一级入口（§3.5）：首选工作方式
    "scn": "场景包管理",
    "exec": "执行评测",
    "runs": "查看结果",
    "account": "账号与配置",
}


@dataclass
class WorkbenchContext:
    """跨域保持的会话上下文（F-C-NAV-03）。"""

    platform_ok: bool = False
    models_ok: bool = False
    active_package: str | None = None
    active_task_set: str | None = None
    active_sut: str | None = None

    def banner(self) -> str:
        platform = "✅" if self.platform_ok else "⚠️ "
        models = "✅" if self.models_ok else "⚠️ "
        return (
            "╭─ agent-eval 评测工作台 ────────────────────────╮\n"
            f"│ 平台: {platform}   模型: {models}   当前包: {self.active_package or '—'}\n"
            "╰───────────────────────────────────────────────╯"
        )


class WorkbenchSession:
    def __init__(self) -> None:
        self.ctx = WorkbenchContext()
        self._refresh()

    def _refresh(self) -> None:
        """刷新环境态（登录/模型配置），供 banner 与 preflight。"""
        self.ctx.platform_ok = bool(
            os.environ.get("AGENT_EVAL_HOST") and os.environ.get("AGENT_EVAL_API_KEY")
        )
        try:
            from agent_eval.config.llm_file import load_llm_file

            cfg = load_llm_file()
            self.ctx.models_ok = bool(cfg and (cfg.roles.get("text") or cfg.roles.get("vision")))
        except Exception:  # noqa: BLE001 — 环境探测失败按未配置处理
            self.ctx.models_ok = False

    def preflight(self) -> None:
        """首屏引导（F-C-NAV-04）：只提示，不阻断。"""
        if not self.ctx.models_ok:
            rprint(
                "[yellow]⚠ 模型未配置 —— LLM 评估将降级。"
                "可在「账号与配置」域执行 models set[/yellow]"
            )
        if not self.ctx.platform_ok:
            rprint(
                "[yellow]⚠ 平台未连接 —— 结果上报不可用（本地评估不受影响）；"
                "可在「账号与配置」域执行 auth login[/yellow]"
            )

    def run(self, domain: str | None = None) -> None:
        from agent_eval.cli.cmds.workbench_agent import agent_workbench_entry
        from agent_eval.cli.workbench.domains import (
            account,
            scn,
        )
        from agent_eval.cli.workbench.domains import (
            exec as exec_domain,
        )
        from agent_eval.cli.workbench.domains import (
            runs as runs_domain,
        )

        handlers = {
            "agent": lambda _session: agent_workbench_entry(_session),
            "scn": scn.main,
            "exec": exec_domain.main,
            "runs": runs_domain.main,
            "account": account.main,
        }
        if domain:
            # arch/15 §13：--domain auth 为账号域别名（域键 account）
            resolved = "account" if domain == "auth" else domain
            if resolved not in handlers:
                rprint(f"[red]未知 --domain: {domain}（{'/'.join(handlers)}/auth）[/red]")
                raise typer.Exit(code=2)
            handlers[resolved](self)
            return

        rprint(self.ctx.banner())
        self.preflight()
        options = list(_DOMAIN_LABELS.values()) + ["退出"]
        while True:
            choice = select("选择工作域", options, default=1)
            if choice == "退出":
                rprint("👋 再见")
                return
            key = next(k for k, label in _DOMAIN_LABELS.items() if label == choice)
            try:
                handlers[key](self)
                self._refresh()
            except typer.Exit as e:
                if e.exit_code:
                    rprint(f"[dim]（动作退出码 {e.exit_code}，返回主菜单）[/dim]")
            except typer.Abort:
                rprint("\n[dim]已取消，返回主菜单[/dim]")
