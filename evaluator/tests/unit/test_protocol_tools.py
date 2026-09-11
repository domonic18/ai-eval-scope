"""AgentProtocolToolServer 测试（arch/03 §4.0.6-b 语义工具面）。"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_eval.agent.executor import protocol_tools
from agent_eval.agent.executor.protocol_tools import AgentProtocolToolServer
from agent_eval.execution.channels.agent_protocol import AgentProtocolChannel
from agent_eval.execution.registry import OutputPathsConfig, SUTSystemConfig

WAIT_PAYLOAD = {
    "run": {"run_id": "r-1", "status": "success"},
    "values": {"output_files": ["a.html"], "content": "x" * 6000},
    "messages": [{"role": "assistant", "content": "done"}],
}


def _server(workspace_dir: Path | None = None, **sut_kwargs) -> AgentProtocolToolServer:
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
        channel,
        default_metadata={"eval_run_id": "run_x", "sut_name": "cw"},
        workspace_dir=workspace_dir,
    )


def test_eight_semantic_tools_registered() -> None:
    server = _server()
    assert server.get_tool_names() == [
        "agent_run",
        "agent_run_stream",
        "create_thread",
        "run_on_thread",
        "answer_sut_questions",
        "cancel_run",
        "get_agent_info",
        "download_sut_file",
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


def test_tool_guard_converts_channel_error_to_failed_result() -> None:
    """通道异常不炸图：转 failed 结果交给执行 Agent 决策重试/降级。"""
    from agent_eval.core.exceptions import AgentProtocolError

    class _BoomChannel:
        async def run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise AgentProtocolError("run.start 失败: 必须指定模型(modelId)")

    server = AgentProtocolToolServer(_BoomChannel())  # type: ignore[arg-type]
    result = asyncio.run(server.agent_run("hi"))
    assert result["status"] == "failed"
    assert result["error"]["type"] == "AgentProtocolError"
    assert "必须指定模型" in result["error"]["message"]


def test_agent_run_records_last_run_summary() -> None:
    """run 后记录摘要（thread/run/status/未截断 text），供 trace 回填 SUT 回答。"""
    payload = {
        "run": {"run_id": "r-9", "thread_id": "th-9", "status": "success"},
        "values": {"messages": []},
        "output": {"text": "回答" * 3000},
        "text": "回答" * 3000,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    channel = AgentProtocolChannel(
        SUTSystemConfig(
            name="cw",
            channel="agent_protocol",
            base_url="https://ap.example.com",
            output_paths=OutputPathsConfig(text_field="output.text"),
        ),
        http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    server = AgentProtocolToolServer(channel)
    asyncio.run(server.agent_run("问题"))
    assert server.last_run == {
        "status": "success",
        "thread_id": "th-9",
        "run_id": "r-9",
        "text": "回答" * 3000,  # 截断前原文
        "input": "问题",  # 机械回显守卫的判定信号源
        "pending": None,  # success 无待应答反问
    }


# ─── answer_sut_questions（askQuestion 反问应答闭环；arch/03 §4.0.6-b v4.11） ───

INTERRUPT_STATE = {
    "next": ["tools"],
    "tasks": [
        {
            "interrupts": [
                {
                    "id": "int-1",
                    "value": {
                        "type": "ask_question",
                        "questions": [
                            {
                                "question": "交付形式?",
                                "options": [
                                    {"value": "ppt", "description": "演示文稿"},
                                    {"value": "word", "description": "文档"},
                                ],
                            },
                            {
                                "question": "用途?",
                                "options": [{"value": "课堂教学", "description": ""}],
                            },
                        ],
                    },
                }
            ]
        }
    ],
    "values": {
        "messages": [
            {"type": "human", "id": "a", "content": "生成课件"},
            {
                "type": "ai",
                "id": "b",
                "content": [{"type": "text", "text": "请选择交付形式与用途"}],
                "tool_calls": [{"name": "ask_question", "id": "askq-1", "args": {}}],
            },
        ]
    },
}

RESUMED_STATE = {
    "next": [],
    "values": {
        "messages": [
            *INTERRUPT_STATE["values"]["messages"],
            {"type": "ai", "id": "c", "content": [{"type": "text", "text": "课件已生成完毕"}]},
        ]
    },
}


def _commands_server(
    states: list[dict], captured: dict | None = None, timeout: float = 5.0
) -> AgentProtocolToolServer:
    """commands 形态通道：POST 一律成功，state 按次序返回 states（末态复用）。"""
    gets = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            if captured is not None:
                captured.setdefault("posts", []).append(json.loads(request.content))
            return httpx.Response(200, json={"type": "success", "result": {"run_id": "r-1"}})
        index = min(gets["n"], len(states) - 1)
        gets["n"] += 1
        return httpx.Response(200, json=states[index])

    channel = AgentProtocolChannel(
        SUTSystemConfig(
            name="cw",
            channel="agent_protocol",
            base_url="https://ap.example.com",
            protocol_flavor="commands",
            timeout=timeout,
        ),
        http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return AgentProtocolToolServer(channel)


def test_agent_run_interrupted_records_pending() -> None:
    """interrupted 结果透出 questions，last_run 记录待应答（interrupt/tool_call id）。"""
    server = _commands_server([INTERRUPT_STATE])
    result = asyncio.run(server.agent_run("生成课件"))
    assert result["status"] == "interrupted"
    assert len(result["questions"]) == 2
    assert result["questions"][0]["interrupt_id"] == "int-1"
    assert server.last_run["pending"] == {
        "interrupt_id": "int-1",
        "tool_call_id": "askq-1",
        "questions": [
            {
                "question": "交付形式?",
                "options": [
                    {"value": "ppt", "description": "演示文稿"},
                    {"value": "word", "description": "文档"},
                ],
            },
            {"question": "用途?", "options": [{"value": "课堂教学", "description": ""}]},
        ],
    }


def test_answer_sut_questions_resumes_to_success_and_clears_pending() -> None:
    """应答 → input.respond 信封（顶层 answers 键 + 逐题 selected）→ 续跑至终态。"""
    captured: dict = {}
    server = _commands_server([INTERRUPT_STATE, INTERRUPT_STATE, RESUMED_STATE], captured)
    interrupted = asyncio.run(server.agent_run("生成课件"))
    assert interrupted["status"] == "interrupted"
    # 第 2 个 state：应答已受理、图未推进的竞态窗口（旧中断仍在），须跳过续等
    result = asyncio.run(server.answer_sut_questions(["ppt", "课堂教学"]))
    assert result["status"] == "success"
    assert result["text"] == "课件已生成完毕"
    respond = captured["posts"][1]
    assert respond["method"] == "input.respond"
    assert respond["params"]["interrupt_id"] == "int-1"
    # 前端 AskQuestionCard 同款：顶层 answers 键，不按工具调用 id 键控
    # （run 20260910_234613 实测旧键控形状被 SUT 端「答案数据无效」拒绝）
    assert respond["params"]["response"] == {
        "answers": [{"selected": ["ppt"]}, {"selected": ["课堂教学"]}]  # 字符串→单选规范化
    }
    assert server.last_run["pending"] is None  # 应答闭环后清除
    assert server.last_run["status"] == "success"


def test_answer_sut_questions_count_mismatch_lists_questions() -> None:
    server = _commands_server([INTERRUPT_STATE])
    asyncio.run(server.agent_run("生成课件"))
    result = asyncio.run(server.answer_sut_questions(["ppt"]))
    assert result["status"] == "failed"
    assert "反问共 2 题，收到 1 份答案" in result["error"]["message"]
    assert "用途?" in result["error"]["message"]  # 题目透出供 LLM 重答


def test_answer_sut_questions_without_pending_fails() -> None:
    server = _commands_server([RESUMED_STATE])
    result = asyncio.run(server.answer_sut_questions(["ppt"]))
    assert result["status"] == "failed"
    assert "没有待应答的反问" in result["error"]["message"]


def test_bounded_result_digest_drops_reasoning_keeps_answers() -> None:
    """工具结果 messages 摘要化：6 万字符 reasoning 不再把真正的回答挤出局。"""
    reasoning_state = {
        "next": [],
        "values": {
            "messages": [
                {"type": "human", "id": "a", "content": "任务"},
                {
                    "type": "ai",
                    "id": "b",
                    "content": [
                        {"type": "reasoning", "reasoning": "R" * 60000},
                        {"type": "text", "text": "最终课件链接 https://ap.example.com/f.pdf"},
                    ],
                },
            ]
        },
    }
    server = _commands_server([reasoning_state])
    result = asyncio.run(server.agent_run("任务"))
    assert result["status"] == "success"
    dumped = result["messages"]
    assert isinstance(dumped, str) and len(dumped) <= 4000 + 20  # 仍受整表截断约束
    assert "最终课件链接" in dumped  # 回答可见（此前被 reasoning 头部挤掉）
    assert "R" * 10 not in dumped


def test_bounded_result_messages_keep_tail_drop_head() -> None:
    """多轮线程摘要保尾弃头：最新 SUT 回复（含产物路径）必须留在窗口内。"""
    from agent_eval.agent.executor.protocol_tools import bounded_result

    messages = [{"role": "human", "content": f"历史消息 {i}：" + "垫" * 600} for i in range(10)]
    messages.append(
        {"role": "ai", "content": "课件已生成：/workspace/agent/一元二次方程_公式法_课件.html"}
    )
    result = bounded_result({"status": "success", "messages": messages})
    dumped = result["messages"]
    assert isinstance(dumped, str)
    assert len(dumped) <= 4000 + 80  # 省略标记占用额外长度
    assert "一元二次方程_公式法_课件.html" in dumped  # 最新回复可见
    assert "条历史消息已省略" in dumped  # 头部以占位标记省略
    assert "历史消息 0：" not in dumped  # 头部确实被弃


def test_bounded_result_short_messages_kept_intact() -> None:
    """预算内的短消息全量保留，不追加省略标记。"""
    from agent_eval.agent.executor.protocol_tools import bounded_result

    messages = [
        {"role": "human", "content": "生成课件"},
        {"role": "ai", "content": "课件已完成"},
    ]
    result = bounded_result({"messages": messages})
    dumped = result["messages"]
    assert "生成课件" in dumped and "课件已完成" in dumped
    assert "已省略" not in dumped
    assert "已截断" not in dumped


# ─── download_sut_file（产物下载落包；arch/03 §4.0.6-b v4.10） ───


def _download_server(handler, tmp_path: Path, **sut_kwargs) -> AgentProtocolToolServer:
    """构建绑定 MockTransport 下载通道的工具注册表（workspace 落 tmp_path）。"""
    defaults: dict[str, Any] = dict(
        name="cw", channel="agent_protocol", base_url="https://ap.example.com"
    )
    defaults.update(sut_kwargs)
    channel = AgentProtocolChannel(
        SUTSystemConfig(**defaults),
        http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return AgentProtocolToolServer(channel, workspace_dir=tmp_path)


def test_download_relative_path_lands_in_package_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """相对路径按 base_url 解析 + 会话凭证头挂载 + 落 {workspace}/{task_id}/output/。"""
    monkeypatch.setenv("AGENT_EVAL_SUT__CW__TOKEN", "tk-1")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200, content=b"%PDF-1.4 fake", headers={"content-type": "application/pdf"}
        )

    server = _download_server(
        handler,
        tmp_path,
        auth={"type": "static_token", "credential_ref": "CW"},
    )
    result = asyncio.run(server.download_sut_file("/files/report.pdf", "cw_math_001"))
    assert result["status"] == "success"
    assert result["file"] == "output/report.pdf"
    assert result["size_bytes"] == len(b"%PDF-1.4 fake")
    assert result["content_type"] == "application/pdf"
    assert captured["url"] == "https://ap.example.com/files/report.pdf"
    assert captured["auth"] == "Bearer tk-1"
    assert (tmp_path / "cw_math_001" / "output" / "report.pdf").read_bytes() == b"%PDF-1.4 fake"


def test_download_absolute_url_same_host_allowed(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data")

    server = _download_server(handler, tmp_path)
    result = asyncio.run(server.download_sut_file("https://ap.example.com/exports/a.xlsx", "t1"))
    assert result["status"] == "success"


def test_download_cross_host_rejected(tmp_path: Path) -> None:
    """SUT 返回异域 URL → 白名单拒绝（SSRF 防线），不发起任何请求。"""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"data")

    server = _download_server(handler, tmp_path)
    result = asyncio.run(server.download_sut_file("https://evil.example.com/x.pdf", "t1"))
    assert result["status"] == "failed"
    assert result["error"]["type"] == "ToolExecutionError"
    assert "不在白名单" in result["error"]["message"]
    assert not requests  # 越界 URL 未发出请求
    assert not (tmp_path / "t1" / "output").exists()


def test_download_artifact_hosts_allows_extra_domain(tmp_path: Path) -> None:
    """sut.artifact_hosts 是白名单的唯一合法扩展口。"""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"cdn-file")

    server = _download_server(handler, tmp_path, artifact_hosts=["files.cdn.example.com"])
    result = asyncio.run(
        server.download_sut_file("https://files.cdn.example.com/a/doc.pdf", "t1", "doc.pdf")
    )
    assert result["status"] == "success"
    assert (tmp_path / "t1" / "output" / "doc.pdf").read_bytes() == b"cdn-file"


def test_download_filename_traversal_flattened(tmp_path: Path) -> None:
    """filename 含 ../ 拍平为 basename（落盘目的地服务端持有，防路径逃逸）。"""
    served: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        served.append(request)
        return httpx.Response(200, content=b"data")

    server = _download_server(handler, tmp_path)
    result = asyncio.run(
        server.download_sut_file("https://ap.example.com/f/x.pdf", "t1", "../../escape.pdf")
    )
    assert result["status"] == "success"
    assert result["file"] == "output/escape.pdf"
    assert (tmp_path / "t1" / "output" / "escape.pdf").exists()
    assert not (tmp_path / "escape.pdf").exists()


def test_download_invalid_task_id_rejected(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data")

    server = _download_server(handler, tmp_path)
    result = asyncio.run(server.download_sut_file("/f/a.pdf", "../escape"))
    assert result["status"] == "failed"
    assert "非法 task_id" in result["error"]["message"]


def test_download_http_error_returns_failed_result(tmp_path: Path) -> None:
    """HTTP ≥400 → failed 结果（tool_guard 语义），半截文件不落包。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    server = _download_server(handler, tmp_path)
    result = asyncio.run(server.download_sut_file("/files/missing.pdf", "t1"))
    assert result["status"] == "failed"
    assert "404" in result["error"]["message"]
    assert not (tmp_path / "t1" / "output").exists() or not any(
        (tmp_path / "t1" / "output").iterdir()
    )


def test_download_size_cap_aborts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """流式累计超 DOWNLOAD_MAX_BYTES 中止：failed 结果 + 半截文件清除。"""
    monkeypatch.setattr(protocol_tools, "DOWNLOAD_MAX_BYTES", 8)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 64)

    server = _download_server(handler, tmp_path)
    result = asyncio.run(server.download_sut_file("/files/big.bin", "t1"))
    assert result["status"] == "failed"
    assert "大小上限" in result["error"]["message"]
    assert not (tmp_path / "t1" / "output" / "big.bin").exists()


def test_download_requires_workspace(tmp_path: Path) -> None:
    """workspace 未注入（ExecutionAgent 未接线）→ failed 提示，不落盘。"""
    defaults: dict[str, Any] = dict(
        name="cw", channel="agent_protocol", base_url="https://ap.example.com"
    )
    channel = AgentProtocolChannel(
        SUTSystemConfig(**defaults),
        http_client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"d"))
        ),
    )
    server = AgentProtocolToolServer(channel)  # workspace_dir 缺省 None
    result = asyncio.run(server.download_sut_file("/f/a.pdf", "t1"))
    assert result["status"] == "failed"
    assert "workspace" in result["error"]["message"]
