"""执行层共享工具。"""

from __future__ import annotations

from typing import Any

from agent_eval.core.exceptions import ToolExecutionError

# 路径段：普通段为 str；过滤段为 (key, value) 元组——对当前列表按字段过滤
_Segment = str | tuple[str, str]


def _path_segments(path: str) -> list[_Segment]:
    """路径段归一化：点分为主，方括号拆成下标段或过滤段（LLM 自然写法）。

    - ``key[-1]`` → 下标段 ``-1``（负下标从尾部计数）
    - ``key[role=assistant]`` → 过滤段 ``(role, assistant)``（对列表按字段过滤）

    实测教训：jxb 配置写 ``data.messages[-1].content``，方括号形式此前不被
    支持 → 未命中 → 静默兜底整包文本（假成功）；SSE 事件流的答案帧位置
    不定（thought 帧数可变），固定下标取不到，须按 ``[type=content]`` 过滤。
    """
    segments: list[_Segment] = []
    for raw in path.split("."):
        seg = raw.strip()
        if seg.endswith("]") and "[" in seg:
            base, _, bracket = seg.partition("[")
            inner = bracket.rstrip("]")
            if "=" in inner and not inner.lstrip("-").isdigit():
                key, _, value = inner.partition("=")
                if base:
                    segments.append(base)
                segments.append((key.strip(), value.strip()))
                continue
            if base:
                segments.append(base)
            segments.append(inner)
        else:
            segments.append(seg)
    return segments


def _filter_match(element: Any, key: str, value: str) -> bool:
    """过滤谓词：字典元素的 key 值与目标值字符串等值（小写归一，兼容 JSON 布尔/数字）。"""
    if not isinstance(element, dict) or key not in element:
        return False
    return str(element[key]).lower() == value.lower()


def extract_by_path(data: Any, path: str) -> Any:
    """按点分路径提取字段值（数字段表示列表下标，负下标从尾部计数）。

    如 ``choices.0.message.content`` / ``data.messages.-1.content`` /
    ``data.messages[-1].content``（方括号等价点分）。

    过滤段 ``列表字段[k=v]`` 先按字段过滤再继续后续段，用于「答案帧位置不定」
    的响应形态：``events[type=content].-1.content``（取末个 content 帧）、
    ``data.messages[role=assistant].-1.content``（取末条助手消息）。
    过滤未命中 → 报错（fail-loud，不静默兜底）。

    供 invoke_http_sut 的 response_mapping、api_login 的 token_path、
    Agent Protocol 的 output_paths、generic_http 的链式提取共用。
    """
    current = data
    for segment in _path_segments(path):
        if isinstance(segment, tuple):
            key, value = segment
            if not isinstance(current, list):
                raise ToolExecutionError(
                    f"点分路径无法解析: {path!r}（过滤段 [{key}={value}] 作用在 "
                    f"{type(current).__name__} 上，须为列表）",
                    details={"path": path, "segment": f"{key}={value}"},
                )
            current = [el for el in current if _filter_match(el, key, value)]
            if not current:
                raise ToolExecutionError(
                    f"点分路径无法解析: {path!r}（过滤 [{key}={value}] 未命中任何元素）",
                    details={"path": path, "segment": f"{key}={value}"},
                )
        elif isinstance(current, dict):
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
