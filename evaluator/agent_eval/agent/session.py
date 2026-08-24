"""Agent 会话记录与状态外部化（arch/03 §3.5 v4.6）。

AgentSession 从 DeepAgents/LangGraph 消息序列构建会话统计；
WorkspaceCheckpointer 实现 LangGraph checkpointer 语义（鸭子类型），
将会话状态 pickle 落盘 workspace/agent_sessions/——推理-执行-状态分离，
崩溃可恢复/可重放/可审计。PoC 说明（v4.6.3）：单进程文件实现，
**未接入 ExecutionAgent 图装配**——langgraph 高频触达 saver，全量读写
实现会拖垮执行（实测 CPU 空转）；且 pending_writes 尚未按 checkpoint_id
索引，恢复语义不完整。待 B4 实现增量真 saver 后接回。
"""

from __future__ import annotations

import hashlib
import pickle
import re
from collections import namedtuple
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# LangGraph CheckpointTuple 兼容形态（NamedTuple：可索引 + 属性访问）
CheckpointTuple = namedtuple(
    "CheckpointTuple", ["config", "checkpoint", "parent_config", "metadata", "pending_writes"]
)

# langgraph 侧 CompiledStateGraph 对 checkpointer 做 isinstance 校验（鸭子类型不被
# 接受）；[agent] extra 环境下挂真基类过校验，纯 mock 测试环境退化为 object
try:
    from langgraph.checkpoint.base import (
        BaseCheckpointSaver as _LGBaseCheckpointSaver,
    )
except ImportError:  # pragma: no cover — langgraph 属 [agent] extra，可选
    _LGBaseCheckpointSaver = object  # type: ignore[assignment,misc]

_THREAD_SAFE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass
class AgentSession:
    """Agent 会话记录，保存完整的交互历史（arch/03 §3.5）。"""

    messages: list[Any] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    tool_call_count: int = 0
    turns_used: int = 0
    started_at: str = ""
    finished_at: str = ""

    @classmethod
    def from_messages(cls, messages: list[Any]) -> AgentSession:
        """从 LangGraph 结果消息序列（鸭子类型）构建会话统计。

        Args:
            messages: ainvoke 返回的 messages 列表（HumanMessage/AIMessage/ToolMessage 或 dict）。
        """
        session = cls(messages=[_serialize_message(m) for m in messages])
        for message in messages:
            usage = getattr(message, "usage_metadata", None)
            if isinstance(usage, dict):
                session.total_input_tokens += int(usage.get("input_tokens", 0) or 0)
                session.total_output_tokens += int(usage.get("output_tokens", 0) or 0)
            session.tool_call_count += len(getattr(message, "tool_calls", None) or [])
            if _message_type(message) == "ai":
                session.turns_used += 1
        return session


def _serialize_message(message: Any) -> Any:
    """把 LangChain 消息序列化为可记录的 dict（pydantic → dict → repr 兜底）。"""
    if hasattr(message, "model_dump"):
        return message.model_dump()
    if isinstance(message, dict):
        return message
    return {"type": _message_type(message), "repr": str(message)[:2000]}


def _message_type(message: Any) -> str:
    """提取消息类型标识（langchain .type 属性 / 类名兜底，统一小写）。"""
    mtype = getattr(message, "type", None)
    if isinstance(mtype, str):
        return mtype.lower()
    return type(message).__name__.lower()


