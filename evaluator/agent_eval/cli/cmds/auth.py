"""agent-eval auth — 平台账号（requirement/04 F-C-AUTH；arch/15 §5.1）。

auth 管平台身份（谁在上报、以哪个团队/项目）；secrets 管被测系统凭证——两域不混用。
身份落密钥区 ``~/.agent_eval/platform.json``（0600，与 llm.json / sut_credentials.json 三域
三文件），启动注入 env 仅补缺（env 直供优先——CI/云函数/executor 不受影响）。
登录双通道：打开平台页面创建 Key 后粘贴（浏览器，无浏览器环境自动降级打印 URL）/
直接粘贴已有 Key；`--token/--host` 为 CI 非交互形态（F-C-AUTH-07）。
`/cli-auth` 授权页与设备码流为 P2（平台侧落地后接入，arch/15 §5.2）。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import typer
from rich import print as rprint

auth_app = typer.Typer(help="平台账号（login / status / logout / register）")

# 与 observability 缺省一致（本地 docker compose 起栈的 web 端口）
DEFAULT_HOST = "http://localhost:9000"
_ENV_KEYS = ("AGENT_EVAL_HOST", "AGENT_EVAL_API_KEY", "AGENT_EVAL_PROJECT")


@dataclass
class PlatformIdentity:
    """whoami 身份回执（团队/项目）。"""

    org_name: str
    org_slug: str
    project_id: str
    project_name: str
    project_slug: str
    key_name: str


class ProbeError(Exception):
    """Key 探测失败：invalid=Key 无效/未提供；unreachable=平台不可达；server=平台异常响应。"""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def mask_key(key: str) -> str:
    """Key 掩码回显（前 8 + 后 4），完整值不落终端日志。"""
    return key if len(key) <= 12 else f"{key[:8]}…{key[-4:]}"


def _raise_for_probe(resp: httpx.Response) -> None:
    """把非 2xx 探测响应归类为 ProbeError——**任何状态都不裸抛 HTTPStatusError**。

    实测教训：空 Key 拼出畸形 ``Bearer `` 头，网关回 400 曾直接 traceback。
    """
    if resp.status_code < 400:
        return
    if resp.status_code == 401:
        raise ProbeError("invalid", "Key 无效（不存在 / 已吊销 / 已过期）")
    raise ProbeError("server", f"平台返回 HTTP {resp.status_code}（检查平台地址 / 平台版本）")


def probe_identity(
    host: str, api_key: str, *, transport: httpx.BaseTransport | None = None
) -> PlatformIdentity | None:
    """GET /api/public/whoami 探测 Key 并解析身份。

    空 Key → ProbeError(invalid)；401 → invalid；404（旧平台无 whoami）→ 回退
    GET /api/public/secrets 仅验有效性、返回 None 身份；连接失败 → unreachable；
    其余非 2xx → server。**不抛 httpx 异常**（调用方只处理 ProbeError）。
    """
    if not api_key or not api_key.strip():
        raise ProbeError("invalid", "Key 为空（未粘贴 / 未提供）")
    with httpx.Client(timeout=10, transport=transport) as client:
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            resp = client.get(f"{host}/api/public/whoami", headers=headers)
            if resp.status_code == 404:  # 旧平台：轻探测（仅验证 Key）
                fallback = client.get(f"{host}/api/public/secrets", headers=headers)
                _raise_for_probe(fallback)
                return None
        except httpx.HTTPError as e:  # 仅网络层（连接 / 超时）；ProbeError 穿透
            raise ProbeError("unreachable", f"平台不可达: {e}") from e
        _raise_for_probe(resp)
        data = resp.json()
    return PlatformIdentity(
        org_name=str(data["org"]["name"]),
        org_slug=str(data["org"]["slug"]),
        project_id=str(data["project"]["id"]),
        project_name=str(data["project"]["name"]),
        project_slug=str(data["project"]["slug"]),
        key_name=str(data["key"]["name"]),
    )


def _warn_stale_env() -> None:
    """.env 残留平台配置提示——env 优先于密钥区（登录 A 实际上报 B），归用户手工删改。"""
    from agent_eval.cli._env_file import find_env_path, platform_keys_in_env

    if stale := platform_keys_in_env(find_env_path()):
        rprint(
            f"[yellow]⚠ .env 中仍有 {len(stale)} 项平台配置（{', '.join(stale)}）——"
            "env 优先于密钥区，将以 .env 为准；如需改用密钥区请删除对应行。[/yellow]"
        )


def login_flow(token: str | None = None, host: str | None = None) -> PlatformIdentity | None:
    """``auth login`` 动作（纯函数，命令层与 workbench 复用）。"""
    from agent_eval.cli.console.prompts import ask, select

    host = (host or os.environ.get("AGENT_EVAL_HOST", "")).rstrip("/") or None
    if host is None:
        host = ask("平台地址", default=DEFAULT_HOST).rstrip("/")

    token_from_param = token is not None
    if token is None:
        if os.environ.get("AGENT_EVAL_NO_INPUT"):
            rprint("[red]❌ --no-input 下登录需直供 Key：auth login --token <api_key>[/red]")
            raise typer.Exit(code=2)
        channel = select("获取 API Key", ["打开平台页面创建（浏览器）", "直接粘贴已有 Key", "取消"])
        if channel == "取消":
            rprint("[dim]已取消。[/dim]")
            return None
        if channel.startswith("打开平台"):
            from agent_eval.cli.cmds.open_url import open_url

            open_url(f"{host}/login")
            rprint(
                "[dim]引导：登录平台 → 打开项目 →「设置 & API Key」→ 创建 API Key"
                "（scope 含 ingest）→ 回到这里粘贴。[/dim]"
            )
        token = ask("粘贴 API Key（eval- 开头，隐藏输入，直接回车取消）", hide=True)
        if not token:
            rprint("[yellow]未输入 Key，已取消。[/yellow]")
            return None

    identity: PlatformIdentity | None
    for attempt in range(3):
        try:
            identity = probe_identity(host, token)
            break
        except ProbeError as e:
            if e.kind != "invalid" or token_from_param or attempt == 2:
                rprint(f"[red]❌ 登录失败：{e}[/red]")
                rprint(f"[dim]检查平台地址 {host} 与 Key；或 agent-eval auth login 重试[/dim]")
                raise typer.Exit(code=1) from e
            rprint(f"[red]❌ {e}[/red]")
            token = ask("重新粘贴 API Key（直接回车取消）", hide=True)
            if not token:
                rprint("[yellow]未输入 Key，已取消。[/yellow]")
                return None
    else:  # pragma: no cover — for/else 兜底（break 前必 return/raise）
        return None

    updates = {"AGENT_EVAL_HOST": host, "AGENT_EVAL_API_KEY": token}
    if identity is not None:
        updates["AGENT_EVAL_PROJECT"] = identity.project_slug
    from agent_eval.config.platform_file import PlatformFileConfig, save_platform_file

    path = save_platform_file(
        PlatformFileConfig(host=host, api_key=token, project=updates.get("AGENT_EVAL_PROJECT"))
    )
    os.environ.update(updates)
    _warn_stale_env()

    if identity is None:
        rprint("[green]✅ Key 有效[/green]（平台未提供身份接口，团队/项目未知）")
    else:
        rprint(
            f"[green]✅ 已登录[/green] {identity.org_name} · 项目 "
            f"{identity.project_name}（{identity.project_slug}）"
        )
    rprint(f"[dim]Key {mask_key(token)} → {path}（0600）[/dim]")
    return identity


def status_action() -> None:
    """``auth status`` 动作：本地身份 + 平台 ping（Key 有效性 / 团队 / 项目）。"""
    from agent_eval.config.platform_file import apply_platform_env, platform_file_path

    apply_platform_env()  # 非 main 入口直调（workbench/测试）也读得到密钥区
    host = os.environ.get("AGENT_EVAL_HOST", "").rstrip("/")
    key = os.environ.get("AGENT_EVAL_API_KEY", "")
    if not (host and key):
        rprint("[yellow]未登录平台（无 platform.json，亦无 AGENT_EVAL_HOST/API_KEY env）[/yellow]")
        rprint("[dim]→ agent-eval auth login（或工作台「账号与配置」域）[/dim]")
        raise typer.Exit(code=1)
    source = platform_file_path() if platform_file_path().exists() else ".env / env 直供"
    rprint(f"平台: {host}\nKey: {mask_key(key)}\n存储: {source}")
    if project := os.environ.get("AGENT_EVAL_PROJECT", ""):
        rprint(f"项目: {project}")
    try:
        identity = probe_identity(host, key)
    except ProbeError as e:
        if e.kind == "invalid":
            rprint(f"[red]❌ {e}[/red]\n[dim]→ agent-eval auth login 重新登录[/dim]")
        elif e.kind == "server":
            rprint(f"[red]❌ {e}[/red]")  # 平台可达但异常响应，非本地网络问题
        else:
            rprint(f"[yellow]⚠ {e}[/yellow]\n[dim]本地身份如上；检查平台地址 / 网络。[/dim]")
        raise typer.Exit(code=1) from e
    if identity is not None:
        rprint(
            f"团队: {identity.org_name}（{identity.org_slug}）\n"
            f"项目: {identity.project_name}（{identity.project_slug}）"
        )
    rprint("[green]✅ Key 有效[/green]")


def logout_action(revoke: bool = False) -> None:
    """``auth logout`` 动作：删除密钥区 platform.json 与进程环境（--revoke 为 P2）。

    ``.env`` 归用户手工管理：其中有平台配置时仅提示残留（env 优先仍会生效），
    不代为删改。
    """
    from agent_eval.config.platform_file import platform_file_path

    path = platform_file_path()
    removed = path.exists()
    if removed:
        path.unlink()
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    if revoke:
        rprint(
            "[yellow]--revoke 为 P2（需平台吊销端点授权）——请到平台「设置 & API Key」手动吊销。[/yellow]"
        )
    if removed:
        rprint(f"[green]✅ 已清除本地平台凭证[/green] {path}")
    else:
        rprint("[yellow]本地未配置平台凭证（无 platform.json）[/yellow]")
    _warn_stale_env()  # 无残留时静默


def register_action(host: str | None = None) -> None:
    """``auth register`` 动作：打开平台注册页（无浏览器降级打印 URL）。"""
    from agent_eval.cli.cmds.open_url import open_url
    from agent_eval.cli.console.prompts import ask

    host = (host or os.environ.get("AGENT_EVAL_HOST", "")).rstrip("/") or ask(
        "平台地址", default=DEFAULT_HOST
    ).rstrip("/")
    open_url(f"{host}/register")
    rprint("[dim]注册完成后运行 agent-eval auth login 登录（浏览器通道会引导创建 API Key）[/dim]")


def auth_wizard() -> None:
    """工作台「平台账号」交互子向导（纯函数动作，workbench 复用）。"""
    from agent_eval.cli.console.prompts import select

    actions: dict[str, Callable[[], object]] = {
        "登录": lambda: login_flow(),
        "状态": status_action,
        "退出登录": logout_action,
        "注册账号": lambda: register_action(),
    }
    while True:
        choice = select("平台账号", [*actions, "返回"])
        if choice == "返回":
            return
        try:
            actions[choice]()
        except typer.Exit as e:
            if e.exit_code:  # 状态探测失败等：提示后留在本向导
                rprint(f"[dim]（动作退出码 {e.exit_code}，继续）[/dim]")


@auth_app.command("login")
def login(
    token: str | None = typer.Option(None, "--token", help="直供 API Key（CI 无浏览器形态）"),
    host: str | None = typer.Option(None, "--host", help="平台地址（缺省 .env 或本地 9000）"),
) -> None:
    """登录平台：浏览器创建 / 粘贴 API Key → 有效性探测 → 写密钥区（0600）。"""
    login_flow(token=token, host=host)


@auth_app.command("status")
def status() -> None:
    """平台身份体检：本地凭证 + Key 有效性 + 团队 / 项目归属。"""
    status_action()


@auth_app.command("logout")
def logout(
    revoke: bool = typer.Option(False, "--revoke", help="同时吊销平台侧 Key（P2，暂仅提示）"),
) -> None:
    """清除本地平台凭证（密钥区 + 进程 env）。"""
    logout_action(revoke=revoke)


@auth_app.command("register")
def register(
    host: str | None = typer.Option(None, "--host", help="平台地址（缺省 .env 或本地 9000）"),
) -> None:
    """打开平台注册页，完成后引导 auth login。"""
    register_action(host=host)
