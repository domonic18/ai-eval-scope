"""CLI 入口 — 组装顶层命令与子命令组。

顶层命令（pack/eval/run/pipeline/upload/version）定义在 ``main``，
子命令组（rule-set/dataset/knowledge）各自独立模块，在此统一挂载到 ``app``。

入口：``agent-eval = "agent_eval.cli:app"``
"""

from agent_eval.cli.dataset import dataset_app
from agent_eval.cli.knowledge import knowledge_app
from agent_eval.cli.main import app
from agent_eval.cli.rule_set import rule_app

app.add_typer(rule_app)
app.add_typer(dataset_app)
app.add_typer(knowledge_app)

__all__ = ["app"]
