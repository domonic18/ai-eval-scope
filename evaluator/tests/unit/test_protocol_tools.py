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
from agent_eval.agent.executor.ledger import EvidenceLedger, ResourceLedger
from agent_eval.agent.executor.protocol_tools import AgentProtocolToolServer
from agent_eval.execution.channels.agent_protocol import AgentProtocolChannel
from agent_eval.execution.models import InteractionPolicy
from agent_eval.execution.registry import OutputPathsConfig, SUTSystemConfig

WAIT_PAYLOAD = {
    "run": {"run_id": "r-1", "status": "success"},
    "values": {"output_files": ["a.html"], "content": "x" * 6000},
    "messages": [{"role": "assistant", "content": "done"}],
}


@pytest.fixture(autouse=True)
def _downloads_enabled_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """生产默认停用下载（SUT_FILE_DOWNLOAD_ENABLED=False，临时措施）——本模块
    单测恢复开启以验证下载行为；停用行为单独测（见 test_download_disabled_*）。"""
    monkeypatch.setattr(protocol_tools, "SUT_FILE_DOWNLOAD_ENABLED", True)


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


def test_semantic_tools_registered_in_order() -> None:
    server = _server()
    assert server.get_tool_names() == [
        "agent_run",
        "agent_run_stream",
        "create_thread",
        "run_on_thread",
        "read_thread_state",
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


# ─── read_thread_state（只读取证；2026-09-11 追问污染事故防线） ───


def test_read_thread_state_returns_bounded_evidence() -> None:
    """只读 GET state：不注入任何 run；values 摘要保尾（产物线索可见）。"""
    captured: dict = {}
    done_state = {
        "next": [],
        "values": {
            "messages": [
                {"type": "human", "content": "生成课件"},
                {
                    "type": "ai",
                    "content": [
                        {"type": "reasoning", "reasoning": "R" * 2000},
                        {"type": "text", "text": "课件已写入 output/一元二次方程教学课件.html"},
                    ],
                },
            ],
            "skillsMetadata": {"name": "pbl-learning-plan"},
        },
    }
    server = _commands_server([done_state], captured=captured)
    result = asyncio.run(server.read_thread_state("11111111-1111-1111-1111-111111111111"))
    assert "posts" not in captured  # 只读取证：未向 SUT 会话注入任何 run
    assert result["status"] == "success"
    assert result["thread_busy"] is False
    assert result["pending_questions"] == []
    assert "output/一元二次方程教学课件.html" in result["values"]  # 保尾：产物线索可见
    assert "R" * 50 not in result["values"]  # reasoning 噪声摘要丢弃


def test_read_thread_state_exposes_busy_and_pending_questions() -> None:
    """SUT 未完成或挂起反问时如实透出——取证先于催促。"""
    server = _commands_server([INTERRUPT_STATE])
    result = asyncio.run(server.read_thread_state("t-busy"))
    assert result["thread_busy"] is True
    assert result["pending_questions"][0]["question"] == "交付形式?"


def test_read_thread_state_missing_thread_reports_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "thread not found"})

    channel = AgentProtocolChannel(
        SUTSystemConfig(
            name="cw",
            channel="agent_protocol",
            base_url="https://ap.example.com",
            protocol_flavor="commands",
        ),
        http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = asyncio.run(AgentProtocolToolServer(channel).read_thread_state("t-404"))
    assert result["status"] == "not_found" and result["thread_id"] == "t-404"


def test_read_thread_state_rejects_runs_flavor() -> None:
    """runs 形态无 threads/{id}/state 端点——显式拒绝，不静默乱发请求。"""
    server = _server()  # protocol_flavor 缺省 runs
    result = asyncio.run(server.read_thread_state("t-1"))
    assert result["status"] == "failed"
    assert "仅 commands 形态" in result["error"]["message"]


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


def test_bounded_result_values_payload_keeps_tail_symmetrically() -> None:
    """values 复合载荷（外壳 + messages）保尾弃头与消息列表同病同治（plan/07 P3）。

    整表 dumps 头部截断会把 values.messages 里最新回复挤出窗口——长历史 +
    短最新回复时最易触发。
    """
    from agent_eval.agent.executor.protocol_tools import bounded_result

    messages = [{"role": "human", "content": f"历史 {i}：" + "垫" * 700} for i in range(12)]
    messages.append({"role": "ai", "content": "完成，产物在 /w/课件.html"})
    values = {"next": [], "total_messages": 13, "messages": messages}
    result = bounded_result({"values": values})
    dumped = result["values"]
    assert isinstance(dumped, str)
    assert len(dumped) <= 4000 + 120
    assert "/w/课件.html" in dumped  # values.messages 最新回复可见
    assert "条历史消息已省略" in dumped
    assert "历史 0：" not in dumped  # 头部确实被弃
    assert "total_messages" in dumped  # 外壳字段保留


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


def test_download_spa_shell_rejected_and_not_landed(tmp_path: Path) -> None:
    """网关 SPA fallback 壳不是产物：判定下载失败且不落包（2026-09-11 事故）。"""
    spa_shell = (
        b"<!doctype html><html><head><title>Sasan Agent</title>"
        b'<script type="module" crossorigin src="/assets/index-sTe-VZ9J.js"></script>'
        b'</head><body><div id="root"></div></body></html>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=spa_shell, headers={"content-type": "text/html"})

    server = _download_server(handler, tmp_path)
    result = asyncio.run(server.download_sut_file("/files/courseware.html", "t1"))
    assert result["status"] == "failed"
    assert "前端壳" in result["error"]["message"]
    assert list((tmp_path / "t1" / "output").glob("*")) == []  # 壳文件不留包


def test_download_html_with_root_div_but_no_bundle_passes(tmp_path: Path) -> None:
    """指纹须双命中：含 root 挂载点但无 /assets/index- 脚本的正常 HTML 不误伤。"""
    legit = b'<!doctype html><html><body><div id="root"><h1>slides</h1></div></body></html>'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=legit, headers={"content-type": "text/html"})

    server = _download_server(handler, tmp_path)
    result = asyncio.run(server.download_sut_file("/files/courseware.html", "t1"))
    assert result["status"] == "success"
    assert result["size_bytes"] == len(legit)


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


# ─── 下载临时停用（SUT_FILE_DOWNLOAD_ENABLED=False，2026-09-11 用户指示） ───


def test_download_disabled_returns_guidance_without_budget_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """停用期间入口即拒：不触网、不耗下载预算，指引写包收尾；证据流记 disabled。"""
    monkeypatch.setattr(protocol_tools, "SUT_FILE_DOWNLOAD_ENABLED", False)  # 盖过 autouse
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"should-not-be-fetched")

    server = _download_server(handler, tmp_path)
    ledger = ResourceLedger(InteractionPolicy())
    evidence = EvidenceLedger()
    ledger.evidence = evidence
    server.ledger = ledger

    result = asyncio.run(server.download_sut_file("/files/课件.html", "t1"))
    assert result["status"] == "failed"
    assert result["error"]["type"] == "ToolDisabled"
    assert "临时停用" in result["error"]["message"]
    assert "write_package" in result["error"]["message"]  # 收尾指引随载荷透出
    assert not requests  # 未发起任何网络请求
    assert ledger.counters["download"] == 0  # 停用尝试不消耗下载额度
    assert evidence.events[-1]["outcome"] == "disabled"  # 证据流留痕


