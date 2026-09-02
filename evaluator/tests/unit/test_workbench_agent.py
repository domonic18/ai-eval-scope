"""WorkbenchAgent / PackageToolServer 单测 — 沙盒红线、门禁回改、落盘原子性（arch/15 §六）。

LLM 链路以回放状态机 mock（monkeypatch ``WorkbenchAgent._invoke``），
不依赖 deepagents / LLM / 网络；工具面直调异步方法。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import typer

from agent_eval.agent.workbench_agent import (
    TurnResult,
    WorkbenchAgent,
    WorkbenchAgentConfig,
    _resume_messages,
)
from agent_eval.agent.workbench_tools import PackageToolServer
from agent_eval.core.exceptions import AgentError

MANIFEST = "package:\n  id: demo\n  scenario: demo\n  version: 0.1.0\n"
RULES = "rules:\n  - id: r1\n    evaluator: llm_judge\n"


def _seed_valid_package(root: Path) -> None:
    """磁盘上放一个合法最小包（edit 会话 / update_manifest 场景）。"""
    for sub in ("rules", "prompts", "datasets"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "agent_eval.yaml").write_text(MANIFEST, encoding="utf-8")
    (root / "rules" / "quality.yaml").write_text(RULES, encoding="utf-8")
    (root / "prompts" / "judge.yaml").write_text("prompts: []\n", encoding="utf-8")
    (root / "datasets" / "ref.yaml").write_text("data: []\n", encoding="utf-8")


def _ai(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="ai", content=text)


def _replay(effects: list[Any]) -> tuple[Any, list[list[Any]]]:
    """伪造 ``_invoke``：逐次消费 effects（async fn(server) -> str 回复），记录每次入参消息。

    on_event 给定时发一条 token 事件（模拟流式），供事件链路断言。
    """

    calls: list[list[Any]] = []
    remaining = list(effects)

    async def fake_invoke(
        self: WorkbenchAgent, messages: list[Any], *, on_event: Any = None
    ) -> dict[str, Any]:
        calls.append(list(messages))
        reply = await remaining.pop(0)(self.server)
        if callable(on_event):
            on_event({"type": "token", "text": reply})
        return {"messages": [*messages, _ai(reply)]}

    return fake_invoke, calls


async def _write_valid(server: PackageToolServer) -> str:
    await server.write_file("agent_eval.yaml", MANIFEST)
    await server.write_file("rules/quality.yaml", RULES)
    await server.write_file("prompts/judge.yaml", "prompts: []\n")
    await server.write_file("datasets/ref.yaml", "data: []\n")
    return "已生成完整场景包"


# ── 沙盒工具面 ──────────────────────────────────────────────────────────


class TestSandbox:
    def test_write_rejects_path_escape(self, tmp_path: Path) -> None:
        server = PackageToolServer(tmp_path)

        async def run() -> None:
            for evil in ("../evil.yaml", "/tmp/evil.yaml", "rules/../../evil.yaml"):
                result = await server.write_file(evil, "x")
                assert "越出包根" in result["error"], evil

        asyncio.run(run())
        assert not (tmp_path.parent / "evil.yaml").exists()

    def test_write_rejects_symlink_escape(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "outside.md"
        outside.write_text("秘密", encoding="utf-8")
        (tmp_path / "link.md").symlink_to(outside)
        result = asyncio.run(PackageToolServer(tmp_path).write_file("link.md", "覆盖"))
        assert "越出包根" in result["error"]

    def test_write_rejects_non_whitelisted_ext(self, tmp_path: Path) -> None:
        result = asyncio.run(PackageToolServer(tmp_path).write_file("run.sh", "x"))
        assert "白名单" in result["error"]

    def test_write_intercepts_credential_plaintext(self, tmp_path: Path) -> None:
        server = PackageToolServer(tmp_path)

        async def run() -> None:
            bad = await server.write_file(
                "sut_configs/sut.yaml", "sut:\n  password: hunter2-secret\n"
            )
            assert "安全红线" in bad["error"]
            assert "secrets set" in bad["error"]
            for clean in ("password: ${SASAN_PASSWORD}", "token: ''", "secret:"):
                ok = await server.write_file("sut_configs/sut.yaml", f"sut:\n  {clean}\n")
                assert "error" not in ok, clean

        asyncio.run(run())
        assert server.staging  # 干净内容已入暂存

    def test_read_prefers_staged_and_missing(self, tmp_path: Path) -> None:
        _seed_valid_package(tmp_path)
        server = PackageToolServer(tmp_path)

        async def run() -> None:
            await server.write_file("rules/quality.yaml", "rules: [staged]\n")
            staged = await server.read_file("rules/quality.yaml")
            assert "staged" in staged["content"]
            missing = await server.read_file("nope.yaml")
            assert "error" in missing

        asyncio.run(run())

    def test_delete_requires_existence(self, tmp_path: Path) -> None:
        _seed_valid_package(tmp_path)
        server = PackageToolServer(tmp_path)

        async def run() -> None:
            missing = await server.delete_file("nope.yaml")
            assert "error" in missing
            ok = await server.delete_file("rules/quality.yaml")
            assert ok["staged_delete"] == "rules/quality.yaml"

        asyncio.run(run())

    def test_update_manifest_merges_fields(self, tmp_path: Path) -> None:
        _seed_valid_package(tmp_path)
        server = PackageToolServer(tmp_path)
        asyncio.run(server.update_manifest({"version": "0.2.0", "labels": ["staging"]}))
        assert "0.2.0" in server.staging["agent_eval.yaml"]
        assert "staging" in server.staging["agent_eval.yaml"]

    def test_validate_empty_and_minimal(self, tmp_path: Path) -> None:
        server = PackageToolServer(tmp_path)

        async def run() -> None:
            empty = await server.validate_package()
            assert not empty["ok"] and empty["errors"]
            await _write_valid(server)
            ok = await server.validate_package()
            assert ok["ok"], ok["errors"]

        asyncio.run(run())

    def test_validate_rejects_md_only_prompts(self, tmp_path: Path) -> None:
        # 实测 Agent 曾把提示词写成 README 式 .md——下游加载器只认 .yaml，静默失效
        server = PackageToolServer(tmp_path)

        async def run() -> None:
            await server.write_file("agent_eval.yaml", MANIFEST)
            await server.write_file("rules/quality.yaml", RULES)
            await server.write_file("prompts/README.md", "# 说明\n")
            await server.write_file("datasets/README.md", "占位\n")
            result = await server.validate_package()
            assert not result["ok"]
            assert any("缺少 YAML" in e for e in result["errors"])

        asyncio.run(run())

    def test_commit_is_atomic_and_reports_changes(self, tmp_path: Path) -> None:
        _seed_valid_package(tmp_path)
        server = PackageToolServer(tmp_path)

        async def run() -> None:
            await server.write_file("rules/new.yaml", RULES)
            await server.delete_file("prompts/judge.yaml")

        asyncio.run(run())
        # 提交前磁盘不受影响（不变量：磁盘只见确认且校验通过的内容）
        assert not (tmp_path / "rules" / "new.yaml").exists()
        assert (tmp_path / "prompts" / "judge.yaml").exists()
        changed = server.commit()
        assert (tmp_path / "rules" / "new.yaml").is_file()
        assert not (tmp_path / "prompts" / "judge.yaml").exists()
        assert changed == ["D prompts/judge.yaml", "M rules/new.yaml"]  # 按路径排序提交
        assert not server.staging

    def test_render_diff_marks_changes(self, tmp_path: Path) -> None:
        _seed_valid_package(tmp_path)
        server = PackageToolServer(tmp_path)
        asyncio.run(server.write_file("rules/quality.yaml", "rules: [r-new]\n"))
        diff = server.render_diff()
        assert "+rules: [r-new]" in diff and "-rules:" in diff

    def test_search_reference_offline(self) -> None:
        result = asyncio.run(PackageToolServer(Path()).search_reference("chat"))
        assert result["query"] == "chat" and result["notes"]
        # notes 附真实文件树（猜路径失败时可就近取得正确相对路径）
        assert "rules/chat-quality.yaml" in result["notes"]

    def test_read_reference_builtin_and_escape(self) -> None:
        server = PackageToolServer(Path())

        async def run() -> None:
            ok = await server.read_reference("chat", "rules/chat-quality.yaml")
            assert "error" not in ok and "rules" in ok["content"]
            escape = await server.read_reference("chat", "../../pyproject.toml")
            assert "越出参考包根" in escape["error"]
            missing = await server.read_reference("nope-pkg", "x.yaml")
            assert "error" in missing

        asyncio.run(run())

    def test_read_reference_miss_returns_available_files(self) -> None:
        """猜错路径时返回该包真实清单，供 Agent 就近重试。"""
        server = PackageToolServer(Path())

        async def run() -> None:
            miss = await server.read_reference("chat", "prompts/judge.yaml")
            assert "文件不存在或不可读" in miss["error"]
            assert miss["available_files"], "必须给出实际文件清单供重试"
            assert "rules/chat-quality.yaml" in miss["available_files"]
            assert "available_files"  # hint 指引重试
            retry = await server.read_reference("chat", miss["available_files"][0])
            assert "error" not in retry

        asyncio.run(run())

    def test_staged_manifest_id(self) -> None:
        """暂存清单 id 读取——确认提示据此显示预计落点。"""
        server = PackageToolServer(Path())
        assert server.staged_manifest_id() is None  # 空暂存

        async def stage() -> None:
            await server.write_file(
                "agent_eval.yaml",
                "package:\n  id: demo-pkg\n  scenario: demo\n  version: 0.1.0\n",
            )

        asyncio.run(stage())
        assert server.staged_manifest_id() == "demo-pkg"


# ── WorkbenchAgent 会话状态机（mock _invoke 回放） ────────────────────────


class TestAgentTurn:
    def test_turn_confirm_then_commit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, calls = _replay([_write_valid])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert result.committed and result.staged
        assert (tmp_path / "rules" / "quality.yaml").is_file()
        assert any(f.startswith("M ") for f in result.committed_files)
        assert result.reply == "已生成完整场景包"
        assert len(calls) == 1

    def test_turn_user_abort_rolls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, _ = _replay([_write_valid])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: False))

        assert result.aborted_reason == "user_aborted" and not result.committed
        assert not agent.server.staging  # 暂存清空
        assert not (tmp_path / "rules").exists()  # 磁盘未受影响
        # 文件变更回滚但对话上下文保留（含本轮讨论），显式回滚说明防 Agent 误判
        assert any("生成包" in str(m) for m in agent._messages)
        assert any("放弃" in str(m) for m in agent._messages)

    def test_dialogue_persisted_and_replayed_on_resume(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 实测教训：会话中断重开后进程内历史清零，用户此前给的评测地址全部丢失
        root = tmp_path / "pkg"

        fake, _ = _replay([_write_valid])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        first = WorkbenchAgent(root, log_dir=tmp_path / "log")
        asyncio.run(
            first.turn("评测地址 https://sut.example.com，请生成包", confirm_fn=lambda r, d: True)
        )
        assert first.resumed_dialogue_count == 2  # user + assistant 要点已持久化

        async def cont(server: PackageToolServer) -> str:
            return "继续"

        fake2, calls = _replay([cont])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake2)
        resumed = WorkbenchAgent(root, log_dir=tmp_path / "log")  # 模拟新进程续作
        assert resumed.resumed_dialogue_count == 2
        asyncio.run(resumed.turn("继续", confirm_fn=lambda r, d: True))
        injected = str(calls[0][0])  # 首条注入消息
        assert "续接此前会话" in injected and "sut.example.com" in injected

    def test_turn_validate_gate_fix_rounds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def broken(server: PackageToolServer) -> str:
            await server.write_file("agent_eval.yaml", MANIFEST)  # 缺资源目录
            return "初版"

        fake, calls = _replay([broken, _write_valid])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert result.committed  # 门禁回改一轮后通过
        assert len(calls) == 2
        assert isinstance(calls[1][-1], tuple)  # 第 2 次调用末尾是 fix_validation 注入消息
        assert (tmp_path / "rules" / "quality.yaml").is_file()

    def test_turn_exhausts_fix_rounds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def broken(server: PackageToolServer) -> str:
            await server.write_file("agent_eval.yaml", MANIFEST)
            return "仍不完整"

        fake, _ = _replay([broken, broken])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(
            tmp_path, config=WorkbenchAgentConfig(max_fix_rounds=2), log_dir=tmp_path / "log"
        )

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert not result.committed
        assert result.aborted_reason == "max_fix_rounds"
        assert result.validation_errors
        assert not (tmp_path / "agent_eval.yaml").exists()  # 门禁未过不落盘

    def test_turn_no_changes_short_circuits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def noop(server: PackageToolServer) -> str:
            return "无需改动"

        fake, _ = _replay([noop])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")

        result = asyncio.run(agent.turn("看看", confirm_fn=lambda r, d: True))

        assert not result.staged and not result.committed and result.diff == ""

    def test_agent_protocol_channel_requires_probe_protocol(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """落盘门禁：声明 agent_protocol 通道的 base_url 主机必须经 probe_protocol
        实测（实测教训：创建会话未做协议探测把入口页面域写进 base_url，执行时
        commands 端点 404——红线从提示升级为门禁）。"""
        sut_yaml = (
            "sut:\n  name: bj33\n  channel: agent_protocol\n"
            "  base_url: ${BJ33_AGENT_URL:-https://agent.staging.example.com}\n"
        )

        async def write_sut(server: PackageToolServer) -> str:
            await _write_valid(server)
            await server.write_file("sut_configs/bj33.yaml", sut_yaml)
            return "写了 sut 配置（未探测协议）"

        fake, _ = _replay([write_sut, write_sut])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(
            tmp_path, config=WorkbenchAgentConfig(max_fix_rounds=2), log_dir=tmp_path / "log"
        )

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert not result.committed  # 未实测 → 门禁打回
        assert any("probe_protocol" in e for e in result.validation_errors)
        assert not (tmp_path / "sut_configs" / "bj33.yaml").exists()  # 门禁未过不落盘

        # Agent 实测过该主机后放行
        agent.probe._protocol_hosts.add("agent.staging.example.com")  # noqa: SLF001
        fake2, _ = _replay([write_sut])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake2)
        retry = asyncio.run(agent.turn("已按提示探测，重写", confirm_fn=lambda r, d: True))
        assert retry.committed

    def test_protocol_gate_skips_non_agent_protocol_channel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """门禁只针对 agent_protocol 通道：http 等通道不受 probe_protocol 约束。"""

        async def write_http_sut(server: PackageToolServer) -> str:
            await _write_valid(server)
            await server.write_file(
                "sut_configs/api.yaml",
                "sut:\n  name: api\n  channel: http\n  base_url: https://api.example.com\n",
            )
            return "写了 http 通道配置"

        fake, _ = _replay([write_http_sut])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert result.committed  # 非 agent_protocol 通道不触发门禁

    def test_first_turn_text_uses_templates(self) -> None:
        text = WorkbenchAgent.first_turn_text(
            "做一个客服质检包", new_package=True, ref="demo/quality"
        )
        assert "客服质检包" in text and "demo/quality" in text

    def test_first_turn_text_agent_chosen_ref(self) -> None:
        # ref 省略：指引 Agent 按需求拟定引用并在计划首行给出
        text = WorkbenchAgent.first_turn_text("研学计划质检", new_package=True)
        assert "拟定" in text and "{ref}" not in text

    def test_build_system_prompt_keeps_literal_braces(self, tmp_path: Path) -> None:
        # 回归：提示词含 `{ type: ... }` 字面大括号示例，str.format 会误吞（冒烟实测）
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        prompt = agent._build_system_prompt()
        assert "- write_file:" in prompt  # {tools} 已展开
        assert str(tmp_path.resolve()) in prompt  # {pkg_root} 已展开
        assert "{ type:" in prompt  # 字面大括号原样保留

    def test_turn_streams_events_to_on_event(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, _ = _replay([_write_valid])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        events: list[dict[str, Any]] = []

        asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True, on_event=events.append))

        assert {"type": "token", "text": "已生成完整场景包"} in events
        assert {"type": "phase", "name": "confirm"} in events  # 确认前关闭流式文本行

    def test_turn_interrupt_rolls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Ctrl+C 中断（协内表现为 CancelledError）：暂存清空 + 历史截断，
        # 磁盘从未见过本轮内容。不用 KeyboardInterrupt 直抛——Runner 的 SIGINT
        # 机制会接管并重试循环（实测死循环）
        async def boom(
            self: WorkbenchAgent, messages: list[Any], *, on_event: Any = None
        ) -> dict[str, Any]:
            await self.server.write_file("rules/a.yaml", RULES)
            raise asyncio.CancelledError

        monkeypatch.setattr(WorkbenchAgent, "_invoke", boom)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert not agent.server.staging
        assert agent._messages == []
        assert not (tmp_path / "rules").exists()

    def test_emit_tool_events_from_updates(self) -> None:
        from agent_eval.agent.workbench_agent import _emit_tool_events

        events: list[dict[str, Any]] = []
        updates = {
            "model": {
                "messages": [
                    SimpleNamespace(
                        type="ai",
                        content="计划",
                        tool_calls=[{"name": "write_file", "args": {"path": "rules/a.yaml"}}],
                    )
                ]
            },
            "tools": {
                "messages": [
                    SimpleNamespace(
                        type="tool",
                        name="write_file",
                        content='{"ok": true, "staged": "rules/a.yaml"}',
                        status="success",
                    )
                ]
            },
        }
        _emit_tool_events(updates, events.append)
        assert events[0] == {
            "type": "tool_start",
            "name": "write_file",
            "args": {"path": "rules/a.yaml"},
        }
        assert events[1]["type"] == "tool_end" and events[1]["ok"] is True

    def test_invoke_streams_block_content_and_collects_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # KIMI/Claude 系模型 content 为 blocks（thinking/text）——真机冒烟实测曾因
        # isinstance(str) 过滤导致 token 零输出
        from agent_eval.agent.workbench_agent import _text_from_content

        assert _text_from_content("纯文本") == "纯文本"
        assert (
            _text_from_content(
                [{"type": "thinking", "thinking": "内心"}, {"type": "text", "text": "回复"}]
            )
            == "回复"
        )

        class _FakeGraph:
            def __init__(self, script: list[tuple[str, Any]]) -> None:
                self.script = script

            async def astream(self, inp: dict, config: dict | None = None, stream_mode: Any = None):
                for mode, payload in self.script:
                    yield (mode, payload)

            async def ainvoke(self, inp: dict, config: dict | None = None) -> dict:
                return {"messages": ["fallback"]}

        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        agent._graph = _FakeGraph(
            [
                (
                    "messages",
                    (
                        SimpleNamespace(
                            type="AIMessageChunk",  # 增量 chunk 的真实 type（实测）
                            content=[{"type": "thinking", "thinking": "想一下"}],
                        ),
                        {},
                    ),
                ),
                (
                    "messages",
                    (
                        SimpleNamespace(
                            type="AIMessageChunk", content=[{"type": "text", "text": "计划"}]
                        ),
                        {},
                    ),
                ),
                ("messages", (SimpleNamespace(type="tool", content='{"ok": 1}'), {})),
                (
                    "messages",
                    (
                        SimpleNamespace(
                            type="AIMessageChunk",
                            content=[],
                            # 工具参数增量生成（大文件内容不走 text 流）
                            tool_call_chunks=[{"name": "write_file", "args": '{"path": "a"'}],
                        ),
                        {},
                    ),
                ),
                (
                    "updates",
                    {
                        "model": {
                            "messages": [
                                SimpleNamespace(
                                    type="ai",
                                    content=[],
                                    tool_calls=[{"name": "validate_package", "args": {}}],
                                )
                            ]
                        }
                    },
                ),
                ("values", {"messages": ["final-state"]}),
            ]
        )
        events: list[dict[str, Any]] = []
        state = asyncio.run(agent._invoke([("user", "hi")], on_event=events.append))

        assert {"type": "thinking", "text": "想一下"} in events
        assert {"type": "token", "text": "计划"} in events
        assert {"type": "tool_start", "name": "validate_package", "args": {}} in events
        assert {"type": "tool_args", "name": "write_file", "delta": 12} in events
        assert not any(e["type"] == "tool_end" for e in events)  # 工具消息不发 token 事件
        assert state == {"messages": ["final-state"]}  # values 收集最终态（不走 ainvoke 兜底）


# ── CLI 入口（guard / 非交互开关 / REPL 循环 / builtin 只读） ────────────


class TestCliEntries:
    def test_new_noninteractive_requires_instruction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_eval.cli.cmds.workbench_agent import agent_new_package

        monkeypatch.setattr("agent_eval.cli.cmds.workbench_agent._guard_llm_ready", lambda: None)
        with pytest.raises(typer.Exit) as exc:
            agent_new_package(
                ref="x/y", output=tmp_path / "p", instruction=None, yes=True, trust_agent=True
            )
        assert exc.value.exit_code == 2

    def test_new_noninteractive_happy_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_eval.cli.cmds import workbench_agent as sa

        monkeypatch.setattr(sa, "_guard_llm_ready", lambda: None)
        monkeypatch.setattr(
            "agent_eval.agent.workbench_agent.run_turn",
            lambda agent, text, *, confirm_fn, on_event=None: TurnResult(
                reply="ok", diff="d", staged=True, committed=True, committed_files=["M a.yaml"]
            ),
        )
        root = sa.agent_new_package(
            ref="x/y", output=tmp_path / "p", instruction="需求", yes=True, trust_agent=True
        )
        assert root == tmp_path / "p" and root.is_dir()

    def test_new_agent_derives_ref_and_moves(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ref 省略：草稿落 workspace/.staging（conftest 钉 WORKSPACE_DIR 到
        # tmp_path/workspace），会话结束后按清单 id 归位 cwd 直出 <id>-package/
        from agent_eval.cli.cmds import workbench_agent as sa

        monkeypatch.setattr(sa, "_guard_llm_ready", lambda: None)
        monkeypatch.chdir(tmp_path)

        def fake_run_turn(agent, text, *, confirm_fn, on_event=None):
            (agent.server.root / "agent_eval.yaml").write_text(
                "package:\n  id: study-trip\n  scenario: travel\n", encoding="utf-8"
            )
            return TurnResult(
                reply="ok", diff="d", staged=True, committed=True, committed_files=["M a.yaml"]
            )

        monkeypatch.setattr("agent_eval.agent.workbench_agent.run_turn", fake_run_turn)
        root = sa.agent_new_package(
            ref=None, output=None, instruction="研学计划质检", yes=True, trust_agent=True
        )
        assert root == tmp_path / "study-trip-package"  # cwd 直出（形态 B）
        assert (root / "agent_eval.yaml").is_file()
        # 草稿已迁走：.staging 下不留 agent-eval-pkg-* 残留
        assert not any(p.name.startswith("agent-eval-pkg-") for p in tmp_path.rglob("*"))

    def test_new_agent_interrupted_keeps_draft(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_eval.cli.cmds import workbench_agent as sa

        monkeypatch.setattr(sa, "_guard_llm_ready", lambda: None)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "agent_eval.agent.workbench_agent.run_turn",
            lambda agent, text, *, confirm_fn, on_event=None: (_ for _ in ()).throw(typer.Exit(1)),
        )
        with pytest.raises(typer.Exit):
            sa.agent_new_package(
                ref=None, output=None, instruction="需求", yes=True, trust_agent=True
            )
        # 中断 ≠ 放弃：草稿保留在 workspace/.staging，可 --output 指回续作
        drafts = list((tmp_path / "workspace" / ".staging").glob("agent-eval-pkg-*"))
        assert len(drafts) == 1 and drafts[0].is_dir()

    def test_finalize_conflict_keeps_draft(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_eval.cli.cmds.workbench_agent import _finalize_new_package

        monkeypatch.chdir(tmp_path)
        root = tmp_path / "gen"  # 草稿位
        root.mkdir()
        (root / "agent_eval.yaml").write_text(
            "package:\n  id: dup\n  scenario: s\n", encoding="utf-8"
        )
        (tmp_path / "dup-package").mkdir()  # cwd 直出目标已占位
        with pytest.raises(typer.Exit) as exc:
            _finalize_new_package(root, movable=True)
        assert exc.value.exit_code == 1
        assert root.is_dir()  # 草稿保留，交用户处置（换名/手动 mv）

    def test_new_output_nonempty_allowed_for_continuation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--output 指向非空目录放行（续作草稿），默认路径仍要求空。"""
        from agent_eval.cli.cmds import workbench_agent as sa

        monkeypatch.setattr(sa, "_guard_llm_ready", lambda: None)
        monkeypatch.setattr(
            "agent_eval.agent.workbench_agent.run_turn",
            lambda agent, text, *, confirm_fn, on_event=None: TurnResult(
                reply="ok", diff="d", staged=True, committed=True, committed_files=["M a.yaml"]
            ),
        )
        draft = tmp_path / "draft"  # 预置非空草稿（模拟中断遗留）
        draft.mkdir()
        (draft / "agent_eval.yaml").write_text(
            "package:\n  id: wip\n  scenario: s\n", encoding="utf-8"
        )
        root = sa.agent_new_package(
            ref=None, output=draft, instruction="继续", yes=True, trust_agent=True
        )
        assert root == draft  # --output 原地生成，不归位

    def test_finalize_not_movable_noop(self, tmp_path: Path) -> None:
        from agent_eval.cli.cmds.workbench_agent import _finalize_new_package

        assert _finalize_new_package(tmp_path, movable=False) == tmp_path

    def test_landing_hint_from_staged_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """确认提示的预计落点：草稿区暂存 id → cwd/<id>-package/。"""
        from types import SimpleNamespace

        from agent_eval.cli.cmds.workbench_agent import _landing_hint

        monkeypatch.chdir(tmp_path)
        draft = tmp_path / "workspace" / ".staging" / "agent-eval-pkg-abcd1234"
        draft.mkdir(parents=True)
        agent = SimpleNamespace(
            server=SimpleNamespace(
                root=draft,
                staged_manifest_id=lambda: "study-trip",
            )
        )
        hint = _landing_hint(agent)
        assert hint == tmp_path / "study-trip-package"

        # 无暂存清单（磁盘也没有）→ 不提示
        empty = SimpleNamespace(
            server=SimpleNamespace(root=tmp_path / "empty", staged_manifest_id=lambda: None)
        )
        assert _landing_hint(empty) is None

    def test_edit_rejects_builtin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_eval.cli.cmds.workbench_agent import agent_edit_package

        monkeypatch.setattr("agent_eval.cli.cmds.workbench_agent._guard_llm_ready", lambda: None)
        with pytest.raises(typer.Exit) as exc:
            agent_edit_package(ref="chat", instruction=None, yes=False, trust_agent=False)
        assert exc.value.exit_code == 1

    def test_edit_rejects_single_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_eval.cli.cmds.workbench_agent import agent_edit_package

        _seed_valid_package(tmp_path)
        monkeypatch.setattr("agent_eval.cli.cmds.workbench_agent._guard_llm_ready", lambda: None)
        with pytest.raises(typer.Exit) as exc:
            agent_edit_package(ref=str(tmp_path), instruction="改", yes=True, trust_agent=False)
        assert exc.value.exit_code == 2

    def test_repl_session_loop_exits_on_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_eval.cli.cmds import workbench_agent as sa

        _seed_valid_package(tmp_path)
        seen: list[str] = []
        inputs = iter(["加一条规则", ""])  # 首轮需求 + 空行退出（勿按 seen 取值：
        # run_turn 每轮异常会让 seen 永不增长 → REPL 无限循环吃满 CPU，实测教训）
        monkeypatch.setattr(
            "agent_eval.agent.workbench_agent.run_turn",
            lambda agent, text, *, confirm_fn, on_event=None: (
                seen.append(text) or TurnResult(reply="ok", diff="", staged=False)
            ),
        )
        monkeypatch.setattr(sa, "ask", lambda prompt: next(inputs))
        sa._session(WorkbenchAgent(tmp_path, log_dir=tmp_path / "log"), None)
        assert seen == ["加一条规则"]  # 一轮后空输入退出

    def test_repl_first_turn_error_contained(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 首轮瞬时错误（LLM 网关断流等）不杀会话——曾因首轮在 try 外直接 traceback 退出
        from agent_eval.cli.cmds import workbench_agent as sa

        _seed_valid_package(tmp_path)
        monkeypatch.setattr(
            "agent_eval.agent.workbench_agent.run_turn",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("peer closed")),
        )
        monkeypatch.setattr(sa, "ask", lambda prompt: "")
        sa._session(WorkbenchAgent(tmp_path, log_dir=tmp_path / "log"), "首轮需求")  # 不上抛


