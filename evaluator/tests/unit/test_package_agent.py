"""PackageAgent / PackageToolServer 单测 — 沙盒红线、门禁回改、落盘原子性（arch/15 §六）。

LLM 链路以回放状态机 mock（monkeypatch ``PackageAgent._invoke``），
不依赖 deepagents / LLM / 网络；工具面直调异步方法。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import typer

from agent_eval.agent.package_agent import PackageAgent, TurnResult
from agent_eval.agent.package_tools import PackageToolServer

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
    """伪造 ``_invoke``：逐次消费 effects（async fn(server) -> str 回复），记录每次入参消息。"""
    calls: list[list[Any]] = []
    remaining = list(effects)

    async def fake_invoke(self: PackageAgent, messages: list[Any]) -> dict[str, Any]:
        calls.append(list(messages))
        reply = await remaining.pop(0)(self.server)
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


# ── PackageAgent 会话状态机（mock _invoke 回放） ────────────────────────


class TestAgentTurn:
    def test_turn_confirm_then_commit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, calls = _replay([_write_valid])
        monkeypatch.setattr(PackageAgent, "_invoke", fake)
        agent = PackageAgent(tmp_path, log_dir=tmp_path / "log")

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
        monkeypatch.setattr(PackageAgent, "_invoke", fake)
        agent = PackageAgent(tmp_path, log_dir=tmp_path / "log")

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: False))

        assert result.aborted_reason == "user_aborted" and not result.committed
        assert not agent.server.staging  # 暂存清空
        assert not (tmp_path / "rules").exists()  # 磁盘未受影响
        assert agent._messages == []  # 历史截断回本轮前，上下文与磁盘一致

    def test_turn_validate_gate_fix_rounds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def broken(server: PackageToolServer) -> str:
            await server.write_file("agent_eval.yaml", MANIFEST)  # 缺资源目录
            return "初版"

        fake, calls = _replay([broken, _write_valid])
        monkeypatch.setattr(PackageAgent, "_invoke", fake)
        agent = PackageAgent(tmp_path, log_dir=tmp_path / "log")

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
        monkeypatch.setattr(PackageAgent, "_invoke", fake)
        agent = PackageAgent(tmp_path, max_fix_rounds=2, log_dir=tmp_path / "log")

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
        monkeypatch.setattr(PackageAgent, "_invoke", fake)
        agent = PackageAgent(tmp_path, log_dir=tmp_path / "log")

        result = asyncio.run(agent.turn("看看", confirm_fn=lambda r, d: True))

        assert not result.staged and not result.committed and result.diff == ""

    def test_first_turn_text_uses_templates(self) -> None:
        text = PackageAgent.first_turn_text(
            "做一个客服质检包", new_package=True, ref="demo/quality"
        )
        assert "客服质检包" in text and "demo/quality" in text

    def test_build_system_prompt_keeps_literal_braces(self, tmp_path: Path) -> None:
        # 回归：提示词含 `{ type: ... }` 字面大括号示例，str.format 会误吞（冒烟实测）
        agent = PackageAgent(tmp_path, log_dir=tmp_path / "log")
        prompt = agent._build_system_prompt()
        assert "- write_file:" in prompt  # {tools} 已展开
        assert str(tmp_path.resolve()) in prompt  # {pkg_root} 已展开
        assert "{ type:" in prompt  # 字面大括号原样保留


# ── CLI 入口（guard / 非交互开关 / REPL 循环 / builtin 只读） ────────────


class TestCliEntries:
    def test_new_noninteractive_requires_instruction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_eval.cli.cmds.scenario_agent import agent_new_package

        monkeypatch.setattr("agent_eval.cli.cmds.scenario_agent._guard_llm_ready", lambda: None)
        with pytest.raises(typer.Exit) as exc:
            agent_new_package(
                ref="x/y", output=tmp_path / "p", instruction=None, yes=True, trust_agent=True
            )
        assert exc.value.exit_code == 2

    def test_new_noninteractive_happy_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_eval.cli.cmds import scenario_agent as sa

        monkeypatch.setattr(sa, "_guard_llm_ready", lambda: None)
        monkeypatch.setattr(
            "agent_eval.agent.package_agent.run_turn",
            lambda agent, text, *, confirm_fn: TurnResult(
                reply="ok", diff="d", staged=True, committed=True, committed_files=["M a.yaml"]
            ),
        )
        root = sa.agent_new_package(
            ref="x/y", output=tmp_path / "p", instruction="需求", yes=True, trust_agent=True
        )
        assert root == tmp_path / "p" and root.is_dir()

    def test_edit_rejects_builtin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_eval.cli.cmds.scenario_agent import agent_edit_package

        monkeypatch.setattr("agent_eval.cli.cmds.scenario_agent._guard_llm_ready", lambda: None)
        with pytest.raises(typer.Exit) as exc:
            agent_edit_package(ref="chat", instruction=None, yes=False, trust_agent=False)
        assert exc.value.exit_code == 1

    def test_edit_rejects_single_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_eval.cli.cmds.scenario_agent import agent_edit_package

        _seed_valid_package(tmp_path)
        monkeypatch.setattr("agent_eval.cli.cmds.scenario_agent._guard_llm_ready", lambda: None)
        with pytest.raises(typer.Exit) as exc:
            agent_edit_package(ref=str(tmp_path), instruction="改", yes=True, trust_agent=False)
        assert exc.value.exit_code == 2

    def test_repl_session_loop_exits_on_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_eval.cli.cmds import scenario_agent as sa

        _seed_valid_package(tmp_path)
        seen: list[str] = []
        monkeypatch.setattr(
            "agent_eval.agent.package_agent.run_turn",
            lambda agent, text, *, confirm_fn: (
                seen.append(text) or TurnResult(reply="ok", diff="", staged=False)
            ),
        )
        monkeypatch.setattr(sa, "ask", lambda prompt: "加一条规则" if not seen else "")
        sa._session(PackageAgent(tmp_path, log_dir=tmp_path / "log"), None)
        assert seen == ["加一条规则"]  # 一轮后空输入退出
