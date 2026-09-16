"""agent-eval models — LLM 配置管理（交互式向导，arch/06 §4.6 CLI 形态）。

向导式选择**提供商 × 协议**、隐藏输入 api-key，保存到 ``~/.agent_eval/llm.json``
（0600）。密钥不打印、不入日志。Sprint 10 命令重命名：``login/logout`` →
``set/clear``（「login」语义保留给平台账号 auth，requirement/04 §3.3）。

向导两层选择（厂商与协议正交）：预置厂商（deepseek/kimi/zhipu/minimax）均提供
anthropic 与 openai 兼容双协议、端点由 ``(厂商, 协议)`` 预置矩阵给出（免输
URL）；custom 需自备 base_url。角色只问 text/vision——agent 角色为执行引擎/
工作台 Agent 专用（``--llm-role`` 可覆盖），未配置时解析层自动回退 text，不进
向导（已有配置原样保留）。
"""

from __future__ import annotations

import time

import typer
from rich import print as rprint
from rich.table import Table

models_app = typer.Typer(help="LLM 模型配置管理（set / list / test / clear）")

_PROTOCOL_LABELS = {"anthropic": "Anthropic 协议", "openai": "OpenAI 兼容协议"}
_CUSTOM_LABEL = "custom（自定义，自备 base_url / 模型 / api_key）"


def _mask(secret: str) -> str:
    return f"{secret[:4]}…{secret[-4:]}" if len(secret) > 8 else "****"


def _test_configured_roles() -> bool:
    """对已配置角色做连通性测试（真实调用一次对话接口）；返回是否存在失败。

    ``set`` 保存后与 ``test`` 命令共用；结果逐角色打印，由调用方决定退出码
    （命令形态 exit 1 供脚本判断，向导形态不打断——返回调用菜单后可改 Key 重测）。
    """
    from agent_eval.config.llm import ProviderConfig
    from agent_eval.config.llm_file import ROLES, effective_protocol, load_llm_file
    from agent_eval.llm.factory import LLMClientFactory
    from agent_eval.llm.models import Message

    cfg = load_llm_file()
    if cfg is None or not any(cfg.roles.get(r) for r in ROLES):
        rprint("[yellow]未配置模型。运行 [/yellow][bold]agent-eval models set[/bold]")
        return True

    failed = False
    for role in ROLES:
        rc = cfg.roles.get(role)
        if rc is None:
            rprint(f"[dim]· {role}: 跳过（未配置）[/dim]")
            continue
        try:
            client = LLMClientFactory.create(
                role,
                ProviderConfig(
                    # 分发键归一为线路协议（厂商键自定义 provider 不被工厂识别）
                    provider=effective_protocol(rc.provider, rc.protocol),
                    model=rc.model,
                    api_key=rc.api_key,
                    base_url=rc.base_url,
                ),
            )
            start = time.perf_counter()
            resp = client.chat([Message(role="user", content="ping，请只回复 pong")])
            ms = (time.perf_counter() - start) * 1000
            text = (resp.content or "").strip()[:40]
            rprint(f"[green]✅ {role}[/green] {rc.model} — {ms:.0f}ms：「{text}」")
        except Exception as e:  # noqa: BLE001 — 连通性测试需如实报告任何失败
            failed = True
            rprint(f"[red]❌ {role}[/red] {rc.model} — {e}")
    return failed


