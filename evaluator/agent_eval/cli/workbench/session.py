"""WorkbenchSession — 向导会话：上下文 + 域导航 + 首启引导。

Ctrl-C / 取消优雅回落主菜单，不破坏 workspace 已落盘产物（NF-C-03）。

首启引导：模型未配置时给结构化引导卡 + 一步直达 models set 向导，
菜单动态标注受影响域。曾只打印一行「可在账号与配置域执行 models set」——
首次用户不知道 models set 是什么、要走几步、不配会失去什么（gh/Claude Code
式 onboarding：当场给出去向与成本，把配置动作拉到面前，而非让用户自己找）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import typer
from rich import print as rprint
from rich.panel import Panel

from agent_eval.cli.console.prompts import select

# (key, label, needs_model)：needs_model = LLM 未配置时该域受限/降级（菜单标注）
_DOMAINS: list[tuple[str, str, bool]] = [
    ("agent", "工作台 Agent（对话式·推荐）", True),  # 一级入口：首选工作方式
    ("scn", "场景包管理", False),
    ("exec", "执行评测", True),
    ("runs", "查看结果", False),
    ("account", "账号与配置", False),
]

_MODEL_NOTE = " ⚠ 需先配置模型"


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

    def onboard(self) -> None:
        """首屏引导（F-C-NAV-04）：模型未配置 → 引导卡 + 一步直达配置向导。

        只提示不阻断的哲学不变：稍后配置完全合法（规则类评估器与本地功能
        不受影响）；变化的是提示的信息量与去向——影响面、所需准备（一个
        OpenAI 兼容 API Key，约 1 分钟）、配置动作本身（无需先知道「账号
        与配置域」的存在）。平台未连接保持一行提示（本地评估完全可用）。
        """
        if not self.ctx.models_ok:
            rprint(
                Panel(
                    "[bold]模型尚未配置[/bold] —— 工作台 Agent 与 LLM 评估暂不可用\n\n"
                    "[dim]配置约 1 分钟：准备任一 OpenAI 兼容服务的 API Key，向导会引导\n"
                    "选择提供商 / 协议 / 模型并完成连通性验证。\n"
                    "场景包管理、查看结果不受影响。[/dim]",
                    title="🚀 欢迎使用 agent-eval",
                    border_style="yellow",
                )
            )
            choice = select(
                "是否立即配置模型",
                ["立即配置（推荐）", "稍后——菜单「账号与配置」随时可配"],
            )
            if choice.startswith("立即配置"):
                from agent_eval.cli.cmds.models import models_set

                try:
                    models_set()
                except (typer.Exit, typer.Abort):
                    # 用户中途取消：回落主菜单，不整场退出（NF-C-03 同款优雅语义）
                    rprint("[dim]（配置未完成，可稍后在「账号与配置 → 配置模型」重试）[/dim]")
                self._refresh()
                if self.ctx.models_ok:
                    rprint("[green]✅ 模型已就绪 —— 工作台 Agent 与 LLM 评估已可用[/green]")
                else:
                    rprint("[yellow]⚠ 模型仍未配置 —— 可从「账号与配置 → 配置模型」重试[/yellow]")
        if not self.ctx.platform_ok:
            rprint(
                "[yellow]⚠ 平台未连接 —— 结果上报不可用（本地评估不受影响）；"
                "可在「账号与配置」域执行 auth login[/yellow]"
            )

    def _menu_entries(self) -> list[tuple[str, str]]:
        """域菜单条目（key, label）：LLM 未配置时给依赖域动态标注（可见非阻断）。"""
        note = "" if self.ctx.models_ok else _MODEL_NOTE
        return [(key, label + note if needs else label) for key, label, needs in _DOMAINS]

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

        handlers: dict[str, Any] = {
            "agent": lambda _session: agent_workbench_entry(_session),
            "scn": scn.main,
            "exec": exec_domain.main,
            "runs": runs_domain.main,
            "account": account.main,
        }
        if domain:
            # --domain auth 为账号域别名（域键 account）
            resolved = "account" if domain == "auth" else domain
            if resolved not in handlers:
                rprint(f"[red]未知 --domain: {domain}（{'/'.join(handlers)}/auth）[/red]")
                raise typer.Exit(code=2)
            handlers[resolved](self)
            return

        rprint(self.ctx.banner())
        self.onboard()
        while True:
            entries = self._menu_entries()
            options = [label for _, label in entries] + ["退出"]
            choice = select("选择工作域", options, default=1)
            if choice == "退出":
                rprint("👋 再见")
                return
            key = next(k for k, label in entries if label == choice)
            needs_model = next(needs for k, _, needs in _DOMAINS if k == key)
            if not self.ctx.models_ok and needs_model:
                # 在最有信息量的位置提醒（选择受影响域时），不阻断——
                # 规则类评估器与本地功能仍可用（preflight 哲学）
                rprint("[yellow]⚠ 模型未配置 —— 该域的 LLM 功能将受限或降级[/yellow]")
            try:
                handlers[key](self)
                self._refresh()
            except typer.Exit as e:
                if e.exit_code:
                    rprint(f"[dim]（动作退出码 {e.exit_code}，返回主菜单）[/dim]")
            except typer.Abort:
                rprint("\n[dim]已取消，返回主菜单[/dim]")
