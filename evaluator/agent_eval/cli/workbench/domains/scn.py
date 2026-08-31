"""场景包管理域 — 查看 / 列出 / 校验（创建与 Agent 改包在 Sprint 11）。"""

from __future__ import annotations

from pathlib import Path

from rich import print as rprint

from agent_eval.cli.console.prompts import ask, select


def main(session) -> None:  # noqa: ANN001 — WorkbenchSession（避免循环导入用 duck type）
    action = select(
        "场景包动作",
        ["查看包内容", "Agent 会话改包", "Agent 生成新包", "列出全部包", "校验项目包", "返回"],
    )
    if action.startswith("查看包内容"):
        _view()
    elif action.startswith("Agent 会话改包"):
        from agent_eval.cli.cmds.scenario import select_scenario_ref
        from agent_eval.cli.cmds.scenario_agent import agent_edit_package

        agent_edit_package(
            ref=select_scenario_ref(), instruction=None, yes=False, trust_agent=False
        )
    elif action.startswith("Agent 生成新包"):
        from agent_eval.cli.cmds.scenario_agent import agent_new_package

        ref = ask("新包引用（如 travel-itinerary/quality）")
        agent_new_package(ref=ref, output=None, instruction=None, yes=False, trust_agent=False)
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