class WorkspaceCheckpointer(_LGBaseCheckpointSaver):  # type: ignore[misc]
    """LangGraph checkpointer：会话状态落盘 workspace/agent_sessions/。

    实现协议方法 put/put_writes/get_tuple/list（含 async 变体），按 thread_id
    一文件存储，pickle 序列化（内部工作区状态，崩溃恢复用，非跨系统交换格式）。
    继承 BaseCheckpointSaver 仅为通过 langgraph 的 isinstance 校验（PoC，v4.6）。
    """

    def __init__(self, workspace_dir: Path | str) -> None:
        if _LGBaseCheckpointSaver is not object:
            super().__init__()
        self.sessions_dir = Path(workspace_dir) / "agent_sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    # ─── 路径与存取 ───

    def _thread_id(self, config: dict[str, Any]) -> str:
        configurable = (config or {}).get("configurable", {})
        return str(configurable.get("thread_id", "default"))

    def _path(self, thread_id: str) -> Path:
        if not _THREAD_SAFE.match(thread_id):
            thread_id = hashlib.sha256(thread_id.encode()).hexdigest()[:16]
        return self.sessions_dir / f"{thread_id}.session.pkl"

    def _load(self, thread_id: str) -> dict[str, Any]:
        path = self._path(thread_id)
        if not path.exists():
            return {"checkpoints": [], "writes": {}}
        with path.open("rb") as f:
            data: dict[str, Any] = pickle.load(f)  # 仅读写自身 workspace 产物
            return data

    def _save(self, thread_id: str, data: dict[str, Any]) -> None:
        with self._path(thread_id).open("wb") as f:
            pickle.dump(data, f)

    # ─── 同步协议 ───

    def put(  # type: ignore[override]
        self,
        config: dict[str, Any],
        checkpoint: dict[str, Any],
        metadata: dict[str, Any],
        new_versions: Any = None,
    ) -> None:
        """保存一个 checkpoint（追加到该 thread 的历史）。"""
        thread_id = self._thread_id(config)
        data = self._load(thread_id)
        checkpoint_id = (checkpoint or {}).get("id")
        record_config = {
            "configurable": {
                "thread_id": thread_id,
                **({"checkpoint_id": checkpoint_id} if checkpoint_id else {}),
            }
        }
        data["checkpoints"].append((record_config, checkpoint, metadata))
        self._save(thread_id, data)

    def put_writes(  # type: ignore[override]
        self,
        config: dict[str, Any],
        writes: list[tuple[str, Any]],
        task_id: str,
    ) -> None:
        """保存中间写入（pending writes），按 (thread_id, task_id) 索引。"""
        thread_id = self._thread_id(config)
        data = self._load(thread_id)
        data["writes"][task_id] = writes
        self._save(thread_id, data)

    def get_tuple(  # type: ignore[override]
        self, config: dict[str, Any]
    ) -> CheckpointTuple | None:
        """读取 checkpoint（checkpoint_id 指定则取该版本，否则取最新）。"""
        thread_id = self._thread_id(config)
        data = self._load(thread_id)
        if not data["checkpoints"]:
            return None
        wanted = (config or {}).get("configurable", {}).get("checkpoint_id")
        records = data["checkpoints"]
        record = None
        if wanted:
            for cfg, checkpoint, _meta in reversed(records):
                if cfg["configurable"].get("checkpoint_id") == wanted:
                    record = (cfg, checkpoint, _meta)
                    break
        else:
            cfg, checkpoint, meta = records[-1]
            record = (cfg, checkpoint, meta)
        if record is None:
            return None
        record_config, checkpoint, metadata = record
        parent_config = records[-2][0] if len(records) >= 2 else None
        return CheckpointTuple(
            config=record_config,
            checkpoint=checkpoint,
            parent_config=parent_config,
            metadata=metadata,
            pending_writes=data["writes"].get("__latest__", []),
        )

    def list(  # type: ignore[override]
        self,
        config: dict[str, Any],
        *,
        before: Any = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> Iterator[CheckpointTuple]:
        """按新→旧迭代该 thread 的 checkpoints。"""
        thread_id = self._thread_id(config)
        records = self._load(thread_id)["checkpoints"]
        count = 0
        for cfg, checkpoint, metadata in reversed(records):
            if limit is not None and count >= limit:
                break
            count += 1
            yield CheckpointTuple(
                config=cfg,
                checkpoint=checkpoint,
                parent_config=None,
                metadata=metadata,
                pending_writes=[],
            )

    # ─── 异步协议（委托同步实现） ───

    async def aput(  # type: ignore[override]
        self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any = None
    ) -> None:
        self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(  # type: ignore[override]
        self, config: Any, writes: Any, task_id: str
    ) -> None:
        self.put_writes(config, writes, task_id)

    async def aget_tuple(  # type: ignore[override]
        self, config: Any
    ) -> CheckpointTuple | None:
        return self.get_tuple(config)

    async def alist(  # type: ignore[override,misc]
        self, config: Any, **kwargs: Any
    ) -> Iterator[CheckpointTuple]:
        for item in self.list(config, **kwargs):
            yield item