# ─── 超时重试机械守卫（TimeoutBudgetExhausted，v4.17） ───


def _timeout_commands_server(monkeypatch: pytest.MonkeyPatch) -> AgentProtocolToolServer:
    """commands 通道：线程空闲但 baseline 后只有 human 消息——终态判定永不通过，
    每次 SUT 执行调用必然超时（留证 TimeoutBudgetExhausted 守卫的触发链）。"""
    import agent_eval.execution.channels.thread_commands as thread_commands

    monkeypatch.setattr(thread_commands, "COMMANDS_POLL_INTERVAL_S", 0.01)
    state = {"next": [], "values": {"messages": [{"type": "human", "content": "hi"}]}}
    return _commands_server([state], timeout=0.05)


def test_timeout_guard_allows_one_retry_then_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """首次超时按 failed 透出原错误（允许重试 1 次）；再次超时起机械拒绝并附证据。"""
    server = _timeout_commands_server(monkeypatch)

    first = asyncio.run(server.agent_run("生成课件"))
    assert first["status"] == "failed"
    assert first["error"]["type"] == "AgentProtocolTimeoutError"

    second = asyncio.run(server.agent_run("生成课件"))
    assert second["status"] == "failed"
    assert second["error"]["type"] == "TimeoutBudgetExhausted"
    assert any("run 超时" in ev for ev in second["timeout_evidence"])

    # 换执行工具同样在入口被拒——预算耗尽后不再有任何 SUT 执行调用
    third = asyncio.run(server.run_on_thread("th-1", "继续", rationale="首次超时后取证续跑"))
    assert third["error"]["type"] == "TimeoutBudgetExhausted"
    stream = asyncio.run(server.agent_run_stream("生成课件"))
    assert stream["error"]["type"] == "TimeoutBudgetExhausted"


