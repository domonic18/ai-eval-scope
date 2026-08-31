"""agent-eval scenario — 场景包子命令（new / show / validate / list / pull）。

对齐 13 配置管理设计 §四/§五。Sprint 10 重命名：原 ``package`` 组更名 ``scenario``
（消除与顶层 ``pack``「打包执行包」的名词冲突），``init`` 并入 ``new --mode skeleton``。
"""

from __future__ import annotations

from pathlib import Path

import typer

from agent_eval.cli._common import Table, rprint

scenario_app = typer.Typer(name="scenario", help="场景包管理：new / show / validate / list / pull")


def _scaffold(ref: str, output: Path | None, template: str, force: bool) -> Path:
    """按模板生成场景包目录骨架（原 package init 逻辑）。"""
    from agent_eval.packages import parse_ref

    scenario, package_id, _ = parse_ref(ref)
    package_id = package_id or scenario
    root = Path(output) if output else Path.cwd() / package_id
    if root.exists() and any(root.iterdir()) and not force:
        rprint(f"[red]❌ 目标目录非空: {root}（用 --force 覆盖）[/red]")
        raise typer.Exit(code=1)

    for sub in ("rules", "prompts", "datasets"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    manifest = (
        f"# 场景包清单（template={template}）\n"
        f"package:\n"
        f"  id: {package_id}\n"
        f"  scenario: {scenario}\n"
        f"  version: 0.1.0\n"
        f"  name: {package_id}\n"
        f"  description: TODO\n"
        f'  author: ""\n'
        f"  labels: [latest]\n"
    )
    (root / "agent_eval.yaml").write_text(manifest, encoding="utf-8")
    return root


@scenario_app.command("new")
def scenario_new(
    ref: str | None = typer.Argument(
        None,
        help="scenario/package 引用（如 travel-itinerary/quality）；skeleton 必填，"
        "agent 模式可省——Agent 按需求拟定包名，会话中自然语言可改",
    ),
    mode: str = typer.Option(
        "skeleton",
        "--mode",
        "-m",
        help="skeleton=目录骨架（原 init）| agent=自然语言生成（REPL 会话）| template（P2）",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="输出目录（skeleton 默认 ./<id>/；agent 默认 workspace/scenario-packages/<id>-package/）",
    ),
    template: str = typer.Option(
        "courseware", "--template", "-t", help="脚手架模板（skeleton 模式）"
    ),
    force: bool = typer.Option(False, "--force", help="目标目录非空时强制覆盖（仅 skeleton）"),
    instruction: str | None = typer.Option(
        None, "--instruction", "-i", help="Agent 模式：评测需求描述（缺省进入交互输入）"
    ),
    yes: bool = typer.Option(False, "--yes", help="Agent 模式非交互确认（需配合 --trust-agent）"),
    trust_agent: bool = typer.Option(
        False, "--trust-agent", help="非交互放行写盘（CI 用；默认关闭，交互确认）"
    ),
) -> None:
    """创建场景包（skeleton 骨架 / agent 自然语言生成 / template 模板）。"""
    if mode == "skeleton":
        if not ref:
            rprint("[red]❌ skeleton 模式需要 REF（如 travel-itinerary/quality）[/red]")
            raise typer.Exit(code=2)
        root = _scaffold(ref, output, template, force)
        rprint(f"[green]✅ 已创建场景包[/green] → {root}")
        rprint(
            f"[dim]下一步：在 rules/ prompts/ datasets/ 中填充资产，"
            f"再 `agent-eval scenario validate {root}`[/dim]"
        )
        return
    if mode == "agent":
        from agent_eval.cli.cmds.scenario_agent import agent_new_package

        root = agent_new_package(
            ref=ref,
            output=output,
            instruction=instruction,
            yes=yes,
            trust_agent=trust_agent,
        )
        rprint(
            f"[green]✅ 场景包已生成[/green] → {root}\n"
            f"[dim]校验: agent-eval scenario validate {root}；"
            f"查看: agent-eval scenario show {root}[/dim]"
        )
        return
    rprint(f"[yellow]--mode {mode} 暂未提供（当前支持 skeleton | agent）。[/yellow]")
    raise typer.Exit(code=1)


@scenario_app.command("edit")
def scenario_edit(
    ref: str | None = typer.Argument(
        None, help="项目包路径或本地包引用（内置包只读会被拒绝）；缺省进入交互选择"
    ),
    instruction: str | None = typer.Option(
        None, "--instruction", "-i", help="首轮需求（缺省进入 REPL 会话自由输入）"
    ),
    yes: bool = typer.Option(False, "--yes", help="非交互确认（需配合 --trust-agent）"),
    trust_agent: bool = typer.Option(
        False, "--trust-agent", help="非交互放行写盘（CI 用；默认关闭，交互确认）"
    ),
) -> None:
    """Agent 会话改包：自然语言增删改查（沙盒 + diff 确认 + 校验门禁）。"""
    from agent_eval.cli.cmds.scenario_agent import agent_edit_package

    if ref is None:
        ref = select_editable_ref()
    agent_edit_package(ref=ref, instruction=instruction, yes=yes, trust_agent=trust_agent)


def _resolve_root(ref: str) -> tuple[Path, object]:
    """按路径或包引用解析包根（路径含 agent_eval.yaml 优先）。"""
    from agent_eval.packages import MANIFEST_FILENAME, PackageManager, load_manifest

    path = Path(ref)
    if (path / MANIFEST_FILENAME).is_file():
        return path, load_manifest(path)
    try:
        pkg = PackageManager().resolve_ref(ref)
    except Exception as e:  # noqa: BLE001 — 统一转为可读错误
        rprint(f"[red]❌ 无法解析场景包 {ref}: {e}[/red]")
        raise typer.Exit(code=1) from e
    return pkg.root, pkg.manifest


def _count_lines(path: Path) -> int:
    """文本文件行数（YAML 资产的信息量在行数而非字节）；二进制/不可读计 0。"""
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return 0


def show_scenario(ref: str, section: str = "tree") -> None:
    """展示场景包内容（纯函数动作，workbench 复用）。

    section: tree（结构树）| manifest（清单）| rules（规则集表）| tasks（考卷）| sut（SUT 概览）
    """
    import yaml

    root, manifest = _resolve_root(ref)
    m = manifest

    if section == "tree":
        rprint(f"[bold]📦 {m.ref}[/bold]")
        rprint(f"[dim]{root}[/dim]\n")
        entries = sorted(p for p in root.rglob("*") if ".git" not in p.parts and p.is_file())
        groups: dict[str, list[tuple[str, int]]] = {}
        for p in entries:
            rel = p.relative_to(root)
            d = rel.parent.as_posix() if str(rel.parent) != "." else "(根)"
            groups.setdefault(d, []).append((rel.name, _count_lines(p)))
        total = 0
        for d in sorted(groups, key=lambda k: (k != "(根)", k)):
            rprint(f"  [bold]{d if d == '(根)' else d + '/'}[/bold]")
            for name, n in groups[d]:
                total += n
                rprint(f"    [cyan]{name}[/cyan] [dim]· {n} 行[/dim]")
        rprint(f"\n  [dim]合计 {len(entries)} 个文件 · {total} 行[/dim]")
        return

    if section == "manifest":
        table = Table(title=f"包清单 — {m.ref}")
        table.add_column("字段", style="bold")
        table.add_column("值")
        table.add_row("id", m.id)
        table.add_row("scenario", m.scenario)
        table.add_row("version", m.version)
        table.add_row("name", m.name or "—")
        table.add_row("labels", ",".join(m.labels) or "—")
        table.add_row("default_task_set", m.default_task_set or "（task_sets/ 下唯一）")
        table.add_row("default_rule_set", m.default_rule_set or "（rules/ 下唯一）")
        rprint(table)
        return

    if section == "rules":
        rule_files = sorted((root / "rules").glob("*.yaml")) if (root / "rules").is_dir() else []
        if not rule_files:
            rprint("[yellow]包内无 rules/ 规则集[/yellow]")
            return
        for rf in rule_files:
            data = yaml.safe_load(rf.read_text(encoding="utf-8")) or {}
            rules = data.get("rules", [])
            mark = " [dim](default)[/dim]" if m.default_rule_set == rf.stem else ""
            rprint(f"[bold]📋 {rf.stem}[/bold]{mark} — {len(rules)} 条规则")
            table = Table(show_header=True)
            table.add_column("id")
            table.add_column("评估器")
            table.add_column("阶段")
            table.add_column("权重", justify="right")
            table.add_column("启用")
            for r in rules:
                table.add_row(
                    str(r.get("id", "—")),
                    str(r.get("evaluator", "—")),
                    str(r.get("stage", "—")),
                    str(r.get("weight", 1.0)),
                    "✅" if r.get("enabled", True) else "⛔",
                )
            rprint(table)
        return

    if section == "tasks":
        ts_dir = root / "task_sets"
        if not ts_dir.is_dir():
            rprint("[yellow]包内无 task_sets/ 考卷[/yellow]")
            return
        for tf in sorted(ts_dir.glob("*.yaml")):
            data = yaml.safe_load(tf.read_text(encoding="utf-8")) or {}
            tasks = data.get("tasks", [])
            mark = " [dim](default)[/dim]" if m.default_task_set == tf.stem else ""
            rprint(f"[bold]📝 {tf.stem}[/bold]{mark} — {len(tasks)} 个任务")
            for t in tasks[:5]:
                rprint(f"  • {t.get('id', '—')}")
            if len(tasks) > 5:
                rprint(f"  [dim]… 共 {len(tasks)} 个[/dim]")
        return

    if section == "sut":
        sut_dir = root / "sut_configs"
        if not sut_dir.is_dir():
            rprint("[yellow]包内无 sut_configs/（eval-only 型场景）[/yellow]")
            return
        table = Table(title="SUT 接入概览（不含凭证）")
        table.add_column("配置", style="bold")
        table.add_column("channel")
        table.add_column("base_url")
        table.add_column("鉴权")
        table.add_column("credential_ref")
        for sf in sorted(sut_dir.glob("*.yaml")):
            data = yaml.safe_load(sf.read_text(encoding="utf-8")) or {}
            sut = data.get("sut", data)
            auth = sut.get("auth") or {}
            table.add_row(
                sf.stem,
                str(sut.get("channel", sut.get("driver", "—"))),
                str(sut.get("base_url", "—")),
                str(auth.get("type", "none")),
                str(auth.get("credential_ref", "—")),
            )
        rprint(table)
        return

    rprint(f"[red]未知 --section: {section}（tree|manifest|rules|tasks|sut）[/red]")
    raise typer.Exit(code=2)


@scenario_app.command("show")
def scenario_show(
    ref: str | None = typer.Argument(
        None, help="包引用（如 chat）或包根目录路径；缺省进入交互选择"
    ),
    section: str = typer.Option(
        "tree", "--section", "-s", help="tree | manifest | rules | tasks | sut"
    ),
) -> None:
    """查看场景包内容（结构 / 清单 / 规则集 / 考卷 / SUT 概览）。"""
    show_scenario(select_scenario_ref() if ref is None else ref, section)


def select_editable_ref() -> str:
    """``scenario edit`` 交互选择：内置包只读不入列，另给手动输入路径入口。"""
    from agent_eval.cli.console.prompts import ask, select
    from agent_eval.packages import PackageManager

    editable = [p for p in PackageManager().list() if p.source != "builtin"]
    options = [f"{p.manifest.ref}  ({p.source})" for p in editable] + ["📁 输入项目包目录路径…"]
    pick = select("选择要改的包（内置包只读）", options)
    if pick.startswith("📁"):
        path = ask("项目包根目录路径（含 agent_eval.yaml）")
        if not path.strip():
            raise typer.Exit(code=2)
        return path.strip()
    return pick.split("  (")[0]


def select_scenario_ref(env_key: str = "AGENT_EVAL_SCENARIO_REF") -> str:
    """REF 缺省时的交互选择（gh run view 同款无参路径；--no-input 下 env 唯一前缀旁路）。"""
    from agent_eval.cli.console.prompts import resolve_bypass, select
    from agent_eval.packages import PackageManager

    pkgs = PackageManager().list()
    if not pkgs:
        rprint("[red]❌ 未发现场景包（agent-eval scenario list 查看）[/red]")
        raise typer.Exit(code=2)
    options = [f"{p.manifest.ref}  ({p.source})" for p in pkgs]
    bypassed = resolve_bypass(env_key, options)
    return bypassed.split("  (")[0] if bypassed else select("选择场景包", options).split("  (")[0]


@scenario_app.command("validate")
def scenario_validate(
    path: Path = typer.Argument(..., help="包根目录（含 agent_eval.yaml）"),
) -> None:
    """校验场景包：清单合法、资源目录存在、规则 YAML 可解析。"""
    import yaml

    from agent_eval.core.exceptions import ScenarioPackageValidationError
    from agent_eval.packages import load_manifest

    try:
        manifest = load_manifest(path)
    except ScenarioPackageValidationError as e:
        rprint(f"[red]❌ 清单校验失败: {e}[/red]")
        raise typer.Exit(code=1) from e

    problems: list[str] = []
    for sub in ("rules", "prompts", "datasets"):
        d = path / sub
        if not d.is_dir():
            problems.append(f"缺少资源目录: {sub}/")
    # 约定：rules/ prompts/ 资产是 YAML（13 配置管理）——只写 .md 会被加载器忽略
    for sub in ("rules", "prompts"):
        d = path / sub
        if d.is_dir() and not any(d.glob("*.yaml")):
            problems.append(f"{sub}/ 缺少 YAML 资产（提示词/规则集须为 .yaml）")

    rule_files = sorted((path / "rules").glob("*.yaml")) if (path / "rules").is_dir() else []
    for rf in rule_files:
        try:
            yaml.safe_load(rf.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            problems.append(f"规则 YAML 解析失败 {rf.name}: {e}")

    if problems:
        rprint(f"[red]❌ 校验失败（{len(problems)} 项）:[/red]")
        for p in problems:
            rprint(f"  • {p}")
        raise typer.Exit(code=1)

    rprint(
        f"[green]✅ 校验通过[/green] {manifest.ref} "
        f"(rules={len(rule_files)}, prompts={len(list((path / 'prompts').glob('*.yaml')))})"
    )


@scenario_app.command("list")
def scenario_list(
    source: str = typer.Option(
        "all", "--source", "-s", help="all | builtin | local | project（当前目录下生成的包）"
    ),
) -> None:
    """列出场景包（内置 / 本地缓存 / 项目目录）。"""
    from agent_eval.packages import PackageManager

    if source not in ("all", "builtin", "local", "project"):
        rprint("[red]--source 仅支持 all/builtin/local[/red]")
        raise typer.Exit(code=1)

    pkgs = PackageManager().list(source=source)
    if not pkgs:
        rprint(f"[dim]无场景包（source={source}）[/dim]")
        return

    table = Table(title=f"场景包（{source}，{len(pkgs)} 个）")
    table.add_column("ref", style="cyan")
    table.add_column("名称")
    table.add_column("版本")
    table.add_column("标签")
    table.add_column("来源")
    for p in pkgs:
        table.add_row(
            p.manifest.ref,
            p.manifest.name or p.manifest.id,
            p.manifest.version,
            ",".join(p.manifest.labels) or "—",
            p.source,
        )
    rprint(table)


@scenario_app.command("pull")
def scenario_pull(
    ref: str = typer.Argument(..., help="scenario/package:version_or_label"),
    remote: str | None = typer.Option(
        None,
        "--remote",
        help="远端仓库基址（如 http://localhost:9000）；默认读 AGENT_EVAL_REGISTRY_URL",
    ),
) -> None:
    """从线上拉取场景包到本地缓存（~/.agent_eval/packages/）。"""
    from agent_eval.packages import PackageStore, get_remote_client
    from agent_eval.packages.remote_client import HttpRemotePackageClient

    client = HttpRemotePackageClient(remote) if remote else get_remote_client()
    if client is None:
        rprint(
            "[yellow]⚠ 远端拉取未配置。[/yellow]\n"
            "[dim]设置环境变量 AGENT_EVAL_REGISTRY_URL（Web 平台基址）或用 --remote <base_url>。[/dim]"
        )
        raise typer.Exit(code=1)

    try:
        remote_pkg = client.fetch(ref)
    except Exception as e:  # noqa: BLE001
        rprint(f"[red]❌ 拉取失败: {e}[/red]")
        raise typer.Exit(code=1) from e

    root = PackageStore().install(remote_pkg.manifest, dict(remote_pkg.files))
    rprint(f"[green]✅ 已拉取[/green] {remote_pkg.manifest.ref} → {root}")
