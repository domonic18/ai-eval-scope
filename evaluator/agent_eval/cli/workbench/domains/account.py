"""账号与配置域 — doctor / models set / secrets 向导（auth 登录在 Sprint 11）。"""

from __future__ import annotations

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
        from agent_eval.cli.cmds.secrets import secrets_wizard

        secrets_wizard()
    else:
        return
