"""场景包管理域 — 查看 / 列出 / 校验（创建与 Agent 改包在 Sprint 11）。"""

from __future__ import annotations

from pathlib import Path

from rich import print as rprint

from agent_eval.cli.console.prompts import ask, select


def main(session) -> None:  # noqa: ANN001 — WorkbenchSession（避免循环导入用 duck type）
    action = select(
        "场景包动作",
        ["查看包内容", "列出全部包", "校验项目包", "创建 / Agent 改包（Sprint 11）", "返回"],
    )
    if action.startswith("查看包内容"):
        _view()
    elif action.startswith("列出"):
        from agent_eval.cli.cmds.scenario import scenario_list

        scenario_list(source="all")
    elif action.startswith("校验"):
        from agent_eval.cli.cmds.scenario import scenario_validate

        path = ask("项目包根目录路径（含 agent_eval.yaml）")
        scenario_validate(Path(path))
    else:
        rprint(
            "[yellow]场景包创建（模板 / Agent 生成）与 Agent 会话改包将在 Sprint 11 提供；"
            "当前可用 `agent-eval scenario new --mode skeleton` 生成骨架。[/yellow]"
        )


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
