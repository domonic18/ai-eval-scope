"""SDK 入口 — Python SDK 封装。

提供 Python 编程接口，供外部程序调用评估系统。
"""

from __future__ import annotations

from agent_eval.config.loader import ConfigLoader
from agent_eval.execution.models import AgentConfig, Task, TaskSet
from agent_eval.rules.models import RuleSet
from agent_eval.storage.builder import PackageBuilder
from agent_eval.storage.collector import DirectoryCollector
from agent_eval.storage.package import ExecutionPackage, EvaluationResult
from agent_eval.storage.workspace import Workspace

__all__ = [
    "ConfigLoader",
    "AgentConfig",
    "Task",
    "TaskSet",
    "RuleSet",
    "PackageBuilder",
    "DirectoryCollector",
    "ExecutionPackage",
    "EvaluationResult",
    "Workspace",
]