@models_app.command("set")
def models_set() -> None:
    """交互式配置模型（提供商/协议/模型/api-key），保存到 ~/.agent_eval/llm.json（0600）。"""
    from agent_eval.cli.console.prompts import select
    from agent_eval.config.llm_file import (
        PROTOCOLS,
        PROVIDER_DEFAULT_BASE_URLS,
        PROVIDER_LABELS,
        PROVIDER_MODEL_SUGGESTIONS,
        PROVIDERS,
        LLMFileConfig,
        RoleConfig,
        llm_file_path,
        load_llm_file,
        save_llm_file,
    )

    existing = load_llm_file() or LLMFileConfig()
    rprint("[bold]═ LLM 配置向导 ═[/bold]（保存到 " + str(llm_file_path()) + "，权限 0600）")

    # ① 提供商（预置厂商 + custom）
    vendor_options = [PROVIDER_LABELS[v] for v in PROVIDERS] + [_CUSTOM_LABEL]
    vendor_choice = select("选择提供商", vendor_options)
    is_custom = vendor_choice == _CUSTOM_LABEL
    vendor = "custom" if is_custom else PROVIDERS[vendor_options.index(vendor_choice)]

    # ② 协议（所有厂商均双协议提供；分发键随之确定）
    protocol_options = [_PROTOCOL_LABELS[p] for p in PROTOCOLS]
    protocol = PROTOCOLS[protocol_options.index(select("选择协议", protocol_options))]

    # ③ 端点：预置厂商直接采用 (厂商, 协议) 端点（展示不提问）；custom 必答
    if is_custom:
        current_text = existing.roles.get("text")
        base_url = str(
            typer.prompt(
                "API Base URL", default=(current_text.base_url if current_text else "") or ""
            )
        ).strip()
        if not base_url.startswith(("http://", "https://")):
            rprint("[red]Base URL 需以 http:// 或 https:// 开头，已取消。[/red]")
            raise typer.Exit(code=1)
    else:
        base_url = PROVIDER_DEFAULT_BASE_URLS[(vendor, protocol)]
        rprint(
            f"[blue]· 使用预置端点[/blue]（{PROVIDER_LABELS[vendor]} × {_PROTOCOL_LABELS[protocol]}）: {base_url}"
        )

    api_key = typer.prompt("API Key（隐藏输入）", hide_input=True, default="").strip()
    if not api_key:
        rprint("[red]未输入 API Key，已取消。[/red]")
        raise typer.Exit(code=1)

    def ask_model(role: str) -> str | None:
        # text 为建议必配角色（默认确认），vision 已配置才默认确认
        want = True if role == "text" else bool(existing.roles.get(role))
        if not typer.confirm(f"配置 {role} 角色", default=want):
            return None
        current = existing.roles.get(role)
        default_model = (current.model if current else None) or PROVIDER_MODEL_SUGGESTIONS[vendor][
            role
        ]
        if not default_model:
            return str(typer.prompt(f"  {role} 模型 ID"))
        return str(typer.prompt(f"  {role} 模型 ID", default=default_model))

    roles: dict[str, RoleConfig | None] = {}
    for role in ("text", "vision"):
        model = ask_model(role)
        if model is None:
            roles[role] = None
            continue
        roles[role] = RoleConfig(
            provider=vendor,
            protocol=protocol,
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=8192,
            temperature=0.0,
            seed=42,
        )
    # agent 角色（执行引擎/工作台 Agent 专用，--llm-role 可覆盖）不进向导：未配置时
    # 解析层自动回退 text；已有配置（手改 llm.json）原样保留不被冲掉
    roles["agent"] = existing.roles.get("agent")
    if roles.get("text") is None and roles.get("vision") is None and roles.get("agent") is None:
        rprint("[red]至少需配置一个角色（text 建议必配），已取消。[/red]")
        raise typer.Exit(code=1)

    path = save_llm_file(LLMFileConfig(roles=roles))
    rprint(f"[green]✅ 已保存[/green] {path}（0600）")
    # 保存即验证（真实调用一次对话接口）；失败不打断——返回调用菜单（工作台账号域
    # 或 CLI）后可改 Key 重测，退出码语义由 test 命令承载
    if typer.confirm("立即测试连通性", default=True):
        if _test_configured_roles():
            rprint(
                "[yellow]连通性测试未全部通过——检查 API Key/网络后重跑"
                " [bold]agent-eval models test[/bold][/yellow]"
            )
        else:
            rprint("[green]连通性测试全部通过[/green]")
    rprint("[blue]下一步:[/blue] agent-eval models list 查看；工作台/评测将按角色自动取用")


@models_app.command("list")
def list_models() -> None:
    """查看当前模型配置（api-key 脱敏）。"""
    from agent_eval.config.llm_file import ROLES, effective_protocol, llm_file_path, load_llm_file

    cfg = load_llm_file()
    if cfg is None:
        rprint(
            f"[yellow]未配置（{llm_file_path()} 不存在）。运行 [/yellow][bold]agent-eval models set[/bold]"
        )
        raise typer.Exit(code=1)

    table = Table(title="LLM 模型配置")
    table.add_column("角色", style="bold")
    table.add_column("提供商")
    table.add_column("协议")
    table.add_column("模型")
    table.add_column("Base URL")
    table.add_column("API Key")
    for role in ROLES:
        rc = cfg.roles.get(role)
        if rc is None:
            note = "回退 text" if role == "agent" else "未配置"
            table.add_row(role, f"[dim]{note}[/dim]", "—", "—", "—", "—")
        else:
            table.add_row(
                role,
                rc.provider,
                effective_protocol(rc.provider, rc.protocol),
                rc.model,
                rc.base_url or "（官方端点）",
                _mask(rc.api_key),
            )
    rprint(table)


@models_app.command()
def test() -> None:
    """对已配置角色做连通性测试（真实调用一次对话接口）。"""
    if _test_configured_roles():
        raise typer.Exit(code=1)


@models_app.command("clear")
def models_clear() -> None:
    """删除本地 LLM 配置文件（含 api-key）。"""
    from agent_eval.config.llm_file import llm_file_path

    path = llm_file_path()
    if not path.exists():
        rprint("[yellow]无本地配置可删除。[/yellow]")
        return
    if not typer.confirm(f"确认删除 {path}（含 api-key）", default=False):
        rprint("已取消。")
        return
    path.unlink()
    rprint(f"[green]✅ 已删除[/green] {path}")