# ── 流式渲染（claude code 式工作过程直播） ──────────────────────────────


class TestStreamRender:
    def test_emitter_streams_tokens_and_tools(self, capsys) -> None:
        from agent_eval.cli.cmds.workbench_agent import _make_stream_emitter
        from agent_eval.cli.console.output import set_output_format

        set_output_format("text")
        emit, finish = _make_stream_emitter()
        emit({"type": "token", "text": "计划："})
        emit({"type": "token", "text": "新增一条规则"})
        emit({"type": "tool_start", "name": "write_file", "args": {"path": "rules/a.yaml"}})
        emit(
            {
                "type": "tool_end",
                "name": "write_file",
                "ok": True,
                "output": '{"staged": "rules/a.yaml"}',
            }
        )
        emit({"type": "tool_end", "name": "read_file", "ok": False, "output": "not json"})
        emit({"type": "token", "text": "完成"})
        emit({"type": "phase", "name": "confirm"})
        finish()
        out = capsys.readouterr().out
        assert "计划：新增一条规则" in out  # token 直出同线拼接
        assert "🔧 write_file · rules/a.yaml" in out  # 工具行带关键参数
        assert "已暂存 rules/a.yaml" in out
        assert "⚠ read_file: not json" in out  # 错误降级为可见提示
        assert "完成" in out

    def test_emitter_renders_thinking_stream(self, capsys) -> None:
        from agent_eval.cli.cmds.workbench_agent import _make_stream_emitter
        from agent_eval.cli.console.output import set_output_format

        set_output_format("text")
        emit, finish = _make_stream_emitter()
        emit({"type": "thinking", "text": "先想想"})
        emit({"type": "thinking", "text": "再想想"})
        emit({"type": "token", "text": "结论"})
        finish()
        out = capsys.readouterr().out
        assert "先想想再想想" in out and "结论" in out
        assert "✻" in out and "🤖" in out  # 思考/正文各自起行标记

    def test_emitter_swallows_leading_blank_lines(self, capsys) -> None:
        # 模型 text 段常以 \n\n 开头——段首空白吞掉，🤖 后不空行
        from agent_eval.cli.cmds.workbench_agent import _make_stream_emitter
        from agent_eval.cli.console.output import set_output_format

        set_output_format("text")
        emit, finish = _make_stream_emitter()
        emit({"type": "token", "text": "\n\n正文开始"})
        emit({"type": "token", "text": "继续"})
        finish()
        out = capsys.readouterr().out
        assert "🤖 正文开始继续" in out

    def test_emitter_tool_args_silent_non_tty(self, capsys) -> None:
        # 非 TTY 不渲染 \r 进度行（管道日志免受控制符污染），事件本身不崩
        from agent_eval.cli.cmds.workbench_agent import _make_stream_emitter
        from agent_eval.cli.console.output import set_output_format

        set_output_format("text")
        emit, finish = _make_stream_emitter()
        emit({"type": "tool_args", "name": "write_file", "delta": 100})
        emit({"type": "tool_start", "name": "write_file", "args": {}})
        finish()
        out = capsys.readouterr().out
        assert "🔧 write_file" in out and "⏳" not in out and "\r" not in out


