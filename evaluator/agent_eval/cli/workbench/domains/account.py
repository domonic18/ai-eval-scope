"""账号与配置域 — auth / models / secrets / doctor（arch/15 §3.3）。"""

from __future__ import annotations

from typing import Any

from agent_eval.cli.console.prompts import select


def main(session: Any) -> None:
    action = select(
        "账号与配置",
        [
            "平台账号 (auth)",
            "自检 (doctor)",
            "配置模型 (models set)",
            "查看模型配置 (models list)",
            "SUT 凭证 (secrets)",
            "返回",
        ],
    )
    if action.startswith("平台账号"):
        from agent_eval.cli.cmds.auth import auth_wizard

        auth_wizard()
        session._refresh()
    elif action.startswith("自检"):
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
