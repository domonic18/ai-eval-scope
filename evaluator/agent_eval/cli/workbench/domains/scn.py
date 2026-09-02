"""场景包管理域 — 查看 / 列出 / 校验 / Agent 生成与改包（Sprint 11）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich import print as rprint

from agent_eval.cli.console.prompts import ask, select


def main(session: Any) -> None:  # WorkbenchSession（避免循环导入用 duck type）
    # Agent 两项为「档位快捷方式」（§3.5）：预载对象上下文的快捷入口——
    # 语义从「Agent 的功能」改为「用 Agent 做某事」，通用对话式入口在主菜单一级
    action = select(
        "场景包动作",
        ["查看包内容", "用 Agent 修改选中的包", "用 Agent 创建场景包", "列出全部包", "校验项目包", "返回"],
    )
    if action.startswith("查看包内容"):
        _view()
    elif action.startswith("用 Agent 修改"):
        from agent_eval.cli.cmds.scenario import select_editable_ref
        from agent_eval.cli.cmds.workbench_agent import agent_edit_package

        agent_edit_package(
            ref=select_editable_ref(), instruction=None, yes=False, trust_agent=False
        )
    elif action.startswith("用 Agent 创建"):
        from agent_eval.cli.cmds.workbench_agent import agent_new_package

        # 包名不前置询问——Agent 按需求拟定，会话中自然语言可改（F-C-SCN-AGENT）
        agent_new_package(ref=None, output=None, instruction=None, yes=False, trust_agent=False)
    elif action.startswith("列出"):
        from agent_eval.cli.cmds.scenario import scenario_list

        scenario_list(source="all")
    elif action.startswith("校验"):
        from agent_eval.cli.cmds.scenario import scenario_validate

        path = ask("项目包根目录路径（含 agent_eval.yaml）")
        scenario_validate(Path(path))
    else:
        return


def _view() -> None:
    from agent_eval.cli.cmds.scenario import show_scenario
    from agent_eval.packages import PackageManager

    pkgs = PackageManager().list()
    if not pkgs:
        rprint("[yellow]未发现场景包。[/yellow]")
        return
    options = [f"{p.manifest.ref}  ({p.source})" for p in pkgs] + ["返回"]
    pick = select("选择场景包", options)
    if pick == "返回":
        return
    ref = pick.split("  (")[0]
    section = select(
        "查看分区", ["tree 结构", "manifest 清单", "rules 规则集", "tasks 考卷", "sut 接入", "返回"]
    )
    if section == "返回":
        return
    show_scenario(ref, section.split(" ")[0])