# ── 泛化文件工具（Claude Code 式分级授权，arch/15 §6.11.1） ─────────────


class TestGeneralizedFileTools:
    def test_read_file_assets_auto_granted(self, tmp_path: Path) -> None:
        """随包资源 assets/ 为自动授权只读域——结构规范整篇可读。"""
        server = PackageToolServer(tmp_path)

        async def run() -> None:
            guide = await server.read_file(
                str(server.assets_root / "guides" / "scenario-package-format.md")
            )
            assert "error" not in guide
            assert "包清单" in guide["content"]

        asyncio.run(run())

    def test_read_file_external_grant_records_once(self, tmp_path: Path) -> None:
        """外部文件经 ask_fn 授权；授权记账后同文件不再二次询问。"""
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "user-doc.md"
        outside.write_text("用户提供的数据", encoding="utf-8")
        server = PackageToolServer(root)
        asks: list[str] = []

        async def ask_fn(question: str, *, options: Any, secret: bool) -> str:
            asks.append(question)
            return "允许"

        server.ask_fn = ask_fn

        async def run() -> None:
            first = await server.read_file(str(outside))
            assert "用户提供的数据" in first["content"]
            second = await server.read_file(str(outside))
            assert "error" not in second

        asyncio.run(run())
        assert len(asks) == 1

    def test_read_file_external_deny_blacklists(self, tmp_path: Path) -> None:
        """拒绝即拉黑：后续同路径直接拒绝且不再询问（防反复试探）。"""
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "user-doc.md"
        outside.write_text("x", encoding="utf-8")
        server = PackageToolServer(root)

        async def ask_fn(question: str, *, options: Any, secret: bool) -> str:
            return "拒绝"

        server.ask_fn = ask_fn

        async def run() -> None:
            first = await server.read_file(str(outside))
            assert "用户拒绝" in first["error"]
            second = await server.read_file(str(outside))
            assert "勿再试探" in second["error"]

        asyncio.run(run())

    def test_read_file_external_needs_interactive_channel(self, tmp_path: Path) -> None:
        """非交互（CI）无授权通道：报错指引放入会话根目录。"""
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "user-doc.md"
        outside.write_text("x", encoding="utf-8")
        result = asyncio.run(PackageToolServer(root).read_file(str(outside)))
        assert "需用户授权" in result["error"]
        assert "会话根目录" in result["error"]

    def test_read_file_credential_paths_hard_denied(self, tmp_path: Path) -> None:
        # 凭证类路径先于授权逻辑硬拒（红线：凭证不回流 LLM 上下文）——用户同意也不可读
        root = tmp_path / "root"
        root.mkdir()
        server = PackageToolServer(root)

        async def ask_fn(question: str, *, options: Any, secret: bool) -> str:
            raise AssertionError("凭证路径不得进入授权询问")

        server.ask_fn = ask_fn

        async def run() -> None:
            for evil in (
                Path.home() / ".agent_eval" / "llm.json",
                Path.home() / ".agent_eval" / "sut_credentials.json",
                tmp_path / "root" / ".env",
                tmp_path / "workspace" / "sut_sessions" / "sasan.json",
            ):
                result = await server.read_file(str(evil))
                assert "安全红线" in result["error"], evil

        asyncio.run(run())

    def test_list_files_session_statuses_and_assets(self, tmp_path: Path) -> None:
        _seed_valid_package(tmp_path)
        server = PackageToolServer(tmp_path)

        async def run() -> None:
            await server.write_file("rules/new.yaml", RULES)
            listing = await server.list_files("")
            statuses = {f["path"]: f["status"] for f in listing["files"]}
            assert statuses["rules/new.yaml"] == "added"
            assert statuses["rules/quality.yaml"] == "unchanged"
            assets = await server.list_files(str(server.assets_root))
            assert "guides/scenario-package-format.md" in assets["files"]

        asyncio.run(run())

    def test_list_files_external_requires_grant(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        outside_dir = tmp_path / "user-data"
        outside_dir.mkdir()
        (outside_dir / "a.txt").write_text("1", encoding="utf-8")
        server = PackageToolServer(root)

        no_channel = asyncio.run(server.list_files(str(outside_dir)))
        assert "需用户授权" in no_channel["error"]

        async def ask_fn(question: str, *, options: Any, secret: bool) -> str:
            return "允许"

        server.ask_fn = ask_fn
        ok = asyncio.run(server.list_files(str(outside_dir)))
        assert ok["files"] == ["a.txt"]

    def test_system_prompt_references_guide_without_hardcoded_structure(
        self, tmp_path: Path
    ) -> None:
        # 结构知识外置（§6.11.1）：提示词只指路规范文档，字段表不再 hardcode
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        prompt = agent._build_system_prompt()
        assert "scenario-package-format.md" in prompt
        assert str(agent.server.assets_root) in prompt  # {assets_root} 已展开
        assert "内容规范" not in prompt

    def test_system_prompt_workbench_identity_with_domain_segment(self, tmp_path: Path) -> None:
        # 定位升维（D-WB-2）：会话机段=工作台身份，场景包只是装配域段
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        prompt = agent._build_system_prompt()
        assert "工作台的对话式 Agent（WorkbenchAgent）" in prompt
        assert "场景包工程 · SUT 接入调试" in prompt  # {domain} 取 domain_labels
        assert "工作流程" in prompt and "SUT 接入调试" in prompt  # 域段已装配
        assert "场景包工程 Agent" not in prompt  # 旧身份清零

    def test_unknown_domain_rejected(self, tmp_path: Path) -> None:
        agent = WorkbenchAgent(tmp_path, domain="nope", log_dir=tmp_path / "log")
        with pytest.raises(AgentError, match="未装配的域档位"):
            agent._build_system_prompt()

    def test_generate_template_points_to_guide(self) -> None:
        text = WorkbenchAgent.first_turn_text("做一个代码安全评测包", new_package=True)
        assert "scenario-package-format.md" in text
        assert "rules/" not in text  # 目录清单不再 hardcode 在模板（task_sets/sut_configs 除外）


class TestAgentConfig:
    """WorkbenchAgentConfig——tunables 单点载体（§6.11.2，§6.7 P2 CLI 旗标同注入路径）。"""

    def test_defaults_and_frozen(self) -> None:
        cfg = WorkbenchAgentConfig()
        assert cfg.max_turns == 40
        assert cfg.max_fix_rounds == 3
        assert cfg.probe_budgets  # 探测预算默认取 TOOL_BUDGETS
        with pytest.raises((AttributeError, TypeError)):  # frozen dataclass 禁改字段
            cfg.max_turns = 1  # type: ignore[misc]

    def test_probe_domain_injection(self, tmp_path: Path) -> None:
        # 探测域档位（预算/超时）经 config 注入 SUTProbeToolServer
        cfg = WorkbenchAgentConfig(probe_budgets={"probe_url": 1}, probe_timeout_s=2.5)
        agent = WorkbenchAgent(tmp_path, config=cfg, log_dir=tmp_path / "log")
        assert agent.probe.budgets == {"probe_url": 1}
        assert agent.probe.timeout_s == 2.5

    def test_resume_truncation_uses_config(self, tmp_path: Path) -> None:
        # 续作注入的条数与单条截断由 config 决定（原模块常量迁入）
        cfg = WorkbenchAgentConfig(resume_max_entries=1, resume_max_chars=5)
        dialogue = [
            {"role": "user", "text": "第一轮很长很长很长的需求"},
            {"role": "user", "text": "短需求"},
        ]
        joined = "\n".join(text for _, text in _resume_messages(dialogue, cfg))
        assert "短需求" in joined
        assert "第一轮很长" not in joined  # 条数取最后 1 条

    def test_config_defaults_and_frozen(self) -> None:
        # tunables 单点（§6.11.2）：默认值冻结，改动须经显式 config 注入
        cfg = WorkbenchAgentConfig()
        assert cfg.max_turns == 40 and cfg.max_fix_rounds == 3
        with pytest.raises(Exception):  # noqa: B017, PT011 — frozen dataclass 不允许改字段
            cfg.max_turns = 1  # type: ignore[misc]

    def test_config_injects_probe_domain(self, tmp_path: Path) -> None:
        # 探测域档位默认随 config 注入 SUTProbeToolServer（预算/超时可调）
        cfg = WorkbenchAgentConfig(probe_budgets={"probe_url": 1}, probe_timeout_s=2.5)
        agent = WorkbenchAgent(tmp_path, config=cfg, log_dir=tmp_path / "log")
        assert agent.probe.budgets == {"probe_url": 1}
        assert agent.probe.timeout_s == 2.5

    def test_resume_injection_respects_config(self, tmp_path: Path) -> None:
        # 续作注入条数/截断由 config 决定（原模块常量迁入）
        cfg = WorkbenchAgentConfig(resume_max_entries=1, resume_max_chars=10)
        dialogue = [{"role": "user", "text": "x" * 50}, {"role": "user", "text": "y"}]
        msgs = dict(WorkbenchAgent.__dict__) and _resume_messages(dialogue, cfg)
        joined = "\n".join(m[1] for m in msgs)
        assert "y" in joined and "xxx…" not in joined
