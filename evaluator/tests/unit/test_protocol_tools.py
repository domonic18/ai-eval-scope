"""AgentProtocolToolServer 测试（arch/03 §4.0.6-b 语义工具面）。"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from typing import Any

import httpx

from agent_eval.agent.protocol_tools import AgentProtocolToolServer
from agent_eval.execution.channels.agent_protocol import AgentProtocolChannel
from agent_eval.execution.registry import OutputPathsConfig, SUTSystemConfig

WAIT_PAYLOAD = {
    "run": {"run_id": "r-1", "status": "success"},
    "values": {"output_files": ["a.html"], "content": "x" * 6000},
    "messages": [{"role": "assistant", "content": "done"}],
}


def _server(**sut_kwargs) -> AgentProtocolToolServer:
    defaults: dict[str, Any] = dict(
        name="cw",
        channel="agent_protocol",
        base_url="https://ap.example.com",
        output_paths=OutputPathsConfig(
            files_field="values.output_files", text_field="values.content"
        ),
    )
    defaults.update(sut_kwargs)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=WAIT_PAYLOAD)

    channel = AgentProtocolChannel(
        SUTSystemConfig(**defaults),
        http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return AgentProtocolToolServer(
        channel, default_metadata={"eval_run_id": "run_x", "sut_name": "cw"}
    )


def test_six_semantic_tools_registered() -> None:
    server = _server()
    assert server.get_tool_names() == [
        "agent_run",
        "agent_run_stream",
        "create_thread",
        "run_on_thread",
        "cancel_run",
        "get_agent_info",
    ]
    assert "agent_run" in server.describe_tools()


def test_agent_run_returns_bounded_result() -> None:
    server = _server()
    result = asyncio.run(server.agent_run({"subject": "数学"}, metadata={"task_id": "t1"}))
    assert result["status"] == "success"
    assert result["output"]["files"] == ["a.html"]
    # 大体量字段被截断（6000 字符 content → JSON 文本截断）
    assert len(result["values"]) < 6000
    assert "已截断" in result["values"]


def test_metadata_merged_into_run_body() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=WAIT_PAYLOAD)

    channel = AgentProtocolChannel(
        SUTSystemConfig(name="cw", channel="agent_protocol", base_url="https://ap.example.com"),
        http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    server = AgentProtocolToolServer(
        channel, default_metadata={"eval_run_id": "run_x", "sut_name": "cw"}
    )
    asyncio.run(server.agent_run("input", metadata={"task_id": "t-9"}))
    # §4.0.6-e：metadata 携带 eval_run_id/task_id/sut_name 供被测系统侧审计
    assert captured["metadata"] == {"eval_run_id": "run_x", "sut_name": "cw", "task_id": "t-9"}


def test_to_langchain_tools_export(monkeypatch) -> None:
    created: list[dict] = []

    class FakeStructuredTool:
        @staticmethod
        def from_function(*, coroutine=None, name=None, description=None):
            created.append({"name": name, "coroutine": coroutine})
            return created[-1]

    fake_pkg = types.ModuleType("langchain_core")
    fake_tools = types.ModuleType("langchain_core.tools")
    fake_tools.StructuredTool = FakeStructuredTool
    fake_pkg.tools = fake_tools
    monkeypatch.setitem(sys.modules, "langchain_core", fake_pkg)
    monkeypatch.setitem(sys.modules, "langchain_core.tools", fake_tools)

    server = _server()
    tools = server.to_langchain_tools()
    assert [t["name"] for t in tools] == server.get_tool_names()
    # 包装器可调用且 JSON 文本化
    output = asyncio.run(created[0]["coroutine"](input={"q": 1}))
    assert isinstance(output, str)
    assert json.loads(output)["status"] == "success"
