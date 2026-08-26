"""SUTToolServer 单元测试（arch/03 §四 v4.6）。

全部离线：HTTP 用 httpx.MockTransport，子进程用本地 echo/sleep。
"""

from __future__ import annotations

import json
import sys
import types

import httpx
import pytest

from agent_eval.agent.sut_tools import SUTToolServer
from agent_eval.core.exceptions import AgentError, CollectionError, ToolExecutionError
from agent_eval.execution.models import SUTToolsConfig


def _mock_server(handler, config: SUTToolsConfig | None = None) -> SUTToolServer:
    factory = lambda: httpx.AsyncClient(  # noqa: E731
        transport=httpx.MockTransport(handler)
    )
    if config is None:
        config = SUTToolsConfig(http_base_url="https://sut.example.com")
    return SUTToolServer(config, http_client_factory=factory)


# ─── invoke_http_sut ───


def test_invoke_http_sut_renders_template_and_maps_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/generate"
        body = json.loads(request.content)
        assert body == {"subject": "数学", "grade": "七年级"}
        return httpx.Response(200, json={"success": True, "data": {"output_files": ["a.html"]}})

    import asyncio

    server = _mock_server(handler)
    result = asyncio.run(
        server.invoke_http_sut(
            method="POST",
            url="/generate",
            body_template='{"subject": "{{ subject }}", "grade": "{{ grade }}"}',
            template_vars={"subject": "数学", "grade": "七年级"},
            response_mapping={"files": "data.output_files", "ok": "success"},
        )
    )
    assert result["status_code"] == 200
    assert result["files"] == ["a.html"]
    assert result["ok"] is True


def test_invoke_http_sut_base_url_join() -> None:
    import asyncio

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    config = SUTToolsConfig(http_base_url="https://sut.example.com/")
    server = _mock_server(handler, config)
    result = asyncio.run(server.invoke_http_sut(method="GET", url="/health"))
    assert result["status_code"] == 200


def test_invoke_http_sut_default_headers_merged() -> None:
    import asyncio

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, text="ok")

    config = SUTToolsConfig(
        http_default_headers={"X-Trace": "t1"}, http_base_url="https://sut.example.com"
    )
    server = _mock_server(handler, config)
    asyncio.run(server.invoke_http_sut(method="GET", url="/x", headers={"X-Extra": "e"}))
    assert seen.get("x-trace") == "t1"
    assert seen.get("x-extra") == "e"


def test_invoke_http_sut_mapping_on_non_json_raises() -> None:
    import asyncio

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    server = _mock_server(handler)
    with pytest.raises(ToolExecutionError):
        asyncio.run(server.invoke_http_sut(method="GET", url="/x", response_mapping={"a": "b"}))


# ─── invoke_cli_sut ───


def test_invoke_cli_sut_echo() -> None:
    import asyncio

    server = SUTToolServer()
    result = asyncio.run(server.invoke_cli_sut("echo hello-sut"))
    assert result["exit_code"] == 0
    assert "hello-sut" in result["stdout"]


def test_invoke_cli_sut_timeout_returns_minus_one() -> None:
    import asyncio

    server = SUTToolServer(SUTToolsConfig(cli_default_timeout=0.2))
    result = asyncio.run(server.invoke_cli_sut("sleep 5"))
    assert result["exit_code"] == -1
    assert "超时" in result["stderr"]


def test_invoke_cli_sut_env_vars() -> None:
    import asyncio

    server = SUTToolServer()
    result = asyncio.run(
        server.invoke_cli_sut('echo "$MY_SUT_VAR"', env_vars={"MY_SUT_VAR": "injected"})
    )
    assert "injected" in result["stdout"]


# ─── 目录 / 文件工具 ───


def _make_tree(tmp_path) -> None:
    (tmp_path / "M1").mkdir()
    (tmp_path / "M1" / "a.html").write_text("<html>1</html>", encoding="utf-8")
    (tmp_path / "M2").mkdir()
    (tmp_path / "M2" / "b.md").write_text("# b", encoding="utf-8")


def test_scan_directory(tmp_path) -> None:
    import asyncio

    _make_tree(tmp_path)
    server = SUTToolServer()
    result = asyncio.run(server.scan_directory(str(tmp_path), ["*.html"]))
    assert result["total_files"] == 1
    assert [m["name"] for m in result["modules"]] == ["M1"]


def test_scan_directory_missing_raises(tmp_path) -> None:
    import asyncio

    server = SUTToolServer()
    with pytest.raises(ToolExecutionError):
        asyncio.run(server.scan_directory(str(tmp_path / "nope")))


def test_read_file_and_list_files(tmp_path) -> None:
    import asyncio

    (tmp_path / "x.txt").write_text("内容", encoding="utf-8")
    server = SUTToolServer()
    assert asyncio.run(server.read_file(str(tmp_path / "x.txt"))) == "内容"
    assert asyncio.run(server.list_files(str(tmp_path))) == ["x.txt"]
    assert asyncio.run(server.list_files(str(tmp_path), recursive=True)) == ["x.txt"]
    with pytest.raises(ToolExecutionError):
        asyncio.run(server.read_file(str(tmp_path / "missing.txt")))