def test_timeout_guard_reset_at_task_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """reset_task_state（任务起点统一清账）解除封锁：下一任务重新计数，不误伤。"""
    server = _timeout_commands_server(monkeypatch)
    asyncio.run(server.agent_run("生成课件"))
    exhausted = asyncio.run(server.agent_run("生成课件"))
    assert exhausted["error"]["type"] == "TimeoutBudgetExhausted"

    server.reset_task_state()
    retried = asyncio.run(server.agent_run("生成课件"))
    assert retried["error"]["type"] == "AgentProtocolTimeoutError"  # 新任务的首超时


def test_read_thread_state_not_blocked_by_timeout_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只读取证/产物下载不占超时预算——「先取证后催促」纪律的工具面基础。"""
    server = _timeout_commands_server(monkeypatch)
    server._timeout_errors.extend(["run 超时：a", "run 超时：b"])  # 预算耗尽态
    result = asyncio.run(server.read_thread_state("th-1"))
    assert result["status"] == "success"
    assert result["thread_busy"] is False
    assert result["pending_questions"] == []


# ─── 交互预算闸门（BudgetExhausted，arch/16 §4.3 Phase 1 机械壳） ───


def test_dispatch_exhausted_blocks_agent_run_without_network() -> None:
    """dispatch 额度用尽后 agent_run 入口即拒——不触网（POST 计数不增）。"""
    captured: dict = {}
    server = _commands_server([RESUMED_STATE], captured=captured)
    server.ledger = ResourceLedger(InteractionPolicy(dispatch=1))

    first = asyncio.run(server.agent_run("生成课件"))
    assert first["status"] == "success"
    posts_after_first = len(captured["posts"])

    second = asyncio.run(server.agent_run("生成课件"))
    assert second["status"] == "failed"
    assert second["error"]["type"] == "BudgetExhausted"
    assert second["error"]["budget"] == "dispatch"
    assert "read_thread_state" in second["error"]["guidance"]
    assert any(item["budget"] == "dispatch" for item in second["ledger_digest"])
    assert len(captured["posts"]) == posts_after_first  # 拒绝在触网之前


def test_nudge_backoff_refusal_at_tool_entry() -> None:
    """run_on_thread 入口背压：backoff 窗口内拒绝且不消耗催促额度。"""
    # 三段状态：run_on_thread 先 GET prior 定 baseline=3（第二段），轮询 GET 到
    # 第三段才出现 index>=3 的新 ai 消息——终态判定与 commands 形态一致
    nudged = {
        "next": [],
        "values": {
            "messages": [
                *RESUMED_STATE["values"]["messages"],
                {"type": "human", "content": "继续"},
                {"type": "ai", "content": [{"type": "text", "text": "已继续处理"}]},
            ]
        },
    }
    server = _commands_server([RESUMED_STATE, RESUMED_STATE, nudged])
    ledger = ResourceLedger(InteractionPolicy(dispatch=1, nudges=5, nudge_backoff_s=30))
    server.ledger = ledger

    asyncio.run(server.agent_run("生成课件"))
    first = asyncio.run(
        server.run_on_thread("th-1", "继续", rationale="简报显示仍在产出，索取进度")
    )
    assert first["status"] == "success"

    second = asyncio.run(
        server.run_on_thread("th-1", "继续", rationale="仍无产物，再等一个节奏窗口")
    )
    assert second["status"] == "failed"
    assert second["error"]["type"] == "BudgetExhausted"
    assert second["error"]["budget"] == "nudge_backoff"
    assert ledger.counters["nudge"] == 1  # 节奏窗口不烧额度


def test_execution_exhaustion_leaves_evidence_paths_open(tmp_path: Path) -> None:
    """执行额度耗尽后取证与下载仍放行——闸门不挡「先取证后收尾」退出路径。"""
    server = _commands_server([RESUMED_STATE])
    ledger = ResourceLedger(InteractionPolicy(dispatch=1, nudges=0))
    server.ledger = ledger
    asyncio.run(server.agent_run("生成课件"))

    blocked = asyncio.run(server.run_on_thread("th-1", "继续", rationale="长空闲无产物，索取交付"))
    assert blocked["status"] == "failed"
    assert blocked["error"]["budget"] == "nudges"

    state = asyncio.run(server.read_thread_state("th-1"))
    assert state["status"] == "success"
    assert ledger.remaining("state_poll") == f"{ledger.policy.state_polls - 1}/60"

    downloader = _download_server(
        lambda request: httpx.Response(200, content=b"<html>ok</html>"), tmp_path
    )
    downloader.ledger = ledger
    result = asyncio.run(downloader.download_sut_file("/f/a.html", "t1"))
    assert result["status"] == "success"
    assert result["file"] == "output/a.html"


def test_gate_refusals_and_outcomes_recorded_in_evidence_ledger() -> None:
    """放行 outcome 与拒绝事件都进证据流（ledger.jsonl 的数据源）。"""
    server = _commands_server([RESUMED_STATE])
    evidence = EvidenceLedger()
    server.ledger = ResourceLedger(InteractionPolicy(dispatch=1), evidence=evidence)

    asyncio.run(server.agent_run("生成课件"))
    asyncio.run(server.agent_run("生成课件"))  # 被拒

    kinds = [e["kind"] for e in evidence.events]
    assert kinds[0] == "sut_call"
    assert evidence.events[0]["outcome"] == "ok"
    assert evidence.events[0]["action"] == "dispatch"
    assert "duration_s" in evidence.events[0]
    assert kinds[-1] == "gate_refusal"
    assert evidence.events[-1]["action"] == "dispatch"


def test_ungated_tools_do_not_consume_budget() -> None:
    """取证/收尾类工具不设闸——预算耗尽后仍可用，且不烧额度。"""
    server = _commands_server([RESUMED_STATE])
    ledger = ResourceLedger(InteractionPolicy(sut_calls_total=1, dispatch=1, nudges=0))
    server.ledger = ledger
    asyncio.run(server.agent_run("生成课件"))  # 烧尽合计面

    for call in (lambda: server.get_agent_info(), lambda: server.cancel_run("r-1")):
        result = asyncio.run(call())
        assert result.get("error", {}).get("type") != "BudgetExhausted"
    assert ledger.counters["sut_call"] == 1  # 只有 dispatch 那一次


# ─── 完成仲裁与决策简报（arch/16 §5 决策回路，Phase 2） ───


def test_run_on_thread_without_rationale_refused_without_quota_or_network() -> None:
    """缺 rationale 的催促在入口被拒：不触网、不耗催促额度、gate_refusal 留证。"""
    captured: dict = {}
    server = _commands_server([RESUMED_STATE], captured=captured)
    evidence = EvidenceLedger()
    ledger = ResourceLedger(InteractionPolicy(), evidence=evidence)
    server.ledger = ledger

    refused = asyncio.run(server.run_on_thread("th-1", "继续"))
    assert refused["status"] == "failed"
    assert refused["error"]["type"] == "NudgeRationaleRequired"
    assert "read_thread_state" in refused["error"]["message"]
    assert ledger.counters["nudge"] == 0  # 资格闸门不耗额度
    assert captured.get("posts") is None  # 拒绝在触网之前
    refusal_events = [e for e in evidence.events if e["kind"] == "gate_refusal"]
    assert refusal_events and refusal_events[0]["action"] == "nudge"


def test_run_on_thread_rationale_lands_decision_event() -> None:
    """带 rationale 的催促落 decision 台账（verdict 缺省 stalled）——可复盘。"""
    # 三段状态：agent_run 定 baseline，run_on_thread 轮询到新增 ai 回复才算终态
    nudged = {
        "next": [],
        "values": {
            "messages": [
                *RESUMED_STATE["values"]["messages"],
                {"type": "human", "content": "继续"},
                {"type": "ai", "content": [{"type": "text", "text": "已继续处理"}]},
            ]
        },
    }
    server = _commands_server([RESUMED_STATE, RESUMED_STATE, nudged])
    evidence = EvidenceLedger()
    server.ledger = ResourceLedger(InteractionPolicy(), evidence=evidence)
    asyncio.run(server.agent_run("生成课件"))  # 先建立线程上下文

    result = asyncio.run(server.run_on_thread("th-1", "继续", rationale="长空闲无产物，索取交付"))
    assert result["status"] == "success"
    decisions = [e for e in evidence.events if e["kind"] == "decision"]
    assert len(decisions) == 1
    assert decisions[0]["action"] == "nudge"
    assert decisions[0]["verdict"] == "stalled"
    assert decisions[0]["rationale"] == "长空闲无产物，索取交付"


def test_read_thread_state_verdict_rationale_lands_decision_event() -> None:
    """取证时携带 verdict/rationale → decision 台账（仲裁结论留痕）。"""
    server = _commands_server([RESUMED_STATE])
    evidence = EvidenceLedger()
    server.ledger = ResourceLedger(InteractionPolicy(), evidence=evidence)

    result = asyncio.run(
        server.read_thread_state(
            "th-1", verdict="progressing", rationale="values 仍在增长，等待不打扰"
        )
    )
    assert result["status"] == "success"
    decisions = [e for e in evidence.events if e["kind"] == "decision"]
    assert decisions[0]["action"] == "state_poll"
    assert decisions[0]["verdict"] == "progressing"


def test_read_thread_state_rejects_illegal_verdict() -> None:
    """verdict 非受控枚举即拒——受控枚举是契约不是装饰。"""
    server = _commands_server([RESUMED_STATE])
    result = asyncio.run(server.read_thread_state("th-1", verdict="done"))
    assert result["status"] == "failed"
    assert result["error"]["type"] == "ToolExecutionError"
    assert "complete" in result["error"]["message"]


def test_briefing_injected_and_refreshed_on_action_tools() -> None:
    """挂点 b：动作工具结果附简报且随账本刷新；取证后 sut_state 有观察值。"""
    path_state = {
        "next": [],
        "values": {
            "messages": [
                {
                    "type": "ai",
                    "content": [{"type": "text", "text": "已写入 output/课件_final.html"}],
                }
            ]
        },
    }
    server = _commands_server([RESUMED_STATE, path_state])
    server.ledger = ResourceLedger(InteractionPolicy())

    first = asyncio.run(server.agent_run("生成课件"))
    assert first["briefing"]["objective"] == "生成课件"
    assert first["briefing"]["resources"]["sut_calls"] == "7/8"  # 消耗一次后刷新
    assert first["briefing"]["last_result_digest"]

    state = asyncio.run(server.read_thread_state("th-1"))
    sut_state = state["briefing"]["sut_state"]
    assert sut_state["thread_busy"] is False  # 来自 observe 的真实采证
    assert sut_state["artifact_candidates"] == ["output/课件_final.html"]


def test_briefing_absent_without_ledger_and_on_ungated_tools() -> None:
    """直连使用（无账本）恒等返回；取证收尾类工具不注入简报。"""
    server = _commands_server([RESUMED_STATE])
    result = asyncio.run(server.agent_run("生成课件"))
    assert "briefing" not in result

    gated_server = _commands_server([RESUMED_STATE])
    gated_server.ledger = ResourceLedger(InteractionPolicy())
    info = asyncio.run(gated_server.get_agent_info())
    assert "briefing" not in info


def test_gate_refusal_carries_briefing() -> None:
    """拒绝载荷同享简报——拒的是动作，简报告诉决策体接下来去哪。"""
    captured: dict = {}
    server = _commands_server([RESUMED_STATE], captured=captured)
    server.ledger = ResourceLedger(InteractionPolicy(dispatch=1))
    asyncio.run(server.agent_run("生成课件"))

    refused = asyncio.run(server.agent_run("生成课件"))
    assert refused["error"]["type"] == "BudgetExhausted"
    assert refused["briefing"]["resources"]["sut_calls"] == "7/8"  # 合计面已耗 1


def test_state_tracker_resets_across_tasks_and_feeds_idle() -> None:
    """观察时间线随任务换新（reset_task_state）；连续同值观察产生 idle 计时。"""
    import time as _time

    server = _commands_server([RESUMED_STATE, RESUMED_STATE])
    server.ledger = ResourceLedger(InteractionPolicy())
    asyncio.run(server.read_thread_state("th-1"))
    _time.sleep(0.01)
    second = asyncio.run(server.read_thread_state("th-1"))
    assert server._tracker.idle_for_s() is not None  # 两次同值观察界定「持续」
    assert second["briefing"]["sut_state"]["idle_for_s"] is not None  # 简报可见（取整呈现）

    server.reset_task_state()
    assert server._tracker.last_busy is None  # 新任务无观察，不串上一任务状态
