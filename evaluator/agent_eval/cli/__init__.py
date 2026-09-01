"""CLI 入口 — 唯一装配点（arch/15 §2.2 组织约定 1）。

新增命令（组或顶层）= ``cmds/`` 新模块 + 此处一行注册，其余零改动。
入口：``agent-eval = "agent_eval.cli:app"``
"""

from agent_eval.cli.cmds.auth import auth_app
from agent_eval.cli.cmds.dataset import dataset_app
from agent_eval.cli.cmds.evaluate import eval as eval_cmd
from agent_eval.cli.cmds.execute import pipeline, run
from agent_eval.cli.cmds.knowledge import knowledge_app
from agent_eval.cli.cmds.models import models_app
from agent_eval.cli.cmds.pack import pack
from agent_eval.cli.cmds.rule_set import rule_app
from agent_eval.cli.cmds.runs import runs_app
from agent_eval.cli.cmds.scenario import scenario_app
from agent_eval.cli.cmds.secrets import secrets_app
from agent_eval.cli.cmds.suite import suite_app
from agent_eval.cli.cmds.upload import upload
from agent_eval.cli.main import app

# ── 顶层命令（cmds/ 定义绑定，此处注册）──
app.command()(pack)
app.command()(eval_cmd)
app.command()(run)
app.command()(pipeline)
app.command()(upload)

# ── 子命令组 ──
app.add_typer(auth_app, name="auth")  # Sprint 11：平台账号（login/status/logout/register）
app.add_typer(scenario_app)  # Sprint 10 重命名：原 package 组
app.add_typer(runs_app)
app.add_typer(models_app, name="models")
app.add_typer(secrets_app, name="secrets")
app.add_typer(suite_app, name="suite")
app.add_typer(rule_app)
app.add_typer(dataset_app)
app.add_typer(knowledge_app)

__all__ = ["app"]
