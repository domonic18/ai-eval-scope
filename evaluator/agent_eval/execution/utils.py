"""执行层共享工具。"""

from __future__ import annotations

from typing import Any

from agent_eval.core.exceptions import ToolExecutionError


def _path_segments(path: str) -> list[str]:
    """路径段归一化：点分为主，``key[-1]`` 方括号形式拆成两段（LLM 自然写法）。

    实测教训：jxb 配置写 ``data.messages[-1].content``，方括号形式此前不被
    支持 → 未命中 → 静默兜底整包文本（假成功）。
    """
    segments: list[str] = []
    for raw in path.split("."):
        seg = raw.strip()
        if seg.endswith("]") and "[" in seg:
            base, _, bracket = seg.partition("[")
            index = bracket.rstrip("]")
            if base:
                segments.append(base)
            segments.append(index)
        else:
            segments.append(seg)
    return segments


def extract_by_path(data: Any, path: str) -> Any:
    """按点分路径提取字段值（数字段表示列表下标，负下标从尾部计数）。

    如 ``choices.0.message.content`` / ``data.messages.-1.content`` /
    ``data.messages[-1].content``（方括号等价点分）。

    供 invoke_http_sut 的 response_mapping、api_login 的 token_path、
    Agent Protocol 的 output_paths、generic_http 的链式提取共用。
    """
    current = data
    for segment in _path_segments(path):
        if isinstance(current, dict):
            if segment not in current:
                raise ToolExecutionError(
                    f"点分路径无法解析: {path!r}（键 {segment!r} 不存在）",
                    details={"path": path, "segment": segment},
                )
            current = current[segment]
        elif isinstance(current, list) and segment.lstrip("-").isdigit():
            index = int(segment)
            # 正负双向防越界（此前负越界会漏成裸 IndexError）
            if index >= len(current) or index < -len(current):
                raise ToolExecutionError(
                    f"点分路径无法解析: {path!r}（下标 {index} 越界，长度 {len(current)}）",
                    details={"path": path, "segment": segment},
                )
            current = current[index]
        else:
            raise ToolExecutionError(
                f"点分路径无法解析: {path!r}（当前节点类型 {type(current).__name__}）",
                details={"path": path, "segment": segment},
            )
    return current
