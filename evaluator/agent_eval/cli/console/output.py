"""输出分流与退出码集中映射（arch/15 §3.3 / D-CLI-7）。

- 退出码契约（F-C-INTEG-03）：0 成功；1 评测业务失败（含门控未达）；
  2 配置/输入错误；3 依赖不可用（LLM/SUT/平台）；130 用户中断。
- JSON 形态（F-C-INTEG-02）：``--output-format json`` 时 stdout 仅 JSON，
  人读进度/提示一律走 stderr。
"""

from __future__ import annotations

import json
import sys

import typer

__all__ = [
    "EXIT_BUSINESS",
    "EXIT_CONFIG",
    "EXIT_DEPENDENCY",
    "EXIT_INTERRUPT",
    "EXIT_OK",
    "emit_json",
    "is_json",
    "map_exit_code",
    "note",
    "set_output_format",
]

EXIT_OK = 0
EXIT_BUSINESS = 1
EXIT_CONFIG = 2
EXIT_DEPENDENCY = 3
EXIT_INTERRUPT = 130

_json_mode = False


def set_output_format(fmt: str) -> None:
    """由全局 callback 注入（--output-format text|json）。"""
    global _json_mode
    _json_mode = fmt == "json"


def is_json() -> bool:
    return _json_mode


def emit_json(payload: object) -> None:
    """机器可读输出：stdout 仅 JSON（ensure_ascii=False，default=str 容错路径等）。"""
    print(json.dumps(payload, ensure_ascii=False, default=str))


def note(message: str) -> None:
    """人读提示：JSON 模式下转 stderr，避免污染 stdout 契约。"""
    print(message, file=sys.stderr if _json_mode else sys.stdout)


def map_exit_code(exc: BaseException) -> int:
    """异常 → 退出码单点映射（新增异常不改命令层）。"""
    from agent_eval.core.exceptions import (
        AgentEvalError,
        ConfigError,
        LLMError,
        PackageError,
        ScenarioPackageError,
        SUTAuthError,
        SUTChannelError,
    )

    if isinstance(exc, KeyboardInterrupt | typer.Abort):
        return EXIT_INTERRUPT
    if isinstance(exc, typer.Exit):
        return int(exc.exit_code or EXIT_OK)
    # 配置 / 输入 / 包校验类 → 2
    if isinstance(exc, ConfigError | ScenarioPackageError | PackageError):
        return EXIT_CONFIG
    # 依赖不可用（LLM / SUT 通道与鉴权；AgentProtocolError 为 SUTChannelError 子类）→ 3
    if isinstance(exc, LLMError | SUTAuthError | SUTChannelError):
        return EXIT_DEPENDENCY
    # 其余业务失败（执行 / 评估 / 编排）→ 1
    if isinstance(exc, AgentEvalError):
        return EXIT_BUSINESS
    return EXIT_BUSINESS