def test_collect_results_copies_files(tmp_path) -> None:
    import asyncio

    src = tmp_path / "src"
    src.mkdir()
    (src / "out.html").write_text("<html/>", encoding="utf-8")
    workspace = tmp_path / "workspace"
    server = SUTToolServer(workspace_dir=workspace)
    result = asyncio.run(server.collect_results([str(src / "out.html")], "task_1"))
    output = workspace / "task_1" / "output" / "out.html"
    assert output.exists()
    assert result["collected_files"] == [str(output)]


def test_collect_results_missing_source_raises(tmp_path) -> None:
    import asyncio

    server = SUTToolServer(workspace_dir=tmp_path)
    with pytest.raises(CollectionError):
        asyncio.run(server.collect_results([str(tmp_path / "ghost")], "t"))


def test_collect_results_unsafe_task_id_rejected(tmp_path) -> None:
    import asyncio

    from agent_eval.core.exceptions import ToolExecutionError

    server = SUTToolServer(workspace_dir=tmp_path)
    with pytest.raises(ToolExecutionError, match="非法 task_id"):
        asyncio.run(server.collect_results([str(tmp_path)], "../escape"))


def test_collect_results_unconfigured_workspace_rejected(tmp_path) -> None:
    import asyncio

    from agent_eval.core.exceptions import ToolExecutionError

    server = SUTToolServer()  # 未注入 workspace_dir
    with pytest.raises(ToolExecutionError, match="workspace_dir 未配置"):
        asyncio.run(server.collect_results([str(tmp_path / "x")], "task_1"))


def test_collect_results_mkdir_oserror_becomes_tool_error(tmp_path) -> None:
    """mkdir 的 OSError 必须转 ToolExecutionError（tool_guard 才能兜住，v4.6.3）。"""
    import asyncio

    from agent_eval.core.exceptions import ToolExecutionError

    blocker = tmp_path / "blocker"
    blocker.write_text("occupied", encoding="utf-8")  # 文件占位 → 其下 mkdir 必败
    server = SUTToolServer(workspace_dir=blocker / "ws")
    with pytest.raises(ToolExecutionError, match="输出目录创建失败"):
        asyncio.run(server.collect_results([str(tmp_path / "x")], "task_1"))


def test_write_package_layout_loadable(tmp_path) -> None:
    import asyncio

    from agent_eval.storage.package import ExecutionPackage

    server = SUTToolServer(workspace_dir=tmp_path)
    result = asyncio.run(
        server.write_package(
            task_id="task_9",
            success=True,
            output_files=["a.html"],
            trace={"request": {}, "response": {}, "started_at": "t", "finished_at": "t"},
            metrics={"tool_calls": 2},
        )
    )
    package_dir = tmp_path / "task_9"
    assert result["package_dir"] == str(package_dir)
    for name in ("manifest.json", "metadata.json", "trace.json", "metrics.json"):
        assert (package_dir / name).exists()
    package = ExecutionPackage.load(package_dir)
    assert package.manifest.task_id == "task_9"
    assert package.metrics == {"tool_calls": 2}


# ─── LangChain 工具导出 ───


def _install_fake_langchain_core(monkeypatch) -> dict[str, dict]:
    """注入伪 langchain_core.tools.StructuredTool，记录 from_function 入参。"""
    created: list[dict] = []

    class FakeStructuredTool:
        @staticmethod
        def from_function(*, coroutine=None, name=None, description=None):
            created.append({"name": name, "description": description, "coroutine": coroutine})
            return created[-1]

    fake_pkg = types.ModuleType("langchain_core")
    fake_tools = types.ModuleType("langchain_core.tools")
    fake_tools.StructuredTool = FakeStructuredTool
    fake_pkg.tools = fake_tools
    monkeypatch.setitem(sys.modules, "langchain_core", fake_pkg)
    monkeypatch.setitem(sys.modules, "langchain_core.tools", fake_tools)
    return {"created": created}


def test_to_langchain_tools_exports_seven(monkeypatch) -> None:
    import asyncio

    _install_fake_langchain_core(monkeypatch)
    server = _mock_server(lambda request: httpx.Response(200, text="ok"))
    tools = server.to_langchain_tools()
    assert [t["name"] for t in tools] == server.get_tool_names()
    assert len(tools) == 7
    # 包装器可实际调用且 JSON 文本化（走 MockTransport，零联网）
    first = tools[0]
    assert first["name"] == "invoke_http_sut"
    output = asyncio.run(first["coroutine"](method="GET", url="/health"))
    assert isinstance(output, str)
    assert "status_code" in output


def test_to_langchain_tools_without_langchain_raises(monkeypatch) -> None:
    # 真环境 langchain 已装（agent extra）→ 父模块与子模块都要置空防缓存命中
    monkeypatch.setitem(sys.modules, "langchain_core", None)  # 触发 ImportError
    monkeypatch.setitem(sys.modules, "langchain_core.tools", None)
    server = SUTToolServer()
    with pytest.raises(AgentError, match="agent-eval\\[agent\\]"):
        server.to_langchain_tools()


def test_describe_tools_lists_all() -> None:
    server = SUTToolServer()
    text = server.describe_tools()
    for name in server.get_tool_names():
        assert name in text
