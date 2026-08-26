"""执行层共享工具。"""

from __future__ import annotations

from typing import Any

from agent_eval.core.exceptions import ToolExecutionError


def extract_by_path(data: Any, path: str) -> Any:
    """按点分路径提取字段值（数字段表示列表下标），如 "choices.0.message.content"。

    供 invoke_http_sut 的 response_mapping、api_login 的 token_path、
    Agent Protocol 的 output_paths 共用。
    """
    current = data
    for segment in path.split("."):
        if isinstance(current, dict):
            if segment not in current:
                raise ToolExecutionError(
                    f"点分路径无法解析: {path!r}（键 {segment!r} 不存在）",
                    details={"path": path, "segment": segment},
                )
            current = current[segment]
        elif isinstance(current, list) and segment.lstrip("-").isdigit():
            index = int(segment)
            if index >= len(current):
                raise ToolExecutionError(
                    f"点分路径无法解析: {path!r}（下标 {index} 越界）",
                    details={"path": path, "segment": segment},
                )
            current = current[index]
        else:
            raise ToolExecutionError(
                f"点分路径无法解析: {path!r}（当前节点类型 {type(current).__name__}）",
                details={"path": path, "segment": segment},
            )
    return current
