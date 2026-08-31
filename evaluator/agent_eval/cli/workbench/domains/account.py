"""账号与配置域 — doctor / models set / secrets 引导（auth 登录在 Sprint 11）。"""

from __future__ import annotations

from rich import print as rprint

from agent_eval.cli.console.prompts import select


def main(session) -> None:  # noqa: ANN001
    action = select(
        "账号与配置",
        [
            "自检 (doctor)",
            "配置模型 (models set)",
            "查看模型配置 (models list)",
            "SUT 凭证 (secrets)",
            "返回",
        ],
    )
    if action.startswith("自检"):
        from agent_eval.cli.cmds.doctor import doctor_action

        doctor_action()
    elif action.startswith("配置模型"):
        from agent_eval.cli.cmds.models import models_set

        models_set()
        session._refresh()
    elif action.startswith("查看模型"):
        from agent_eval.cli.cmds.models import list_models

        list_models()
    elif action.startswith("SUT"):
        from agent_eval.execution.auth.secrets_store import secrets_file_path

        rprint(f"凭证文件: [cyan]{secrets_file_path()}[/cyan]（0600）")
        rprint(
            "[blue]录入:[/blue] agent-eval secrets set <ref>.<field>   "
            "[blue]查看:[/blue] agent-eval secrets list"
        )
    else:
        return
