"""等价命令 argv 构造 — 单点映射（arch/15 §3.4 / 组织约定 3）。

向导动作与命令行调用共用同一参数对象，argv 由本模块从该参数对象组装，
与实际执行天然同源、不会漂移（F-C-NAV-05）。
"""

from __future__ import annotations

import shlex

__all__ = ["eval_argv", "pipeline_argv", "render", "run_argv", "upload_argv"]


def _argv(cmd: str, **flags: object) -> list[str]:
    argv = ["agent-eval", cmd]
    for key, value in flags.items():
        if value is None or value is False or value == "":
            continue
        name = "--" + key.replace("_", "-")
        if value is True:
            argv.append(name)
        else:
            argv.extend([name, str(value)])
    return argv


def run_argv(**flags: object) -> list[str]:
    return _argv("run", **flags)


def pipeline_argv(**flags: object) -> list[str]:
    return _argv("pipeline", **flags)


def eval_argv(**flags: object) -> list[str]:
    return _argv("eval", **flags)


def upload_argv(run: str, workspace: str = "./workspace") -> list[str]:
    return _argv("upload", run=run, workspace=workspace)


def render(argv: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)
