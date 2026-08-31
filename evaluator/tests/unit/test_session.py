"""session 单元测试（AgentSession / WorkspaceCheckpointer，arch/03 §3.5）。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from agent_eval.agent.session import AgentSession, WorkspaceCheckpointer


def _messages() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(type="human"),
        SimpleNamespace(
            type="ai",
            tool_calls=[{"name": "invoke_http_sut"}],
            usage_metadata={"input_tokens": 100, "output_tokens": 20},
        ),
        SimpleNamespace(type="tool"),
        SimpleNamespace(
            type="ai", tool_calls=[], usage_metadata={"input_tokens": 200, "output_tokens": 30}
        ),
    ]


def test_agent_session_from_messages_stats() -> None:
    session = AgentSession.from_messages(_messages())
    assert session.total_input_tokens == 300
    assert session.total_output_tokens == 50
    assert session.tool_call_count == 1
    assert session.turns_used == 2
    assert len(session.messages) == 4


def test_agent_session_serializes_messages() -> None:
    session = AgentSession.from_messages(_messages())
    # SimpleNamespace 无 model_dump/dict → repr 兜底，带 type 标识
    assert session.messages[0] == {"type": "human", "repr": "namespace(type='human')"}
    # dict 消息原样保留
    session2 = AgentSession.from_messages([{"type": "ai", "content": "hi"}])
    assert session2.messages[0] == {"type": "ai", "content": "hi"}


def test_checkpointer_put_get_roundtrip(tmp_path) -> None:
    saver = WorkspaceCheckpointer(tmp_path)
    config = {"configurable": {"thread_id": "task_1"}}
    saver.put(config, {"id": "ck1", "state": 1}, {"step": 1})
    saver.put(config, {"id": "ck2", "state": 2}, {"step": 2})

    got = saver.get_tuple(config)
    assert got is not None
    assert got.checkpoint == {"id": "ck2", "state": 2}
    assert got.metadata == {"step": 2}
    assert got.parent_config is not None
    assert got.config["configurable"]["checkpoint_id"] == "ck2"


def test_checkpointer_specific_checkpoint_id(tmp_path) -> None:
    saver = WorkspaceCheckpointer(tmp_path)
    config = {"configurable": {"thread_id": "t"}}
    saver.put(config, {"id": "a"}, {})
    saver.put(config, {"id": "b"}, {})
    got = saver.get_tuple({"configurable": {"thread_id": "t", "checkpoint_id": "a"}})
    assert got is not None
    assert got.checkpoint == {"id": "a"}


def test_checkpointer_missing_thread_returns_none(tmp_path) -> None:
    saver = WorkspaceCheckpointer(tmp_path)
    assert saver.get_tuple({"configurable": {"thread_id": "ghost"}}) is None


def test_checkpointer_list_newest_first(tmp_path) -> None:
    saver = WorkspaceCheckpointer(tmp_path)
    config = {"configurable": {"thread_id": "t"}}
    saver.put(config, {"id": "1"}, {"n": 1})
    saver.put(config, {"id": "2"}, {"n": 2})
    saver.put(config, {"id": "3"}, {"n": 3})
    items = list(saver.list(config))
    assert [t.checkpoint["id"] for t in items] == ["3", "2", "1"]
    limited = list(saver.list(config, limit=2))
    assert len(limited) == 2


def test_checkpointer_put_writes_and_async(tmp_path) -> None:
    saver = WorkspaceCheckpointer(tmp_path)
    config = {"configurable": {"thread_id": "t"}}

    async def _run() -> None:
        await saver.aput(config, {"id": "x"}, {"step": 0})
        await saver.aput_writes(config, [("notes", "中间写入")], "task-A")
        got = await saver.aget_tuple(config)
        assert got is not None
        assert got.checkpoint == {"id": "x"}

    asyncio.run(_run())
    data_written = (tmp_path / "agent_sessions" / "t.session.pkl").exists()
    assert data_written


def test_checkpointer_unsafe_thread_id_sanitized(tmp_path) -> None:
    saver = WorkspaceCheckpointer(tmp_path)
    config = {"configurable": {"thread_id": "../../etc/passwd"}}
    saver.put(config, {"id": "1"}, {})
    files = list((tmp_path / "agent_sessions").iterdir())
    assert len(files) == 1
    assert ".." not in files[0].name
