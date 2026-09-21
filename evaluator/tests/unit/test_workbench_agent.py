"""WorkbenchAgent / PackageToolServer 单测 — 沙盒红线、门禁回改、落盘原子性（arch/15 §六）。

LLM 链路以回放状态机 mock（monkeypatch ``WorkbenchAgent._invoke``），
不依赖 deepagents / LLM / 网络；工具面直调异步方法。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import typer

from agent_eval.agent.workbench.agent import (
    TurnResult,
    WorkbenchAgent,
    WorkbenchAgentConfig,
    _resume_messages,
    repair_orphan_tool_calls,
)
from agent_eval.agent.workbench.gates import sut_evidence_gate
from agent_eval.agent.workbench.memory import session_key
from agent_eval.agent.workbench.sut_probe import SUTProbeToolServer
from agent_eval.agent.workbench.tools import PackageToolServer
from agent_eval.core.exceptions import AgentError

MANIFEST = "package:\n  id: demo\n  scenario: demo\n  version: 0.1.0\n"
# evaluator 须为注册 ID（llm_judge 是 method 枚举值——规则引用对账门禁会打回）
RULES = "rules:\n  - id: r1\n    evaluator: format.response_format\n"
# 聚合策略必选（落盘门禁对账）；r1 无 stage 字段，空 stage_weights 即覆盖通过
POLICY = (
    "aggregation_policy:\n"
    "  id: p\n  scenario_id: demo\n"
    "  stage_weights: []\n"
    "  normalize_to: [0.0, 1.0]\n"
)


def _seed_valid_package(root: Path) -> None:
    """磁盘上放一个合法最小包（edit 会话 / update_manifest 场景）。"""
    for sub in ("rules", "prompts", "datasets"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "agent_eval.yaml").write_text(MANIFEST, encoding="utf-8")
    (root / "rules" / "quality.yaml").write_text(RULES, encoding="utf-8")
    (root / "prompts" / "judge.yaml").write_text("prompts: []\n", encoding="utf-8")
    (root / "datasets" / "ref.yaml").write_text("data: []\n", encoding="utf-8")
    (root / "metrics").mkdir(parents=True, exist_ok=True)
    (root / "metrics" / "policy.yaml").write_text(POLICY, encoding="utf-8")


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
    await server.write_file("metrics/policy.yaml", POLICY)
    return "已生成完整场景包"


async def _write_valid_with_skeleton(server: PackageToolServer, skeleton: str) -> str:
    """完整包 + 骨架（五阶段流程回放用）。"""
    await server.write_file("SKELETON.md", skeleton)
    return await _write_valid(server)


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

    def test_list_files_file_path_message_accurate(self, tmp_path: Path) -> None:
        """B9：传文件路径报「不是目录或不存在」（旧文案「目录不存在」对存在的文件
        是误导——回显 target 虽可自诊，文案仍须精确）。"""
        (tmp_path / "a.yaml").write_text("x: 1\n", encoding="utf-8")
        server = PackageToolServer(tmp_path)
        result = asyncio.run(server.list_files("a.yaml"))
        assert "不是目录或不存在" in result["error"]

    def test_preview_diff_empty_staging_gives_note(self, tmp_path: Path) -> None:
        """B10：空暂存的 preview_diff 带 note（其余空结果分支均有指引，此处曾缺）。"""
        server = PackageToolServer(tmp_path)
        result = asyncio.run(server.preview_diff())
        assert result["changed"] == 0 and "暂存区为空" in result["note"]

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

    def test_update_manifest_roundtrip_structure(self, tmp_path: Path) -> None:
        """实测事故回放：曾手拼 "package:\\n" + dump(扁平 dict)——子键零缩进、
        package: 为 null，落盘清单结构性损坏（read_manifest 的 get 回退又把坏
        结构读回「自洽」）。结构回读断言防回归。"""
        import yaml as _yaml

        _seed_valid_package(tmp_path)
        server = PackageToolServer(tmp_path)
        asyncio.run(server.update_manifest({"version": "0.2.0"}))
        content = server.staging["agent_eval.yaml"]
        assert "\n  id: demo" in content  # package 下字段两空格缩进
        data = _yaml.safe_load(content)
        assert data["package"]["id"] == "demo"
        assert data["package"]["version"] == "0.2.0"

    def test_validate_rejects_truncated_yaml_anywhere(self, tmp_path: Path) -> None:
        """实测事故回放：task_sets/smoke.yaml 首写被截断，解析门禁只扫 rules/
        时漏网（靠 Agent read_file 自检才发现）——全量 .yaml/.yml 解析，截断
        文件带路径打回。"""
        server = PackageToolServer(tmp_path)

        async def run() -> None:
            await _write_valid(server)
            # 绕过 write_file 预检直接入暂存（跨进程恢复的旧快照等旁路）——
            # validate 的全量解析门禁是纵深防御，截断文件带路径打回
            server.staging["task_sets/smoke.yaml"] = (
                'task_sets:\n  - id: smoke\n    steps: ["未闭合'
            )
            result = await server.validate_package()
            assert not result["ok"]
            assert any("task_sets/smoke.yaml" in e for e in result["errors"])

        asyncio.run(run())

    def test_write_file_rejects_truncated_yaml(self, tmp_path: Path) -> None:
        """截断 YAML 在写入时当场打回（垃圾进不了暂存，省掉靠 Agent 自检发现的
        一整轮）；合法 YAML 与非 YAML 扩展名不受影响。"""
        server = PackageToolServer(tmp_path)

        async def run() -> None:
            bad = await server.write_file("task_sets/smoke.yaml", 'a: "未闭合')
            assert "YAML 解析失败" in bad["error"] and "未入暂存区" in bad["error"]
            assert server.staging == {}
            ok = await server.write_file("task_sets/smoke.yaml", "task_sets: []\n")
            assert ok["ok"] is True and "task_sets/smoke.yaml" in server.staging
            md = await server.write_file("notes.md", '# 任意文本 "未闭合\n')
            assert md["ok"] is True

        asyncio.run(run())

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

    def test_validate_online_shape_without_datasets(self, tmp_path: Path) -> None:
        """回归（内置 chat 包曾被误拦）：清单声明 default_task_set = 在线 SUT 形态，
        考卷来自 task_sets/，datasets/ 不参与——不再硬性要求。"""
        server = PackageToolServer(tmp_path)

        async def run() -> None:
            await server.write_file("agent_eval.yaml", MANIFEST + "  default_task_set: default\n")
            await server.write_file("rules/quality.yaml", RULES)
            await server.write_file("prompts/judge.yaml", "template_id: j1\nsystem_prompt: x\n")
            await server.write_file("task_sets/default.yaml", "id: t1\nname: 考卷\ntasks: []\n")
            await server.write_file("metrics/policy.yaml", POLICY)
            result = await server.validate_package()
            assert result["ok"], result["errors"]
            assert not any("datasets" in e for e in result["errors"])

        asyncio.run(run())

    def test_validate_online_requires_task_sets(self, tmp_path: Path) -> None:
        # 在线形态缺考卷在落盘前打回——此前一路绿灯到运行时才炸（指南 §1 task_sets/ 必需）
        server = PackageToolServer(tmp_path)

        async def run() -> None:
            await server.write_file("agent_eval.yaml", MANIFEST + "  default_task_set: default\n")
            await server.write_file("rules/quality.yaml", RULES)
            await server.write_file("prompts/judge.yaml", "template_id: j1\nsystem_prompt: x\n")
            await server.write_file("metrics/policy.yaml", POLICY)
            result = await server.validate_package()
            assert not result["ok"]
            assert any("task_sets" in e for e in result["errors"])

        asyncio.run(run())

    def test_list_evaluators_returns_registered_ids(self, tmp_path: Path) -> None:
        server = PackageToolServer(tmp_path)

        async def run() -> None:
            result = await server.list_evaluators()
            assert "format.response_format" in result["evaluators"]
            assert "原样复制" in result["note"]

        asyncio.run(run())

    def test_list_evaluators_includes_staged_entry_points(self, tmp_path: Path) -> None:
        """草稿期暂存清单声明的 entry_points 同样装入快照（防「已声明却被告知不可用」假阴性）。"""
        server = PackageToolServer(tmp_path)

        async def run() -> None:
            await server.write_file(
                "agent_eval.yaml",
                MANIFEST
                + '  entry_points:\n    evaluators: "agent_eval.evaluation.evaluators.scenario.chat:register"\n',
            )
            result = await server.list_evaluators()
            assert "chat.answer_quality" in result["evaluators"]
            # 变量契约同面返回（copy, don't recall：user_prompt_template 变量照抄）
            assert result["prompt_variables"]["chat.answer_quality"] == [
                "content",
                "instruction",
                "must_mention",
            ]

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

    # ── list_packages / read_reference 三源发现（arch/15 v4.4） ──

    def _isolate_package_roots(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """三源发现根全部钉到 tmp：local 缺省 ~/.agent_eval（开发者真机有包）也要隔离。"""
        monkeypatch.setenv("AGENT_EVAL_PROJECT_DIR", str(tmp_path / "project"))
        monkeypatch.setenv("AGENT_EVAL_PACKAGE_DIR", str(tmp_path / "local"))

    def test_list_packages_three_sources(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._isolate_package_roots(tmp_path, monkeypatch)
        # project 包：<id>-package/agent_eval.yaml 一级子目录
        proj = tmp_path / "project" / "courseware-reasonableness-package"
        _seed_valid_package(proj)
        (proj / "agent_eval.yaml").write_text(
            "package:\n  id: courseware-reasonableness\n  scenario: courseware\n"
            "  version: 0.1.0\n  name: 课件合理性评测\n  description: 多维合理性\n",
            encoding="utf-8",
        )
        # local 包：<scenario>/<id>/<version>/agent_eval.yaml
        local = tmp_path / "local" / "code" / "my-pkg" / "1.2.3"
        _seed_valid_package(local)
        (local / "agent_eval.yaml").write_text(
            "package:\n  id: my-pkg\n  scenario: code\n  version: 1.2.3\n",
            encoding="utf-8",
        )

        result = asyncio.run(PackageToolServer(tmp_path).list_packages())
        by_ref = {p["ref"]: p for p in result["packages"]}
        assert result["total"] == len(result["packages"]) >= 3  # builtin 3 + project + local
        proj_pkg = by_ref["courseware/courseware-reasonableness:0.1.0"]
        assert proj_pkg["source"] == "project" and proj_pkg["editable"] is True
        assert proj_pkg["path"] == str(proj)
        assert proj_pkg["name"] == "课件合理性评测" and proj_pkg["description"] == "多维合理性"
        assert by_ref["code/my-pkg:1.2.3"]["source"] == "local"
        builtin = by_ref["chat/chat:1.0.0"]
        assert builtin["source"] == "builtin" and builtin["editable"] is False

    def test_list_packages_source_filter_and_invalid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._isolate_package_roots(tmp_path, monkeypatch)
        proj = tmp_path / "project" / "solo-package"
        _seed_valid_package(proj)
        server = PackageToolServer(tmp_path)
        only_project = asyncio.run(server.list_packages("project"))
        assert [p["ref"] for p in only_project["packages"]] == ["demo/demo:0.1.0"]
        only_builtin = asyncio.run(server.list_packages("builtin"))
        assert all(p["source"] == "builtin" for p in only_builtin["packages"])
        assert "未知 source" in asyncio.run(server.list_packages("telepathy"))["error"]

    def test_list_packages_notes_guide_edit_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._isolate_package_roots(tmp_path, monkeypatch)
        server = PackageToolServer(tmp_path)
        notes = asyncio.run(server.list_packages())["notes"]
        assert "edit_package" in notes and "换新 scenario/id" in notes
        assert "read_reference" in notes
        # 空结果给创建指引（project/local 隔离为空，仍剩 builtin → 需显式过滤 project）
        empty = asyncio.run(server.list_packages("project"))
        assert empty["total"] == 0 and "scenario new" in empty["notes"]

    def test_read_reference_project_package(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """项目包可经 read_reference 按 ref 直读（描述纠偏后链路不被破坏）。"""
        self._isolate_package_roots(tmp_path, monkeypatch)
        proj = tmp_path / "project" / "my-pack-package"
        _seed_valid_package(proj)
        result = asyncio.run(
            PackageToolServer(tmp_path).read_reference("demo/demo", "rules/quality.yaml")
        )
        assert "error" not in result and "format.response_format" in result["content"]
        assert result["package"] == "demo/demo:0.1.0"

    def test_reference_notes_mention_list_packages(self) -> None:
        result = asyncio.run(PackageToolServer(Path()).search_reference("chat"))
        assert "list_packages" in result["notes"]

    def test_tool_specs_include_list_packages(self) -> None:
        names = PackageToolServer(Path()).get_tool_names()
        assert "list_packages" in names
        assert "edit_package" in names
        assert len(PackageToolServer.TOOL_SPECS) == 14


# ── edit_package：会话内切换到既有包原位编辑（arch/15 v4.12.2 路由修复） ──


class TestEditPackage:
    """既有包轻量编辑正道：门槛分支 + 切根生命周期（含会话记录迁移）。"""

    def _isolate_roots(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
        """三源发现根 + workspace 全部钉到 tmp；返回（源包根，目标包根）。"""
        monkeypatch.setenv("AGENT_EVAL_PROJECT_DIR", str(tmp_path / "project"))
        monkeypatch.setenv("AGENT_EVAL_PACKAGE_DIR", str(tmp_path / "local"))
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
        src = tmp_path / "project" / "from-package"
        dst = tmp_path / "project" / "target-package"
        _seed_valid_package(src)
        _seed_valid_package(dst)
        (dst / "agent_eval.yaml").write_text(
            "package:\n  id: target\n  scenario: target\n  version: 0.2.0\n",
            encoding="utf-8",
        )
        return src, dst

    @staticmethod
    async def _confirm(question: str, *, options: list[str] | None, secret: bool) -> str:
        assert "切换" in question and "目标" in question
        return options[0] if options else "确认切换"

    @staticmethod
    def _no_relocate(root: Path, *, note: str | None = None) -> None:
        raise AssertionError("拒绝/取消路径不应触发切根")

    def test_refused_non_interactive(self) -> None:
        server = PackageToolServer(Path.cwd())  # ask_fn=None：无确认通道
        result = asyncio.run(server.edit_package("anywhere/any"))
        assert result["status"] == "refused" and "scenario edit" in result["reason"]

    def test_refused_builtin_readonly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._isolate_roots(tmp_path, monkeypatch)
        asked: list[str] = []

        async def ask(question: str, *, options: Any, secret: bool) -> str:
            asked.append(question)
            return "确认切换"

        server = PackageToolServer(tmp_path, ask_fn=ask)
        server.relocate_fn = self._no_relocate
        result = asyncio.run(server.edit_package("chat/chat"))
        assert result["status"] == "refused" and "fork" in result["reason"]
        assert asked == []  # 拒绝发生在确认之前

    def test_not_found_points_to_list_packages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._isolate_roots(tmp_path, monkeypatch)
        server = PackageToolServer(tmp_path, ask_fn=self._confirm)
        server.relocate_fn = self._no_relocate
        result = asyncio.run(server.edit_package("ghost/nothing"))
        assert result["status"] == "not_found" and "list_packages" in result["next_step"]

    def test_already_on_target_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src, _dst = self._isolate_roots(tmp_path, monkeypatch)
        server = PackageToolServer(src, ask_fn=self._confirm)
        server.relocate_fn = self._no_relocate
        result = asyncio.run(server.edit_package(str(src)))
        assert result["status"] == "already"

    def test_refused_when_staging_nonempty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        src, dst = self._isolate_roots(tmp_path, monkeypatch)

        async def never(question: str, *, options: Any, secret: bool) -> str:
            raise AssertionError("staging 非空应在确认之前拒绝")

        server = PackageToolServer(src, ask_fn=never)
        server.relocate_fn = self._no_relocate
        asyncio.run(server.write_file("rules/extra.yaml", "x: 1\n"))
        result = asyncio.run(server.edit_package("target/target"))
        assert result["status"] == "refused" and "放弃" in result["reason"]
        assert server.has_staged_changes and server.root == src.resolve()

    def test_declined_does_not_switch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        src, dst = self._isolate_roots(tmp_path, monkeypatch)

        async def decline(question: str, *, options: Any, secret: bool) -> str:
            return "取消"

        server = PackageToolServer(src, ask_fn=decline)
        server.relocate_fn = self._no_relocate
        server.skeleton_archive = "keep-me"
        result = asyncio.run(server.edit_package("target/target"))
        assert result["status"] == "declined"
        assert server.root == src.resolve()  # 未切根
        assert server.skeleton_archive == "keep-me"  # 旧根态不动

    def test_switch_lifecycle_with_real_agent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """快乐路径：确认后切根 + 图重建标记 + 旧根态清账 + 注记进对话 + 记录迁移。"""
        src, dst = self._isolate_roots(tmp_path, monkeypatch)
        agent = WorkbenchAgent(src, log_dir=tmp_path / "log", ask_fn=self._confirm)
        # 前置：模拟会话已有目标图与旧根态，切换后应全部复位/清账
        agent._graph = object()
        agent.server.skeleton_archive = "stale-skeleton"
        agent.server._granted.add(tmp_path / "outside")
        agent._session_store.record("hi", "hello", str(src))
        old_file = agent._session_store.session_file
        assert old_file.exists()

        result = asyncio.run(agent.server.edit_package("target/target"))

        assert result["status"] == "switched"
        assert agent.server.root == dst.resolve()
        assert agent._graph is None  # 图重建标记：下次调用烘焙新 {pkg_root}
        assert agent.server.skeleton_archive is None  # 骨架归档不跨根携带
        assert agent.server._granted == set()  # 授权账本不跨根携带
        assert agent.server.staging == {}  # 切根前 staging 为空（守卫隐含）
        # 系统注记进对话（Agent 知道以新位置为准）
        kind, text = agent._messages[-1]
        assert kind == "user" and "会话目标已切换" in text and str(dst) in text
        # 会话记录迁移：新 key 落位、旧 key 清除、store 指向新文件
        new_file = old_file.parent / session_key(dst)
        assert agent._session_store.session_file == new_file
        assert new_file.exists() and not old_file.exists()

    def test_relocate_fn_missing_defensive(self, tmp_path: Path) -> None:
        server = PackageToolServer(tmp_path, ask_fn=self._confirm)
        server.relocate_fn = None  # 防御：宿主装配缺失 → error 而非崩溃
        result = asyncio.run(server.edit_package("target/target"))
        assert "error" in result and "relocate_fn" in result["error"]


# ── 证据对账门禁的磁盘基线豁免（v4.12.3：既有包轻量编辑不触发凭证重验） ──

SUT_DISK = (
    "sut:\n"
    "  name: jxb-server\n"
    "  channel: generic_http\n"
    "  base_url: https://jxb.example.com\n"
    "  auth:\n"
    "    type: api_login\n"
    "    credential_ref: jxb-login\n"
    "    login:\n"
    "      method: POST\n"
    "      path: https://jxb.example.com/auth/login\n"
    '      body_template: \'{"u": "{{ username }}"}\'\n'
    "    extract:\n"
    "      token_path: token\n"
)


class TestEvidenceGateBaseline:
    """对账范围收窄至暂存增量：磁盘基线全等豁免，任何相对基线的变更仍需账本。"""

    @staticmethod
    def _seed_disk_sut(tmp_path: Path, name: str, content: str) -> None:
        sut_dir = tmp_path / "sut_configs"
        sut_dir.mkdir(parents=True, exist_ok=True)
        (sut_dir / name).write_text(content, encoding="utf-8")

    def test_untouched_disk_sut_not_reconciled(self, tmp_path: Path) -> None:
        """用户场景复刻：只改 task_sets，磁盘既有 sut_config 不再要求本会话实测。"""
        self._seed_disk_sut(tmp_path, "jxb-server.yaml", SUT_DISK)
        server = PackageToolServer(tmp_path)
        asyncio.run(server.write_file("task_sets/default.yaml", "cases: []\n"))
        assert sut_evidence_gate(server, SUTProbeToolServer()) == []

    def test_rewritten_identical_sut_exempt(self, tmp_path: Path) -> None:
        """本轮重写但与磁盘基线逐字段相同 → 豁免（无转述变形）。"""
        self._seed_disk_sut(tmp_path, "jxb-server.yaml", SUT_DISK)
        server = PackageToolServer(tmp_path)
        asyncio.run(server.write_file("sut_configs/jxb-server.yaml", SUT_DISK))
        assert sut_evidence_gate(server, SUTProbeToolServer()) == []

    def test_changed_login_path_requires_evidence(self, tmp_path: Path) -> None:
        """本轮改 login.path = 新结论 → 仍需账本实测（拦截力不降）。"""
        self._seed_disk_sut(tmp_path, "jxb-server.yaml", SUT_DISK)
        server = PackageToolServer(tmp_path)
        asyncio.run(
            server.write_file(
                "sut_configs/jxb-server.yaml", SUT_DISK.replace("/auth/login", "/auth/sso")
            )
        )
        errors = sut_evidence_gate(server, SUTProbeToolServer())
        assert errors and "未经本会话" in "\n".join(errors)

    def test_deleted_sut_staged_passes_gate(self, tmp_path: Path) -> None:
        """删除标记：无配置可对账（删除动作本身不在对账范围）。"""
        self._seed_disk_sut(tmp_path, "jxb-server.yaml", SUT_DISK)
        server = PackageToolServer(tmp_path)
        asyncio.run(server.delete_file("sut_configs/jxb-server.yaml"))
        assert sut_evidence_gate(server, SUTProbeToolServer()) == []

    def test_new_sut_without_baseline_still_gated(self, tmp_path: Path) -> None:
        """无磁盘基线的新文件：收窄前行为保持（api_login 无账本打回）。"""
        server = PackageToolServer(tmp_path)  # 磁盘无 sut_configs
        asyncio.run(server.write_file("sut_configs/new.yaml", SUT_DISK))
        errors = sut_evidence_gate(server, SUTProbeToolServer())
        assert errors and "未经本会话" in "\n".join(errors)

    def test_protocol_baseline_equality_exempt(self, tmp_path: Path) -> None:
        """agent_protocol 结论三元组与磁盘基线全等 → 豁免协议对账（无账本也过）。"""
        proto = (
            "sut:\n  name: web\n  channel: agent_protocol\n  base_url: https://web.example.com\n"
        )
        self._seed_disk_sut(tmp_path, "web.yaml", proto)
        server = PackageToolServer(tmp_path)
        asyncio.run(server.write_file("sut_configs/web.yaml", proto))
        assert sut_evidence_gate(server, SUTProbeToolServer()) == []

    def test_protocol_base_url_change_requires_evidence(self, tmp_path: Path) -> None:
        """换 base_url 域 = 新结论 → 打回（协议主机必须本会话实测）。"""
        self._seed_disk_sut(
            tmp_path,
            "web.yaml",
            "sut:\n  name: web\n  channel: agent_protocol\n  base_url: https://web.example.com\n",
        )
        server = PackageToolServer(tmp_path)
        asyncio.run(
            server.write_file(
                "sut_configs/web.yaml",
                "sut:\n  name: web\n  channel: agent_protocol\n"
                "  base_url: https://other.example.com\n",
            )
        )
        errors = sut_evidence_gate(server, SUTProbeToolServer())
        assert errors and "未经 probe_protocol 实测" in "\n".join(errors)


class TestRelocateRootConservation:
    """relocate_root 对既有目标会话记录的保育：不覆盖、对话并入、账本合并恢复。"""

    def _isolate_roots(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
        monkeypatch.setenv("AGENT_EVAL_PROJECT_DIR", str(tmp_path / "project"))
        monkeypatch.setenv("AGENT_EVAL_PACKAGE_DIR", str(tmp_path / "local"))
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
        src = tmp_path / "project" / "from-package"
        dst = tmp_path / "project" / "target-package"
        _seed_valid_package(src)
        _seed_valid_package(dst)
        (dst / "agent_eval.yaml").write_text(
            "package:\n  id: target\n  scenario: target\n  version: 0.2.0\n",
            encoding="utf-8",
        )
        return src, dst

    @staticmethod
    async def _confirm(question: str, *, options: Any, secret: bool) -> str:
        return options[0] if options else "确认切换"

    def test_existing_target_record_conserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """切到编辑过的既有包：目标对话史不丢、账本快照恢复且可续写。"""
        src, dst = self._isolate_roots(tmp_path, monkeypatch)
        target_file = tmp_path / "ws" / "agent_sessions" / session_key(dst)
        target_file.parent.mkdir(parents=True)
        fact = {
            "ref": "jxb-login",
            "method": "POST",
            "url": "https://jxb.example.com/auth/login",
            "body_template": '{"u": "{{ username }}"}',
            "token_path": "token",
            "auth_snippet": "auth: {}",
        }
        target_file.write_text(
            json.dumps(
                {
                    "root": str(dst),
                    "dialogue": [
                        {"role": "user", "text": "早前的问题"},
                        {"role": "assistant", "text": "早前的回答"},
                    ],
                    "snapshot": {
                        "staged": {},
                        "ledger": {
                            "verified_logins": {"jxb-login": fact},
                            "verified_protocols": {},
                        },
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        agent = WorkbenchAgent(src, log_dir=tmp_path / "log", ask_fn=self._confirm)
        result = asyncio.run(agent.server.edit_package("target/target"))

        assert result["status"] == "switched"
        assert agent._session_store.session_file == target_file
        assert agent.probe.verified_login("jxb-login") is not None  # 账本合并恢复
        agent._record_turn("新问题", "新回答")  # 续写不再覆盖目标史
        data = json.loads(target_file.read_text(encoding="utf-8"))
        texts = [d["text"] for d in data["dialogue"]]
        assert "早前的问题" in texts and "新问题" in texts
        # 合并后的账本随下一轮进度快照持久化
        assert data["snapshot"]["ledger"]["verified_logins"]["jxb-login"]["ref"] == "jxb-login"


# ── WorkbenchAgent 会话状态机（mock _invoke 回放） ────────────────────────


# ── 创建骨架（Plan-as-Artifact：开槽门禁 / commit 排除归档 / 事实机械回填） ──

SKELETON_OPEN = (
    "# 创建骨架（demo）\n"
    "## SUT 接入 sut_configs/sut.yaml\n"
    "- [ ] 事实槽：登录接口地址与字段形态？—— 证据：request 实测 + declare_token\n"
    "- [x] 事实槽：协议形态 generic_http（证据：probe_protocol 两形态核心端点均 ❌）\n"
    "## 考卷 task_sets/default.yaml\n"
    "- [ ] 决策槽：题目覆盖面与阈值（确认方：用户）\n"
)
SKELETON_CLOSED = (
    "# 创建骨架（demo）\n"
    "## SUT 接入 sut_configs/sut.yaml\n"
    "- [x] 事实槽：登录 POST https://sut.example.com/auth/login（证据：request 200 "
    "+ declare_token 提取成功，auth 段已机械生成）\n"
    "## 考卷 task_sets/default.yaml\n"
    "- [x] 决策槽：11 题覆盖六大类（证据：用户确认）\n"
)


class TestSkeletonWorkflow:
    """五阶段创建流程的骨架机制（arch/15）：配置只在事实齐备后生成。"""

    def test_validate_blocks_open_slots(self, tmp_path: Path) -> None:
        server = PackageToolServer(tmp_path)
        asyncio.run(server.write_file("SKELETON.md", SKELETON_OPEN))
        errors = asyncio.run(server.validate_package())["errors"]
        skeleton_errors = [e for e in errors if "SKELETON.md" in e]
        assert skeleton_errors and any("未闭合槽位" in e for e in skeleton_errors)
        assert any("事实槽：登录接口地址与字段形态" in e for e in skeleton_errors)

    def test_validate_requires_evidence_marker_on_closed_slots(self, tmp_path: Path) -> None:
        """闭槽 = 有证据的结论：- [x] 行缺「证据：」不放行（防表态式闭合）。"""
        server = PackageToolServer(tmp_path)
        asyncio.run(server.write_file("SKELETON.md", "# 骨架\n- [x] 事实槽：登录接口已实测\n"))
        errors = asyncio.run(server.validate_package())["errors"]
        assert any("证据" in e for e in errors)

    def test_validate_passes_all_slots_closed(self, tmp_path: Path) -> None:
        server = PackageToolServer(tmp_path)
        asyncio.run(server.write_file("SKELETON.md", SKELETON_CLOSED))
        errors = asyncio.run(server.validate_package())["errors"]
        assert not any("SKELETON.md" in e for e in errors)

    def test_no_skeleton_behaves_unchanged(self, tmp_path: Path) -> None:
        """骨架 opt-in：克隆/fork 既有包（无骨架）行为不变。"""
        server = PackageToolServer(tmp_path)
        asyncio.run(server.write_file("agent_eval.yaml", MANIFEST))
        errors = asyncio.run(server.validate_package())["errors"]
        assert not any("SKELETON.md" in e for e in errors)

    def test_commit_excludes_skeleton_and_archives(self, tmp_path: Path) -> None:
        server = PackageToolServer(tmp_path)
        asyncio.run(server.write_file("SKELETON.md", SKELETON_CLOSED))
        asyncio.run(server.write_file("agent_eval.yaml", MANIFEST))
        changed = server.commit()
        assert not (tmp_path / "SKELETON.md").exists()  # 过程产物不入包
        assert (tmp_path / "agent_eval.yaml").is_file()
        assert server.skeleton_archive == SKELETON_CLOSED  # 留档供宿主归档
        assert any("SKELETON.md" in f for f in changed)
        assert not server.has_staged_changes

    def test_append_skeleton_fact_accumulates(self, tmp_path: Path) -> None:
        server = PackageToolServer(tmp_path)
        server.append_skeleton_fact("事实槽：无骨架时静默忽略（证据：opt-in）")
        assert "SKELETON.md" not in server.staging  # 无骨架：静默忽略
        asyncio.run(server.write_file("SKELETON.md", "# 骨架\n- [ ] 事实槽：待验证\n"))
        server.append_skeleton_fact("事实槽：登录实测（证据：request 2xx）")
        text = server.staging["SKELETON.md"]
        assert "## 机械实测事实" in text
        assert "- [x] 事实槽：登录实测（证据：request 2xx）" in text
        server.append_skeleton_fact("事实槽：协议矩阵（证据：probe_protocol）")
        text2 = server.staging["SKELETON.md"]
        assert text2.count("- [x] 事实槽：") == 2  # 追加累积
        assert "- [ ] 事实槽：待验证" in text2  # Agent 自写的开槽不受影响

    def test_fact_append_survives_commit_round(self, tmp_path: Path) -> None:
        """提交轮吃掉骨架后，下一轮事实回填仍续写（skeleton_archive 兜底种子）。"""
        server = PackageToolServer(tmp_path)
        asyncio.run(server.write_file("SKELETON.md", "# 骨架\n"))
        server.commit()
        server.append_skeleton_fact("事实槽：二轮实测（证据：request 2xx）")
        assert "- [x] 事实槽：二轮实测" in server.staging["SKELETON.md"]

    def test_turn_blocks_open_skeleton_then_recovers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回放：开槽骨架被门禁打回 → 闭合后提交；骨架不入包、会话区有归档。"""

        async def open_skeleton(server: PackageToolServer) -> str:
            await server.write_file("SKELETON.md", SKELETON_OPEN)
            await _write_valid(server)
            return "初版（含开槽）"

        fake, calls = _replay(
            [open_skeleton, lambda s: _write_valid_with_skeleton(s, SKELETON_CLOSED)]
        )
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert result.committed
        assert len(calls) == 2  # 门禁打回一轮后通过
        assert not (tmp_path / "SKELETON.md").exists()  # 骨架不入包
        archived = agent._session_store.session_file.with_suffix(".SKELETON.md")  # noqa: SLF001
        assert archived.is_file()
        assert "证据：" in archived.read_text(encoding="utf-8")

    def test_probe_fact_sink_wired_in_agent(self, tmp_path: Path) -> None:
        """装配：探测 server 的 fact_sink 指向包沙盒的骨架机械回填（阶段1 落骨架
        后，阶段2 探测事实直达骨架）。"""
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        assert agent.probe.fact_sink is not None
        asyncio.run(agent.server.write_file("SKELETON.md", "# 骨架\n- [ ] 事实槽：登录形态？\n"))
        agent.probe.fact_sink("事实槽：装配冒烟（证据：test）")
        text = agent.server.staging["SKELETON.md"]
        assert "- [x] 事实槽：装配冒烟（证据：test）" in text


class TestWriteSutConfig:
    """机械物化（阶段3）：auth 从探测账本 verbatim 注入，幻觉字段内联打回。"""

    @staticmethod
    async def _allow(question: str, **kw: Any) -> str:
        return "允许"

    def _ledgered_server(self, tmp_path: Path) -> tuple[PackageToolServer, str]:
        """账本播种：走真实 request + declare_token 链生成 auth_snippet
        （MockTransport，零联网），绑定给包沙盒。"""
        import httpx

        from agent_eval.agent.workbench.sut_probe import SUTProbeToolServer
        from agent_eval.execution.auth.credentials import CredentialStore

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"token": "T0KPEN"}, request=request)

        probe = SUTProbeToolServer(
            allowed_hosts={"sut.example.com"},
            ask_fn=self._allow,
            credential_store=CredentialStore(
                env={
                    "AGENT_EVAL_SUT__SUT__USERNAME": "u1",
                    "AGENT_EVAL_SUT__SUT__PASSWORD": "p1",
                }
            ),
            http_client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler), timeout=1.0, follow_redirects=False
            ),
        )
        asyncio.run(
            probe.request(
                "POST",
                "https://sut.example.com/api/login",
                body='{"u": "{{ username }}", "p": "{{ password }}"}',
                ref="SUT",
            )
        )
        declared = asyncio.run(probe.declare_token("SUT", token_path="token"))
        assert declared["ok"] is True
        server = PackageToolServer(tmp_path)
        server.ledger = probe
        return server, declared["sut_config_auth_snippet"]

    def test_requires_verified_login(self, tmp_path: Path) -> None:
        """无账本事实 → 拒绝并引导先实测（auth 不能凭记忆/示例手写）。"""
        server = PackageToolServer(tmp_path)  # 未绑定账本
        result = asyncio.run(
            server.write_sut_config(
                "sut_configs/sut.yaml",
                {"name": "SUT", "channel": "generic_http", "base_url": "https://x.example.com"},
            )
        )
        assert "没有已验证的登录实测" in result["error"]
        assert "request" in result["error"] and "declare_token" in result["error"]

    def test_accepts_bare_filename_normalized_into_sut_configs(self, tmp_path: Path) -> None:
        """实测事故回放：裸名 <名字>.yaml 曾被「平铺文件」守卫拒之门外（parent 是
        "."），错误不指路致 Agent 在 payload 结构上空转多轮——裸名须机械归位
        sut_configs/ 后放行。"""
        server, _ = self._ledgered_server(tmp_path)
        result = asyncio.run(
            server.write_sut_config(
                "jxb-agent.yaml",  # 裸名（实测会话里的真实写法）
                {
                    "name": "SUT",
                    "channel": "generic_http",
                    "base_url": "https://sut.example.com",
                    "request_template": {
                        "steps": [
                            {
                                "name": "send",
                                "method": "POST",
                                "path": "/chat",
                                "body": {"content": "{{ input }}"},
                            }
                        ]
                    },
                    "response_mapping": {"text": "data.reply"},
                },
                credential_ref="SUT",
            )
        )
        assert "ok" in result, result
        assert "sut_configs/jxb-agent.yaml" in server.staging  # 归位到 sut_configs/
        assert result["staged"] == "sut_configs/jxb-agent.yaml"

    def test_rejects_nested_path_with_copyable_guidance(self, tmp_path: Path) -> None:
        server, _ = self._ledgered_server(tmp_path)
        result = asyncio.run(
            server.write_sut_config(
                "sut_configs/sub/sut.yaml",
                {"name": "SUT", "channel": "generic_http", "base_url": "https://x.example.com"},
            )
        )
        assert "平铺文件" in result["error"]
        assert "sut_configs/<名字>.yaml" in result["error"]  # 可照抄的权威形态
        assert not server.staging  # 未入暂存

    def test_injects_auth_verbatim_and_passes_gates(self, tmp_path: Path) -> None:
        """核心验收（plan §八-②）：注入的 auth 与账本 snippet 逐字节一致，且
        sut_evidence_gate 必过——「不再重探」的机制基础。"""
        import yaml

        from agent_eval.agent.workbench.gates import sut_evidence_gate

        server, snippet = self._ledgered_server(tmp_path)
        result = asyncio.run(
            server.write_sut_config(
                "sut_configs/sut.yaml",
                {
                    "name": "SUT",
                    "channel": "generic_http",
                    "base_url": "https://sut.example.com",
                    "request_template": {
                        "steps": [
                            {
                                "name": "send",
                                "method": "POST",
                                "path": "/chat",
                                "body": {"content": "{{ input }}"},
                            }
                        ]
                    },
                    "response_mapping": {"text": "data.reply"},
                },
                credential_ref="SUT",
            )
        )
        assert "ok" in result, result
        staged = server.staging["sut_configs/sut.yaml"]
        injected_auth = yaml.safe_load(staged)["sut"]["auth"]
        # 逐字节一致：snippet 再序列化与注入段完全相等（零转述的机械证明）
        assert (
            yaml.safe_dump({"auth": injected_auth}, allow_unicode=True, sort_keys=False).strip()
            == snippet
        )
        # 执行器同款 schema 校验 + 落盘对账门禁双绿
        from agent_eval.execution.registry import validate_sut_config_document

        assert validate_sut_config_document(yaml.safe_load(staged)) == []
        assert sut_evidence_gate(server, server.ledger) == []

    def test_rejects_agent_supplied_auth(self, tmp_path: Path) -> None:
        server, _ = self._ledgered_server(tmp_path)
        result = asyncio.run(
            server.write_sut_config(
                "sut_configs/sut.yaml",
                {
                    "name": "SUT",
                    "channel": "generic_http",
                    "base_url": "https://sut.example.com",
                    "auth": {"type": "none"},
                },
            )
        )
        assert "不接受手写" in result["error"]

    def test_rejects_hallucinated_step_fields_inline(self, tmp_path: Path) -> None:
        """内联 schema 校验：jxb 事故字段集在入暂存前当场打回（带教学指引）。"""
        server, _ = self._ledgered_server(tmp_path)
        result = asyncio.run(
            server.write_sut_config(
                "sut_configs/sut.yaml",
                {
                    "name": "SUT",
                    "channel": "generic_http",
                    "base_url": "https://sut.example.com",
                    "request_template": {
                        "steps": [
                            {
                                "name": "send",
                                "method": "POST",
                                "path": "/chat",
                                "kind": "http",
                                "until": "data.done",
                                "response_mapping": {"text": "x"},
                            }
                        ]
                    },
                },
            )
        )
        assert "schema 校验未通过" in result["error"]
        assert "kind" in result["error"] and "until" in result["error"]
        assert "sut_configs/sut.yaml" not in server.staging  # 未入暂存

    def test_fix_round_does_not_reprobe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """badcase 回放（plan §八-③）：修复环查账本，不触发重复实测——jxb 会话
        「验证过了又来一遍」的事故链在新流程下被改写：登录实测只发生（用户）一次。"""
        from agent_eval.agent.workbench.sut_probe.tokens import _render_auth_snippet

        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        probe_calls: list[tuple[Any, ...]] = []
        original_request = agent.probe.request

        async def counting_request(*args: Any, **kw: Any) -> Any:
            probe_calls.append(args)
            return await original_request(*args, **kw)

        monkeypatch.setattr(agent.probe, "request", counting_request)
        # 账本播种 = 此前已完成的那一次登录实测（snippet 由真实渲染器生成，与
        # declare_token 成功路径产出的逐字节同源）
        url, template, token_path = (
            "https://sut.example.com/api/login",
            '{"u": "{{ username }}"}',
            "token",
        )
        agent.probe._record_login(
            {
                "ref": "SUT",
                "method": "POST",
                "url": url,
                "body_template": template,
                "token_path": token_path,
                "token_source": "Bearer",
                "expires_in_path": "",
                "auth_snippet": _render_auth_snippet(
                    ref="SUT",
                    method="POST",
                    url=url,
                    template=template,
                    token_type="Bearer",
                    token_path=token_path,
                ),
            }
        )
        sut_fields: dict[str, Any] = {
            "name": "SUT",
            "channel": "generic_http",
            "base_url": "https://sut.example.com",
            "request_template": {
                "steps": [
                    {
                        "name": "send",
                        "method": "POST",
                        "path": "/chat",
                        "body": {"q": "{{ input }}"},
                    }
                ]
            },
            "response_mapping": {"text": "data.reply"},
        }

        async def incomplete(server: PackageToolServer) -> str:
            await server.write_sut_config("sut_configs/sut.yaml", sut_fields, credential_ref="SUT")
            await server.write_file("agent_eval.yaml", MANIFEST)
            return "初版（缺资源目录，触发修复环）"

        fake, calls = _replay(
            [incomplete, lambda s: _write_valid_with_skeleton(s, SKELETON_CLOSED)]
        )
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert result.committed  # 修复环一轮后通过
        assert len(calls) == 2
        assert probe_calls == []  # 整个提交链（含修复环）零重复实测——账本直供

    def test_agent_wires_ledger_and_sink(self, tmp_path: Path) -> None:
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        assert agent.server.ledger is agent.probe  # noqa: SLF001 — 装配内省
        assert agent.probe.fact_sink is not None  # noqa: SLF001


class TestCrossProcessResume:
    """跨进程续跑（v4.10）：暂存 + 骨架留档 + 证据账本随会话记录持久化，重启
    恢复——五阶段中间进度不再「跨进程蒸发」（实测事故：代理超时后建议重启续作，
    暂存与账本实际全丢，只能从头再来）。"""

    def _seed_login_fact(self, probe: Any) -> dict[str, str]:
        """账本播种（snippet 由真实渲染器生成，schema 必合法；零联网零真实链）。"""
        from agent_eval.agent.workbench.sut_probe.tokens import _render_auth_snippet

        url, template, token_path = (
            "https://sut.example.com/api/login",
            '{"u": "{{ username }}"}',
            "token",
        )
        fact = {
            "ref": "SUT",
            "method": "POST",
            "url": url,
            "body_template": template,
            "token_path": token_path,
            "token_source": "Bearer",
            "expires_in_path": "",
            "auth_snippet": _render_auth_snippet(
                ref="SUT",
                method="POST",
                url=url,
                template=template,
                token_type="Bearer",
                token_path=token_path,
                expires_in_path="",
            ),
        }
        probe._record_login(fact)  # noqa: SLF001 — 测试/门禁专用别名
        return fact

    def test_snapshot_roundtrip_restores_staging_and_ledger(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        draft = tmp_path / "draft"
        draft.mkdir()
        agent_a = WorkbenchAgent(draft, log_dir=tmp_path / "log")
        self._seed_login_fact(agent_a.probe)
        asyncio.run(agent_a.server.write_file("task_sets/smoke.yaml", "task_sets: []\n"))
        agent_a._record_turn("推进创建", "骨架已落、smoke 已写")

        session_file = agent_a._session_store.session_file
        raw = session_file.read_text(encoding="utf-8")
        assert '"snapshot"' in raw
        assert "T0KPEN" not in raw and "password" not in raw.lower()  # 无凭证值/明文字段

        agent_b = WorkbenchAgent(draft, log_dir=tmp_path / "log2")  # 模拟重启新进程
        assert "task_sets/smoke.yaml" in agent_b.server.staging  # 暂存恢复
        assert agent_b.probe.verified_login("sut") is not None  # 账本恢复（免重探）
        assert agent_b.restored_progress["staged"] == 1
        assert agent_b.restored_progress["logins"] == 1

    def test_resumed_agent_writes_sut_config_without_reprobe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """核心验收（v4.7 承诺跨进程成立）：新进程 write_sut_config 直接过账本
        注入——恢复的会话不重做已完成的登录实测。"""
        monkeypatch.chdir(tmp_path)
        draft = tmp_path / "draft"
        draft.mkdir()
        agent_a = WorkbenchAgent(draft, log_dir=tmp_path / "log")
        self._seed_login_fact(agent_a.probe)
        agent_a._record_turn("登录已验证", "账本已登记")

        agent_b = WorkbenchAgent(draft, log_dir=tmp_path / "log2")
        result = asyncio.run(
            agent_b.server.write_sut_config(
                "sut_configs/sut.yaml",
                {
                    "name": "SUT",
                    "channel": "generic_http",
                    "base_url": "https://sut.example.com",
                    "request_template": {
                        "steps": [
                            {
                                "name": "send",
                                "method": "POST",
                                "path": "/chat",
                                "body": {"content": "{{ input }}"},
                            }
                        ]
                    },
                    "response_mapping": {"text": "data.reply"},
                },
                credential_ref="SUT",
            )
        )
        assert result["ok"] is True, result
        assert "sut_configs/sut.yaml" in agent_b.server.staging
        assert result["auth_injected"]["credential_ref"] == "SUT"

    def test_resume_note_reports_restored_progress(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        draft = tmp_path / "draft"
        draft.mkdir()
        agent_a = WorkbenchAgent(draft, log_dir=tmp_path / "log")
        self._seed_login_fact(agent_a.probe)
        agent_a._record_turn("推进", "登录已验证")

        agent_b = WorkbenchAgent(draft, log_dir=tmp_path / "log2")

        async def _reply(_s: Any) -> str:
            return "继续推进"

        fake, _calls = _replay([_reply])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        asyncio.run(agent_b.turn("继续", confirm_fn=lambda r, d: True))

        notes = [m for m in agent_b._messages if "已恢复上次会话进度" in str(m)]
        assert len(notes) == 1
        assert "已验证登录 1 项" in str(notes[0])

    def test_snapshot_without_progress_is_noop(self, tmp_path: Path) -> None:
        """无快照/快照残缺：恢复为 no-op（新会话零影响）。"""
        server = PackageToolServer(tmp_path)
        assert server.import_staging_snapshot(None) == 0
        assert server.import_staging_snapshot({"staging": "垃圾"}) == 0
        assert server.staging == {}
        from agent_eval.agent.workbench.sut_probe import SUTProbeToolServer

        probe = SUTProbeToolServer(allowed_hosts=set())
        assert probe.restore_ledgers(None) == 0
        assert probe.restore_ledgers({"verified_logins": ["垃圾"]}) == 0
        assert probe.ledger_snapshot() == {"verified_logins": {}, "verified_protocols": {}}

    def test_local_skeleton_archive_wins_over_snapshot(self, tmp_path: Path) -> None:
        server = PackageToolServer(tmp_path)
        server.skeleton_archive = "# 本会话留档"
        restored = server.import_staging_snapshot(
            {"staging": {"a.yaml": "x"}, "skeleton_archive": "# 旧会话留档"}
        )
        assert restored == 1
        assert server.skeleton_archive == "# 本会话留档"  # 本地更新优先


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

        # Agent 实测过该主机（矩阵核心端点 ✅）后放行
        agent.probe._record_protocol(  # noqa: SLF001 — 单测模拟 probe_protocol 登记事实
            "agent.staging.example.com", "commands", {"send_command": True}
        )
        fake2, _ = _replay([write_sut])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake2)
        retry = asyncio.run(agent.turn("已按提示探测，重写", confirm_fn=lambda r, d: True))
        assert retry.committed

    def test_protocol_gate_rejects_unscheduled_channel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """通道排期门禁：browser 预留未排期，落盘即打回。

        实测教训：协议探测受挫后 Agent 自行降级写预留通道——创建侧当时全放行、
        执行期工厂才报错，用户答完 5 个交互才见失败。拦截前移到落盘前。
        """

        async def write_browser_sut(server: PackageToolServer) -> str:
            await _write_valid(server)
            await server.write_file(
                "sut_configs/ui.yaml",
                "sut:\n  name: ui\n  channel: browser\n  base_url: https://ui.example.com\n",
            )
            return "写了 browser 通道配置"

        fake, _ = _replay([write_browser_sut])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(
            tmp_path, config=WorkbenchAgentConfig(max_fix_rounds=1), log_dir=tmp_path / "log"
        )

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert not result.committed  # 未排期通道 → 门禁打回
        assert any("预留未排期" in e for e in result.validation_errors)
        assert any("不得静默降级" in e for e in result.validation_errors)
        assert not (tmp_path / "sut_configs" / "ui.yaml").exists()  # 门禁未过不落盘

    def test_generic_http_channel_passes_without_protocol_ledger(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """generic_http 已排期（v4.7 落地）且无协议端点语义：不需 probe_protocol
        账本即可落盘（登录对账仍由 _reconcile_login 覆盖）。"""

        async def write_http_sut(server: PackageToolServer) -> str:
            await _write_valid(server)
            await server.write_file(
                "sut_configs/api.yaml",
                "sut:\n  name: api\n  channel: generic_http\n  base_url: https://api.example.com\n"
                '  request_template:\n    method: POST\n    path: /chat\n    body: \'{"q": "{{ input }}"}\'\n',
            )
            return "写了 http 通道配置"

        fake, _ = _replay([write_http_sut])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert result.committed  # 已排期通道，协议对账不适用 → 放行
        assert (tmp_path / "sut_configs" / "api.yaml").exists()

    def test_protocol_gate_rejects_core_step_not_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """对账门禁：探测过但矩阵核心端点非 ✅（如建线程 404 的页面域）不能声明
        agent_protocol——旧门禁只查「host 探测过」，被 catch-all 假 ✅ 放行过。"""

        async def write_sut(server: PackageToolServer) -> str:
            await _write_valid(server)
            await server.write_file(
                "sut_configs/web.yaml",
                "sut:\n  name: web\n  channel: agent_protocol\n"
                "  base_url: https://web.example.com\n  protocol_flavor: commands\n",
            )
            return "写了协议配置（核心端点实际 ❌）"

        fake, _ = _replay([write_sut])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(
            tmp_path, config=WorkbenchAgentConfig(max_fix_rounds=1), log_dir=tmp_path / "log"
        )
        agent.probe._record_protocol(  # noqa: SLF001 — 模拟「探测过但建线程失败」矩阵
            "web.example.com", "commands", {"create_thread": False}
        )

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert not result.committed
        assert any("send_command 非 ✅" in e for e in result.validation_errors)
        assert not (tmp_path / "sut_configs" / "web.yaml").exists()

    # ── 登录对账（bj33 实测复盘：验证结论在落盘转述一步被变形） ──────────

    _LOGIN_URL = "https://sasan-server.staging.example.com/users/login"

    def _record_login_fact(self, agent: WorkbenchAgent) -> None:
        agent.probe._record_login(  # noqa: SLF001 — 单测模拟 declare_token 成功登记
            {
                "ref": "teacher-login",
                "method": "POST",
                "url": self._LOGIN_URL,
                "body_template": '{"phone": "{{ username }}"}',
                "token_path": "token",
                "auth_snippet": (
                    "auth:\n  type: api_login\n  credential_ref: teacher-login\n"
                    "  login:\n    method: POST\n"
                    f"    path: {self._LOGIN_URL}\n"
                    '    body_template: \'{"phone": "{{ username }}"}\'\n'
                    "  extract:\n    token_path: token\n    token_type: Bearer"
                ),
            }
        )

    def test_evidence_gate_rejects_deformed_login_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """实测成功的是 sasan-server 域登录接口，落盘被拆成相对 path + 自造
        login.base_url（执行器静默丢弃）拼回页面域——对账门禁用执行器同款
        URL 解析逐字段比对，打回并携带权威片段。"""
        sut_yaml = (
            "sut:\n  name: bj33\n  channel: agent_protocol\n"
            "  base_url: https://agent.staging.example.com\n  protocol_flavor: commands\n"
            "  auth:\n    type: api_login\n    credential_ref: teacher-login\n"
            "    login:\n      method: POST\n      path: /users/login\n"
            "      base_url: https://sasan-server.staging.example.com\n"
            '      body_template: \'{"phone": "{{ username }}"}\'\n'
            "    extract:\n      token_path: token\n"
        )

        async def write_sut(server: PackageToolServer) -> str:
            await _write_valid(server)
            await server.write_file("sut_configs/bj33.yaml", sut_yaml)
            return "写了登录配置（URL 被拆段）"

        fake, _ = _replay([write_sut])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(
            tmp_path, config=WorkbenchAgentConfig(max_fix_rounds=1), log_dir=tmp_path / "log"
        )
        agent.probe._record_protocol(  # noqa: SLF001
            "agent.staging.example.com", "commands", {"send_command": True}
        )
        self._record_login_fact(agent)

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert not result.committed
        joined = "\n".join(result.validation_errors)
        assert f"实测成功的是 {self._LOGIN_URL}" in joined  # 变形处被点明
        assert "sut_config_auth_snippet" in joined  # 指回权威片段
        # 自造 login.base_url 属未知字段：静默丢弃 → 显式打回（validate 层）
        assert any("未知字段 'base_url'" in e for e in result.validation_errors)
        assert not (tmp_path / "sut_configs" / "bj33.yaml").exists()

    def test_evidence_gate_passes_verbatim_snippet_landing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """原样照抄实测片段（path=完整 URL）→ 对账通过落盘。"""
        sut_yaml = (
            "sut:\n  name: bj33\n  channel: agent_protocol\n"
            "  base_url: https://agent.staging.example.com\n  protocol_flavor: commands\n"
            "  auth:\n    type: api_login\n    credential_ref: teacher-login\n"
            "    login:\n      method: POST\n"
            f"      path: {self._LOGIN_URL}\n"
            '      body_template: \'{"phone": "{{ username }}"}\'\n'
            "    extract:\n      token_path: token\n      token_type: Bearer\n"
        )

        async def write_sut(server: PackageToolServer) -> str:
            await _write_valid(server)
            await server.write_file("sut_configs/bj33.yaml", sut_yaml)
            return "已原样写入实测片段"

        fake, _ = _replay([write_sut])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        agent.probe._record_protocol(  # noqa: SLF001
            "agent.staging.example.com", "commands", {"send_command": True}
        )
        self._record_login_fact(agent)

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert result.committed, result.validation_errors
        assert (tmp_path / "sut_configs" / "bj33.yaml").is_file()

    def test_evidence_gate_expands_env_default_like_executor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """对账前先做执行器同款 ``${VAR:-默认}`` 展开——chat 式 env 缺省写法
        （完整 URL 藏在默认值里）不误判为变形。"""
        sut_yaml = (
            "sut:\n  name: bj33\n  channel: agent_protocol\n"
            "  base_url: https://agent.staging.example.com\n  protocol_flavor: commands\n"
            "  auth:\n    type: api_login\n    credential_ref: teacher-login\n"
            "    login:\n      method: POST\n"
            f"      path: ${{SASAN_LOGIN_URL:-{self._LOGIN_URL}}}\n"
            '      body_template: \'{"phone": "{{ username }}"}\'\n'
            "    extract:\n      token_path: token\n"
        )

        async def write_sut(server: PackageToolServer) -> str:
            await _write_valid(server)
            await server.write_file("sut_configs/bj33.yaml", sut_yaml)
            return "写了 env 缺省形态配置"

        fake, _ = _replay([write_sut])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        agent.probe._record_protocol(  # noqa: SLF001
            "agent.staging.example.com", "commands", {"send_command": True}
        )
        self._record_login_fact(agent)

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert result.committed, result.validation_errors

    def test_protocol_gate_error_carries_session_candidates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """门禁打回时机械复用会话内证据：登录实测成功的域是协议探测的头号候选
        （实测反馈：会话已解析出接口结构，打回后却又让用户重复提供）。"""

        async def write_sut(server: PackageToolServer) -> str:
            await _write_valid(server)
            await server.write_file(
                "sut_configs/web.yaml",
                "sut:\n  name: web\n  channel: agent_protocol\n"
                "  base_url: https://web.example.com\n",
            )
            return "把页面域写成了 agent_protocol"

        fake, _ = _replay([write_sut])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(
            tmp_path, config=WorkbenchAgentConfig(max_fix_rounds=1), log_dir=tmp_path / "log"
        )
        agent.probe._record_login(  # noqa: SLF001 — 模拟本会话已实测 sasan-server 域登录
            {
                "ref": "teacher-login",
                "method": "POST",
                "url": "https://sasan-server.example.com/users/login",
                "body_template": '{"phone": "{{ username }}"}',
                "token_path": "token",
                "auth_snippet": "auth: {}",
            }
        )

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert not result.committed
        joined = "\n".join(result.validation_errors)
        assert "候选接口域" in joined and "sasan-server.example.com" in joined
        assert "先 probe_protocol" in joined  # 先探测候选，全部落空再问用户

    def test_evidence_gate_requires_login_probe_evidence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """api_login 登录配置无本会话实测证据 → 打回（未验证的登录不得落盘）。"""

        async def write_sut(server: PackageToolServer) -> str:
            await _write_valid(server)
            await server.write_file(
                "sut_configs/x.yaml",
                "sut:\n  name: x\n  channel: agent_protocol\n"
                "  base_url: https://x.example.com\n"
                "  auth:\n    type: api_login\n    credential_ref: x-login\n"
                "    login:\n      method: POST\n      path: https://x.example.com/login\n",
            )
            return "写了未经实测的登录配置"

        fake, _ = _replay([write_sut])
        monkeypatch.setattr(WorkbenchAgent, "_invoke", fake)
        agent = WorkbenchAgent(
            tmp_path, config=WorkbenchAgentConfig(max_fix_rounds=1), log_dir=tmp_path / "log"
        )
        agent.probe._record_protocol(  # noqa: SLF001
            "x.example.com", "commands", {"send_command": True}
        )

        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert not result.committed
        joined = "\n".join(result.validation_errors)
        assert "未经本会话" in joined and "declare_token" in joined

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

    def test_turn_interrupt_pauses_with_scene_kept(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Ctrl+C 中断（协内表现为 CancelledError）= 暂停保现场（§6.7 D-WB-4）：
        # 暂存保留 + 历史保留（需求不丢），唯一回滚触发器是用户显式「放弃」。
        # 不用 KeyboardInterrupt 直抛——Runner 的 SIGINT 机制会接管并重试循环
        async def boom(
            self: WorkbenchAgent, messages: list[Any], *, on_event: Any = None
        ) -> dict[str, Any]:
            await self.server.write_file("rules/a.yaml", RULES)
            raise asyncio.CancelledError

        monkeypatch.setattr(WorkbenchAgent, "_invoke", boom)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert agent.server.staging  # 现场保留
        assert any(m[1] == "生成包" for m in agent._messages if isinstance(m, tuple))
        assert agent._dialogue and agent._dialogue[-1]["text"] == "生成包"
        assert not (tmp_path / "rules").exists()  # 暂存未确认，磁盘仍未见

        agent.abandon_pending()  # 用户显式放弃 → 唯一回滚触发器
        assert not agent.server.staging
        assert not (tmp_path / "rules").exists()

    def test_turn_keyboard_interrupt_salvages_and_reraises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 交互桥 ^C 以 KI 形态穿透工具层（v4.12.4）：turn 捕 BaseException →
        # salvage 保现场 → re-raise 交宿主呈现中断；KI 与 CancelledError 同归
        # reason="interrupted"（日志/事件语义，行为同为 raise）
        async def boom(
            self: WorkbenchAgent, messages: list[Any], *, on_event: Any = None
        ) -> dict[str, Any]:
            await self.server.write_file("rules/a.yaml", RULES)
            raise KeyboardInterrupt

        monkeypatch.setattr(WorkbenchAgent, "_invoke", boom)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")

        with pytest.raises(KeyboardInterrupt):
            asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))

        assert agent.server.staging  # salvage 保现场
        assert agent._dialogue and agent._dialogue[-1]["text"] == "生成包"

    def test_emit_tool_events_from_updates(self) -> None:
        from agent_eval.agent.workbench.messages import emit_tool_events as _emit_tool_events

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

    def test_todo_items_normalize_dict_and_object(self) -> None:
        # write_todos 落状态可能是 dict（TypedDict）也可能是对象形态——统一规范化
        from agent_eval.agent.workbench.messages import _todo_items

        assert _todo_items([{"content": "a", "status": "in_progress"}]) == [
            {"content": "a", "status": "in_progress"}
        ]
        assert _todo_items([SimpleNamespace(content="b", status="pending")]) == [
            {"content": "b", "status": "pending"}
        ]
        assert _todo_items(None) == []

    def test_stream_collect_extracts_todo_state(self) -> None:
        # write_todos 后 updates delta 携带 todos 键——提取成独立事件交宿主渲染
        from agent_eval.agent.workbench.messages import stream_collect as _stream_collect

        class _FakeGraph:
            async def astream(self, inp: dict, config: dict | None = None, stream_mode: Any = None):
                yield (
                    "updates",
                    {
                        "tools": {
                            "todos": [{"content": "探测接口", "status": "in_progress"}],
                            "messages": [],
                        }
                    },
                )
                yield ("values", {"messages": [_ai("清单已更新")], "todos": []})

        events: list[dict[str, Any]] = []
        final = asyncio.run(
            _stream_collect(_FakeGraph(), [], {"configurable": {"thread_id": "t"}}, events.append)
        )
        assert [e for e in events if e["type"] == "todos"] == [
            {"type": "todos", "todos": [{"content": "探测接口", "status": "in_progress"}]}
        ]
        assert final["messages"] == [_ai("清单已更新")]  # values 收集不受影响

    def test_invoke_streams_block_content_and_collects_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # KIMI/Claude 系模型 content 为 blocks（thinking/text）——真机冒烟实测曾因
        # isinstance(str) 过滤导致 token 零输出
        from agent_eval.agent.workbench.messages import text_from_content as _text_from_content

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
            "agent_eval.agent.workbench.agent.run_turn",
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

        monkeypatch.setattr("agent_eval.agent.workbench.agent.run_turn", fake_run_turn)
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
            "agent_eval.agent.workbench.agent.run_turn",
            lambda agent, text, *, confirm_fn, on_event=None: (_ for _ in ()).throw(typer.Exit(1)),
        )
        with pytest.raises(typer.Exit):
            sa.agent_new_package(
                ref=None, output=None, instruction="需求", yes=True, trust_agent=True
            )
        # 中断 ≠ 放弃：草稿保留在 workspace/.staging，可 --output 指回续作
        drafts = list((tmp_path / "workspace" / ".staging").glob("agent-eval-pkg-*"))
        assert len(drafts) == 1 and drafts[0].is_dir()

    def test_new_agent_interrupt_after_commit_still_finalizes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回归（实测：确认落盘后 Ctrl+C 退出，归位预告路径下找不到包）——清单已
        落盘 = 成果已完整，中断只是结束对话，照常归位不困在草稿区。"""
        from agent_eval.cli.cmds import workbench_agent as sa

        monkeypatch.setattr(sa, "_guard_llm_ready", lambda: None)
        monkeypatch.chdir(tmp_path)

        def fake_session(agent: Any, text: Any, *, show_intro: bool = True) -> None:
            (agent.server.root / "agent_eval.yaml").write_text(
                "package:\n  id: study-trip\n  scenario: travel\n", encoding="utf-8"
            )
            raise KeyboardInterrupt  # 用户在落盘完成后 Ctrl+C 退出

        monkeypatch.setattr(sa, "_session", fake_session)
        root = sa.agent_new_package(
            ref=None, output=None, instruction="研学计划质检", yes=False, trust_agent=False
        )
        assert root == tmp_path / "study-trip-package"
        assert (root / "agent_eval.yaml").is_file()
        assert not any(p.name.startswith("agent-eval-pkg-") for p in tmp_path.rglob("*"))

    def test_agent_entry_interrupt_after_commit_still_finalizes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """同上（start 一级入口形态）：中断时已落盘的包照常归位。"""
        from agent_eval.cli.cmds import workbench_agent as sa

        monkeypatch.setattr(sa, "_guard_llm_ready", lambda: None)
        monkeypatch.chdir(tmp_path)
        draft = tmp_path / "draft"
        monkeypatch.setattr(sa, "_new_draft_root", lambda: draft)

        def fake_session(agent: Any, text: Any, *, show_intro: bool = True) -> None:
            (agent.server.root / "agent_eval.yaml").write_text(
                "package:\n  id: sec-probe\n  scenario: security\n", encoding="utf-8"
            )
            raise KeyboardInterrupt

        monkeypatch.setattr(sa, "_session", fake_session)
        monkeypatch.setattr(sa, "_render_intro", lambda agent: None)
        sa.agent_workbench_entry(None)  # 不上抛（成果已归位，中断到此为止）
        assert (tmp_path / "sec-probe-package" / "agent_eval.yaml").is_file()
        assert not draft.exists()

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
            "agent_eval.agent.workbench.agent.run_turn",
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

    def test_landing_verb_matches_root_kind(self) -> None:
        """落点动词区分草稿区归位与既有包原位（v4.12.3：edit_package 切根后横幅
        曾一律称「归位」，实际是原位生效——文案与机制对齐）。"""
        from agent_eval.cli.cmds.workbench_agent import _landing_verb

        draft = Path("workspace/.staging/agent-eval-pkg-abcd1234")
        assert _landing_verb(draft) == "归位"
        assert _landing_verb(Path("proj/demo-package")) == "原位落盘"

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
            "agent_eval.agent.workbench.agent.run_turn",
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
            "agent_eval.agent.workbench.agent.run_turn",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("peer closed")),
        )
        monkeypatch.setattr(sa, "ask", lambda prompt: "")
        sa._session(WorkbenchAgent(tmp_path, log_dir=tmp_path / "log"), "首轮需求")  # 不上抛

    def test_repl_pause_then_abandon_rolls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # Ctrl+C 暂停（进度保留）→ 用户输入「放弃」→ 暂存回滚、会话继续（D-WB-4）
        from agent_eval.cli.cmds import workbench_agent as sa

        _seed_valid_package(tmp_path)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        states = iter(["paused", "abandoned", "done"])

        def fake_run_turn(agent_: Any, text: str, *, confirm_fn: Any, on_event: Any = None) -> Any:
            state = next(states)
            if state == "paused":
                raise asyncio.CancelledError  # Ctrl+C（协内形态）
            return TurnResult(reply="ok", diff="", staged=False)

        async def stage_secret() -> None:
            await agent.server.write_file("rules/a.yaml", RULES)

        monkeypatch.setattr("agent_eval.agent.workbench.agent.run_turn", fake_run_turn)
        inputs = iter(["继续", "放弃", ""])
        monkeypatch.setattr(sa, "ask", lambda prompt: next(inputs))
        asyncio.run(stage_secret())  # 预置暂存（模拟暂停轮遗留）
        sa._session(agent, None)
        out = capsys.readouterr().out
        assert "进度已保留" in out  # 暂停提示（替代旧「已回滚」语义）
        assert "已放弃暂存改动" in out
        assert not agent.server.staging  # 「放弃」= 唯一回滚触发器
        assert not (tmp_path / "rules" / "a.yaml").exists()  # 暂存未落盘

    def test_repl_idle_ctrlc_armed_double_press_exits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # 空闲态 ^C 二按退出（v4.12.4 对齐 Claude Code）：首按只武装提示不退会话，
        # 二按才退出——误触不再有清场代价
        from agent_eval.cli.cmds import workbench_agent as sa

        _seed_valid_package(tmp_path)
        presses = iter([typer.Abort, typer.Abort])

        def fake_ask(prompt: str) -> str:
            raise next(presses)

        monkeypatch.setattr(sa, "ask", fake_ask)
        sa._session(WorkbenchAgent(tmp_path, log_dir=tmp_path / "log"), None)
        out = capsys.readouterr().out
        assert "再按一次退出" in out  # 首按 armed 提示
        assert "会话结束" in out  # 二按退出

    def test_repl_idle_ctrlc_armed_resets_on_input(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # ^C 武装后输入任意内容即重置——误触用户正常续用，无残留状态
        from agent_eval.cli.cmds import workbench_agent as sa

        _seed_valid_package(tmp_path)
        monkeypatch.setattr(
            "agent_eval.agent.workbench.agent.run_turn",
            lambda agent, text, *, confirm_fn, on_event=None: TurnResult(
                reply="ok", diff="", staged=False
            ),
        )
        presses = iter([typer.Abort, "接着干", typer.Abort, typer.Abort])

        def fake_ask(prompt: str) -> str:
            item = next(presses)
            if isinstance(item, str):
                return item
            raise item

        monkeypatch.setattr(sa, "ask", fake_ask)
        sa._session(WorkbenchAgent(tmp_path, log_dir=tmp_path / "log"), None)
        out = capsys.readouterr().out
        assert out.count("再按一次退出") == 2  # 首按与重置后各武装一次，二按才退

    def test_emitter_renders_checkpoint_phase(self, capsys) -> None:
        # P1 自动分段：checkpoint 事件 → 「已自动续跑」提示行
        from agent_eval.cli.console.agent_stream import make_stream_emitter as _make_stream_emitter
        from agent_eval.cli.console.output import set_output_format

        set_output_format("text")
        emit, finish = _make_stream_emitter()
        emit({"type": "phase", "name": "checkpoint", "segment": 2, "max_segments": 3})
        finish()
        assert "已自动续跑（第 2 / 3 段" in capsys.readouterr().out

    def test_intro_text_from_asset(self, tmp_path: Path) -> None:
        # §6.10 横幅资产化：{root}/{domains} 展开，示例与红线同源（CLI 只渲染）
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        intro = agent.intro_text()
        assert "工作台 Agent" in intro
        assert str(tmp_path) in intro  # {root}
        assert "场景包工程 · SUT 接入调试" in intro  # {domains} 与系统提示同源
        assert "暂存" in intro and "Ctrl+C" in intro  # 红线与控制方式

    def test_session_renders_intro_banner(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        import sys as _sys

        from agent_eval.cli.cmds import workbench_agent as sa
        from agent_eval.cli.console.output import set_output_format

        set_output_format("text")
        _seed_valid_package(tmp_path)

        class _Tty:  # capsys 的 stdout 非 TTY——横幅设计为 TTY 专属，垫一层
            def __init__(self, inner: Any) -> None:
                self._inner = inner

            def isatty(self) -> bool:
                return True

            def __getattr__(self, name: str) -> Any:
                return getattr(self._inner, name)

        monkeypatch.setattr(sa.sys, "stdout", _Tty(_sys.stdout))
        monkeypatch.setattr(
            "agent_eval.agent.workbench.agent.run_turn",
            lambda agent, text, *, confirm_fn, on_event=None: TurnResult(
                reply="ok", diff="", staged=False
            ),
        )
        inputs = iter([""])
        monkeypatch.setattr(sa, "ask", lambda prompt: next(inputs))
        sa._session(WorkbenchAgent(tmp_path, log_dir=tmp_path / "log"), None)
        out = capsys.readouterr().out
        assert "工作台 Agent" in out and "可以这样用我" in out  # 横幅在会话日志行之前

    def test_intro_silent_for_non_tty(self, tmp_path: Path, capsys) -> None:
        # CI / 管道形态横幅静默（§6.10）
        from agent_eval.cli.cmds import workbench_agent as sa

        sa._render_intro(WorkbenchAgent(tmp_path, log_dir=tmp_path / "log"))
        assert capsys.readouterr().out == ""

    def test_agent_entry_direct_conversation_no_menu(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # §3.5 实测反馈：入口无前置菜单——横幅先于会话直入 REPL（Claude Code 式），
        # 新建/改已有包都是会话里的一句话；默认任务对象 = 新包草稿
        from agent_eval.cli.cmds import workbench_agent as sa

        monkeypatch.setattr(sa, "_guard_llm_ready", lambda: None)
        draft = tmp_path / "draft"
        monkeypatch.setattr(sa, "_new_draft_root", lambda: draft)
        order: list[str] = []
        monkeypatch.setattr(sa, "_render_intro", lambda agent: order.append("intro"))

        def fake_session(agent: Any, text: Any, *, show_intro: bool = True) -> None:
            assert show_intro is False  # 入口已渲染，会话内不重复
            order.append("session")

        monkeypatch.setattr(sa, "_session", fake_session)
        sa.agent_workbench_entry(None)
        assert order == ["intro", "session"]  # 介绍先于输入（顺序曾颠倒）
        assert not draft.exists()  # 空会话退出 → 草稿清理，不留残目录

    def test_agent_entry_keeps_draft_when_session_has_content(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 会话产出了部分内容但清单未落盘（用户提前退出）→ 归位失败保留草稿
        from agent_eval.cli.cmds import workbench_agent as sa

        monkeypatch.setattr(sa, "_guard_llm_ready", lambda: None)
        draft = tmp_path / "draft"
        monkeypatch.setattr(sa, "_new_draft_root", lambda: draft)

        def fake_session(agent: Any, text: Any, *, show_intro: bool = True) -> None:
            (agent.server.root / "rules").mkdir(parents=True)
            (agent.server.root / "rules" / "a.yaml").write_text(RULES, encoding="utf-8")

        monkeypatch.setattr(sa, "_session", fake_session)
        with pytest.raises(typer.Exit) as exc:
            sa.agent_workbench_entry(None)
        assert exc.value.exit_code == 1
        assert draft.exists()  # 草稿保留，--output 指回续作

    def test_agent_entry_interrupt_keeps_draft(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_eval.cli.cmds import workbench_agent as sa

        monkeypatch.setattr(sa, "_guard_llm_ready", lambda: None)
        draft = tmp_path / "draft"
        monkeypatch.setattr(sa, "_new_draft_root", lambda: draft)

        def boom(agent: Any, text: Any, *, show_intro: bool = True) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(sa, "_session", boom)
        with pytest.raises(KeyboardInterrupt):
            sa.agent_workbench_entry(None)
        assert draft.exists()  # 中断 ≠ 放弃：草稿保留

    def test_session_intro_flag_controls_banner(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # show_intro=False 抑制重复横幅（入口形态）；默认 True（scenario new/edit 直连）
        from agent_eval.cli.cmds import workbench_agent as sa

        _seed_valid_package(tmp_path)
        calls: list[bool] = []
        monkeypatch.setattr(sa, "_render_intro", lambda agent: calls.append(True))
        monkeypatch.setattr(
            "agent_eval.agent.workbench.agent.run_turn",
            lambda agent, text, *, confirm_fn, on_event=None: TurnResult(
                reply="ok", diff="", staged=False
            ),
        )
        inputs = iter(["", "", ""])
        monkeypatch.setattr(sa, "ask", lambda prompt: next(inputs))
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        sa._session(agent, None, show_intro=False)
        sa._session(agent, None)
        assert calls == [True]


# ── 交互等待期 Ctrl+C（v4.12.4 五态统一）：选择器 ^C = 中断本轮 ──────────────


class TestInterruptBridge:
    """宿主桥把 click 的 Abort（Exception 子类）转回 KI（BaseException）——

    KI 穿透工具层 `except Exception` 兜底直达 turn() 统一暂停语义。实测事故：
    Abort 被 _json_tool 吞成 `{"type":"Abort","message":""}` 回流 LLM，诱发重试；
    SIG_IGN 滞留整轮后 ^C 全面失效，空回车落默认「允许」放行外发。
    """

    def test_ask_fn_options_abort_becomes_ki(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_eval.cli.cmds import workbench_agent as sa

        def boom(label: str, options: list[str], **kwargs: Any) -> str:
            raise typer.Abort

        monkeypatch.setattr(sa, "select", boom)
        ask_fn = sa._make_ask_fn()
        with pytest.raises(KeyboardInterrupt):
            asyncio.run(ask_fn("允许探测？", options=["允许", "不允许"], secret=False))

    def test_ask_fn_secret_abort_becomes_ki(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_eval.cli.cmds import workbench_agent as sa

        def boom(label: str, **kwargs: Any) -> str:
            raise typer.Abort

        monkeypatch.setattr(sa, "ask", boom)
        ask_fn = sa._make_ask_fn()
        with pytest.raises(KeyboardInterrupt):
            asyncio.run(ask_fn("录入 phone", options=None, secret=True))

    def test_cli_confirm_abort_becomes_ki(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_eval.cli.cmds import workbench_agent as sa

        def boom(label: str, options: list[str], **kwargs: Any) -> str:
            raise typer.Abort

        monkeypatch.setattr(sa, "select", boom)
        with pytest.raises(KeyboardInterrupt):
            sa._cli_confirm("回复", "diff 内容", None)

    def test_json_tool_keyboard_interrupt_not_swallowed(self) -> None:
        # KI 是控制流信号不是工具错误：`except Exception` 兜底不得吞掉
        # （回归守卫——兜底若被改宽成 BaseException，五态统一在机制上瓦解）
        from agent_eval.agent.core.tools import ToolExporterMixin

        async def ki_tool() -> str:
            raise KeyboardInterrupt

        wrapped = ToolExporterMixin()._json_tool(ki_tool)
        with pytest.raises(KeyboardInterrupt):
            asyncio.run(wrapped())

    def test_json_tool_empty_message_falls_back_to_type_name(self) -> None:
        # str 为空的异常（click Abort 无参构造）至少可解释——空 message 曾诱发
        # Agent 盲目反问卡点
        from agent_eval.agent.core.tools import ToolExporterMixin

        class _SilentError(Exception):
            pass

        async def fail() -> str:
            raise _SilentError()

        wrapped = ToolExporterMixin()._json_tool(fail)
        payload = json.loads(asyncio.run(wrapped()))
        assert payload["status"] == "failed"
        assert payload["error"]["message"] == "_SilentError"


# ── 落盘即归位（v4.9）：首次确认落盘即归位 + 沙盒重定向 + 会话记录迁移 ────


class TestRelocateOnCommit:
    def _draft(self, tmp_path: Path, name: str = "agent-eval-pkg-ab12cd34") -> Path:
        draft = tmp_path / "workspace" / ".staging" / name
        draft.mkdir(parents=True)
        return draft

    def test_relocate_root_rebinds_and_migrates_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_eval.agent.workbench.memory import session_key

        monkeypatch.chdir(tmp_path)
        draft = self._draft(tmp_path)
        final = tmp_path / "study-trip-package"
        agent = WorkbenchAgent(draft, log_dir=tmp_path / "log")
        agent._session_store.record("需求", "已生成", str(draft))  # 会话记录已落盘
        old_file = agent._session_store.session_file
        assert old_file.is_file()

        agent.relocate_root(final)

        assert agent.server.root == final.resolve()
        new_file = old_file.parent / session_key(final)
        assert new_file.is_file() and not old_file.exists()  # 记录随包迁移
        assert agent._session_store.session_file == new_file
        assert agent._graph is None  # 系统提示烘焙了旧 {pkg_root}——强制重建
        notes = [m for m in agent._messages if "已归位" in str(m)]
        assert len(notes) == 1  # 归位事实进对话：Agent 知道以新位置为准

    def test_relocate_root_moves_skeleton_archive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:

        monkeypatch.chdir(tmp_path)
        draft = self._draft(tmp_path)
        agent = WorkbenchAgent(draft, log_dir=tmp_path / "log")
        agent._session_store.record("q", "a", str(draft))
        skeleton = agent._session_store.session_file.with_suffix(".SKELETON.md")
        skeleton.write_text("# 骨架", encoding="utf-8")

        agent.relocate_root(tmp_path / "study-trip-package")

        new_file = agent._session_store.session_file
        assert new_file.with_suffix(".SKELETON.md").is_file()  # 审计产物跟进新会话键
        assert not skeleton.exists()

    def test_relocate_root_same_root_noop(self, tmp_path: Path) -> None:
        root = tmp_path / "pkg"
        root.mkdir()
        agent = WorkbenchAgent(root, log_dir=tmp_path / "log")
        agent._graph = object()  # 非空标记：noop 不得触发重建
        agent.relocate_root(root)
        assert agent._graph is not None
        assert agent._messages == []

    def test_relocate_after_commit_moves_draft(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        draft = self._draft(tmp_path)
        (draft / "agent_eval.yaml").write_text(
            "package:\n  id: study-trip\n  scenario: travel\n", encoding="utf-8"
        )
        rebinds: list[Path] = []
        agent = SimpleNamespace(server=SimpleNamespace(root=draft), relocate_root=rebinds.append)

        from agent_eval.cli.cmds.workbench_agent import _relocate_after_commit

        landed = _relocate_after_commit(agent)

        assert landed == tmp_path / "study-trip-package"
        assert (landed / "agent_eval.yaml").is_file() and not draft.exists()
        assert rebinds == [landed]  # 沙盒同步重定向

    def test_relocate_after_commit_skips_in_place_sessions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        # 非草稿前缀（edit / --output 定址 / 已归位）：原地生效，返回 None
        rooted = tmp_path / "demo-package"
        rooted.mkdir()
        (rooted / "agent_eval.yaml").write_text(MANIFEST, encoding="utf-8")
        no_rebind = SimpleNamespace(
            server=SimpleNamespace(root=rooted),
            relocate_root=lambda p: pytest.fail("原地会话不得重定向"),
        )
        from agent_eval.cli.cmds.workbench_agent import _relocate_after_commit

        assert _relocate_after_commit(no_rebind) is None
        # 草稿区但清单未落盘（防御：理论不可达）——留给会话末 finalize
        bare = self._draft(tmp_path, "agent-eval-pkg-aa11")
        assert (
            _relocate_after_commit(
                SimpleNamespace(server=SimpleNamespace(root=bare), relocate_root=pytest.fail)
            )
            is None
        )
        assert bare.exists()

    def test_relocate_after_commit_collision_keeps_draft(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        draft = self._draft(tmp_path)
        (draft / "agent_eval.yaml").write_text(
            "package:\n  id: study-trip\n  scenario: travel\n", encoding="utf-8"
        )
        (tmp_path / "study-trip-package").mkdir()  # 落点已被占
        agent = SimpleNamespace(
            server=SimpleNamespace(root=draft),
            relocate_root=lambda p: pytest.fail("撞名不得重定向"),
        )

        from agent_eval.cli.cmds.workbench_agent import _relocate_after_commit

        assert _relocate_after_commit(agent) is None
        assert draft.exists()  # 包留草稿位不打断会话——会话末 finalize 兜底
        assert "已存在" in capsys.readouterr().out

    def test_repl_continues_on_relocated_package_after_landing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """v4.9 核心验收：确认落盘即归位；同一会话可继续自然语言修改已归位的包。"""
        from agent_eval.cli.cmds import workbench_agent as sa

        monkeypatch.chdir(tmp_path)
        draft = self._draft(tmp_path)
        agent = WorkbenchAgent(draft, log_dir=tmp_path / "log")

        def fake_run_turn(agent_: Any, text: str, *, confirm_fn: Any, on_event: Any = None) -> Any:
            root = agent_.server.root
            if not (root / "agent_eval.yaml").exists():
                (root / "agent_eval.yaml").write_text(
                    "package:\n  id: study-trip\n  scenario: travel\n", encoding="utf-8"
                )
                return TurnResult(
                    reply="已生成",
                    diff="d",
                    staged=True,
                    committed=True,
                    committed_files=["A agent_eval.yaml"],
                )
            (root / "rules").mkdir(exist_ok=True)  # 第二轮写操作落在当前沙盒根
            (root / "rules" / "late.yaml").write_text("rules: []\n", encoding="utf-8")
            return TurnResult(
                reply="已补充",
                diff="d",
                staged=True,
                committed=True,
                committed_files=["A rules/late.yaml"],
            )

        monkeypatch.setattr("agent_eval.agent.workbench.agent.run_turn", fake_run_turn)
        inputs = iter(["补一条规则", ""])
        monkeypatch.setattr(sa, "ask", lambda prompt: next(inputs))
        sa._session(agent, "创建研学包")

        final = tmp_path / "study-trip-package"
        assert (final / "agent_eval.yaml").is_file()  # 首轮确认后包立即可见（不再等会话结束）
        assert not draft.exists()
        assert (final / "rules" / "late.yaml").is_file()  # 第二轮写进已归位的包
        assert agent.server.root == final

    def test_session_end_rename_sync_after_landing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """归位后自然语言改包名：目录名在会话末按最终清单 id 同步（finalize 兜底语义）。"""
        from agent_eval.cli.cmds import workbench_agent as sa

        monkeypatch.setattr(sa, "_guard_llm_ready", lambda: None)
        monkeypatch.chdir(tmp_path)

        def fake_run_turn(agent_: Any, text: str, *, confirm_fn: Any, on_event: Any = None) -> Any:
            manifest = agent_.server.root / "agent_eval.yaml"
            pid = "study-trip" if not manifest.exists() else "trip-v2"
            manifest.write_text(f"package:\n  id: {pid}\n  scenario: travel\n", encoding="utf-8")
            return TurnResult(
                reply="ok",
                diff="d",
                staged=True,
                committed=True,
                committed_files=["M agent_eval.yaml"],
            )

        monkeypatch.setattr("agent_eval.agent.workbench.agent.run_turn", fake_run_turn)
        inputs = iter(["把包名改成 trip-v2", ""])
        monkeypatch.setattr(sa, "ask", lambda prompt: next(inputs))
        root = sa.agent_new_package(
            ref=None, output=None, instruction="创建", yes=False, trust_agent=False
        )
        assert root == tmp_path / "trip-v2-package"
        assert (root / "agent_eval.yaml").is_file()
        assert not (tmp_path / "study-trip-package").exists()  # 首归位目录已按新名同步
        assert not any(p.name.startswith("agent-eval-pkg-") for p in tmp_path.rglob("*"))

    def test_finalize_silent_when_already_landed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        final = tmp_path / "demo-package"
        final.mkdir()
        (final / "agent_eval.yaml").write_text(MANIFEST, encoding="utf-8")  # id: demo
        from agent_eval.cli.cmds.workbench_agent import _finalize_new_package

        assert _finalize_new_package(final, movable=True) == final
        assert "已保存" not in capsys.readouterr().out  # 归位提示已在落盘时刻给出，不重复


# ── 流式渲染（claude code 式工作过程直播） ──────────────────────────────


class TestStreamRender:
    def test_emitter_streams_tokens_and_tools(self, capsys) -> None:
        from agent_eval.cli.console.agent_stream import make_stream_emitter as _make_stream_emitter
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
        from agent_eval.cli.console.agent_stream import make_stream_emitter as _make_stream_emitter
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
        from agent_eval.cli.console.agent_stream import make_stream_emitter as _make_stream_emitter
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
        from agent_eval.cli.console.agent_stream import make_stream_emitter as _make_stream_emitter
        from agent_eval.cli.console.output import set_output_format

        set_output_format("text")
        emit, finish = _make_stream_emitter()
        emit({"type": "tool_args", "name": "write_file", "delta": 100})
        emit({"type": "tool_start", "name": "write_file", "args": {}})
        finish()
        out = capsys.readouterr().out
        assert "🔧 write_file" in out and "⏳" not in out and "\r" not in out

    def test_emitter_trims_gap_before_tool_line(self, capsys) -> None:
        # 实测反馈：正文流段尾换行在工具行前回收——工具行紧邻正文不留空隙；
        # 同模式续写时挂账换行补写，段落间隔保留
        from agent_eval.cli.console.agent_stream import make_stream_emitter as _make_stream_emitter
        from agent_eval.cli.console.output import set_output_format

        set_output_format("text")
        emit, finish = _make_stream_emitter()
        emit({"type": "token", "text": "第一段\n\n"})
        emit({"type": "token", "text": "第二段结束。\n\n\n"})
        emit({"type": "tool_start", "name": "search_content", "args": {}})
        finish()
        out = capsys.readouterr().out
        assert "第一段\n\n第二段" in out  # 段落间隔保留
        assert "第二段结束。\n  🔧 search_content" in out  # 工具行紧邻（仅一个换行），无空行

    def test_emitter_tool_args_starts_own_line(self, capsys) -> None:
        # 正文未收尾时 tool_args 先收行再显进度（\r 不得回写覆盖正文行）——TTY 语义，
        # 非 TTY 只验证事件链不崩且工具行正常
        from agent_eval.cli.console.agent_stream import make_stream_emitter as _make_stream_emitter
        from agent_eval.cli.console.output import set_output_format

        set_output_format("text")
        emit, finish = _make_stream_emitter()
        emit({"type": "token", "text": "正文进行中"})
        emit({"type": "tool_args", "name": "write_file", "delta": 10})
        emit({"type": "tool_start", "name": "write_file", "args": {"path": "a.yaml"}})
        finish()
        out = capsys.readouterr().out
        assert "正文进行中" in out and "🔧 write_file · a.yaml" in out

    def test_emitter_tty_renders_markdown_lite(self, capsys, monkeypatch) -> None:
        # TTY 下正文行缓冲经 markdown-lite 渲染：markdown 标记不再裸奔
        import re as _re
        import sys as _sys

        from agent_eval.cli.console.agent_stream import make_stream_emitter as _make_stream_emitter
        from agent_eval.cli.console.output import set_output_format

        set_output_format("text")

        class _Tty:
            def __init__(self, inner: Any) -> None:
                self._inner = inner

            def isatty(self) -> bool:
                return True

            def __getattr__(self, name: str) -> Any:
                return getattr(self._inner, name)

        monkeypatch.setattr(_sys, "stdout", _Tty(_sys.stdout))
        emit, finish = _make_stream_emitter()
        emit(
            {
                "type": "token",
                "text": "## 执行摘要\n\n**结论**: 收到 `{}`\n- [x] 探测完成\n",
            }
        )
        finish()
        raw = capsys.readouterr().out
        out = _re.sub(r"\x1b\[[0-9;]*m", "", raw)  # 去 ANSI 后断言纯文本形态
        assert "## " not in out and "**" not in out  # 标记被转换
        assert "执行摘要" in out and "结论" in out and "✓ 探测完成" in out

    def test_emitter_tty_keeps_paragraph_gap_and_buffers_partial_line(
        self, capsys, monkeypatch
    ) -> None:
        # 行缓冲语义：完整行才落笔（部分行挂起），段落间隔保留，工具行紧邻
        import sys as _sys

        from agent_eval.cli.console.agent_stream import make_stream_emitter as _make_stream_emitter
        from agent_eval.cli.console.output import set_output_format

        set_output_format("text")

        class _Tty:
            def __init__(self, inner: Any) -> None:
                self._inner = inner

            def isatty(self) -> bool:
                return True

            def __getattr__(self, name: str) -> Any:
                return getattr(self._inner, name)

        monkeypatch.setattr(_sys, "stdout", _Tty(_sys.stdout))
        emit, finish = _make_stream_emitter()
        emit({"type": "token", "text": "第一段\n\n第二段 "})
        first = capsys.readouterr().out
        assert "第二段" not in first  # 部分行挂起（未收到换行）
        emit({"type": "tool_start", "name": "request", "args": {}})
        finish()
        out = first + capsys.readouterr().out
        assert "第一段\n\n第二段" in out  # 段落间隔保留
        assert "第二段" in out and "🔧 request" in out  # 部分行兜底落笔 + 工具行

    def test_emitter_renders_todo_list_with_dedupe(self, capsys) -> None:
        from agent_eval.cli.console.agent_stream import make_stream_emitter as _make_stream_emitter
        from agent_eval.cli.console.output import set_output_format

        set_output_format("text")
        emit, finish = _make_stream_emitter()
        todos = [
            {"content": "探测接口", "status": "completed"},
            {"content": "修正头", "status": "in_progress"},
            {"content": "重放断言", "status": "pending"},
        ]
        emit({"type": "todos", "todos": todos})
        emit({"type": "todos", "todos": list(todos)})  # 与上次相同——去重不重画
        emit(
            {
                "type": "todos",
                "todos": [
                    {"content": "探测接口", "status": "completed"},
                    {"content": "修正头", "status": "completed"},
                ],
            }
        )
        finish()
        out = capsys.readouterr().out
        assert out.count("任务清单") == 2  # 首次 + 变化后；重复事件不重画
        assert "✓ 探测接口" in out and "▶ 修正头" in out and "○ 重放断言" in out
        assert "任务清单 2/2" in out  # 完成进度计数


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
        cfg = WorkbenchAgentConfig(probe_budgets={"request": 1}, probe_timeout_s=2.5)
        agent = WorkbenchAgent(tmp_path, config=cfg, log_dir=tmp_path / "log")
        assert agent.probe.budgets == {"request": 1}
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
        cfg = WorkbenchAgentConfig(probe_budgets={"request": 1}, probe_timeout_s=2.5)
        agent = WorkbenchAgent(tmp_path, config=cfg, log_dir=tmp_path / "log")
        assert agent.probe.budgets == {"request": 1}
        assert agent.probe.timeout_s == 2.5

    def test_resume_injection_respects_config(self, tmp_path: Path) -> None:
        # 续作注入条数/截断由 config 决定（原模块常量迁入）
        cfg = WorkbenchAgentConfig(resume_max_entries=1, resume_max_chars=10)
        dialogue = [{"role": "user", "text": "x" * 50}, {"role": "user", "text": "y"}]
        msgs = dict(WorkbenchAgent.__dict__) and _resume_messages(dialogue, cfg)
        joined = "\n".join(m[1] for m in msgs)
        assert "y" in joined and "xxx…" not in joined


class TestPromptAssets:
    """提示词资产——包发现引导（list_packages / scenario edit / 换新 id）随资产走。"""

    def test_domain_segment_guides_discovery_and_edit(self) -> None:
        from agent_eval.agent.workbench.prompts import load_prompts

        segment = load_prompts()["domain_segments"]["scenario_package"]
        assert "list_packages" in segment  # 「有哪些包」第一查询入口
        assert "scenario edit" in segment  # project/local 首选原位编辑
        assert "换新" in segment and "scenario/id" in segment  # fork 归位冲突避坑
        assert "read_reference" in segment

    def test_intro_mentions_package_listing(self) -> None:
        from agent_eval.agent.workbench.prompts import load_prompts

        intro = str(load_prompts()["intro"])  # intro 是多行字符串而非 mapping
        assert "有哪些评测场景包" in intro


class TestSessionMachine:
    """§6.7 会话机：salvage 保现场 / 自动分段续跑 / 预算缰绳（D-WB-3/4/5）。"""

    @staticmethod
    def _recursion_exc() -> type[BaseException]:
        from agent_eval.agent.workbench.messages import _GraphRecursionError

        if _GraphRecursionError is None:  # langgraph 缺席（纯单测 CI）
            pytest.skip("langgraph 未安装（[agent] extra 缺席）")
        return _GraphRecursionError

    def test_recursion_limit_auto_continues_next_segment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # P1 自动分段：撞线不再交还用户，自动开新段续跑（同一对话/暂存）
        exc = self._recursion_exc()
        calls: list[list[Any]] = []
        fake, replay_calls = _replay([_write_valid])
        events: list[dict[str, Any]] = []

        async def segmented(
            self: WorkbenchAgent, messages: list[Any], *, on_event: Any = None
        ) -> dict[str, Any]:
            calls.append(list(messages))
            if len(calls) == 1:
                raise exc("recursion limit hit")
            return await fake(self, messages, on_event=on_event)

        monkeypatch.setattr(WorkbenchAgent, "_invoke", segmented)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        result = asyncio.run(
            agent.turn("生成包", confirm_fn=lambda r, d: True, on_event=events.append)
        )
        assert result.committed
        checkpoint = [e for e in events if e.get("name") == "checkpoint"]
        assert checkpoint and checkpoint[0]["segment"] == 2  # 第 2 段续跑

    def test_segment_limit_pauses_with_scene(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 分段耗尽 = 暂停（进度完整），不是失败回滚
        exc = self._recursion_exc()

        async def always_limit(
            self: WorkbenchAgent, messages: list[Any], *, on_event: Any = None
        ) -> dict[str, Any]:
            await self.server.write_file("rules/a.yaml", RULES)
            raise exc("recursion limit hit")

        monkeypatch.setattr(WorkbenchAgent, "_invoke", always_limit)
        agent = WorkbenchAgent(
            tmp_path, config=WorkbenchAgentConfig(max_segments=2), log_dir=tmp_path / "log"
        )
        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))
        assert result.aborted_reason == "segment_limit"
        assert result.staged and agent.server.staging  # 现场保留
        assert not (tmp_path / "rules").exists()  # 磁盘仍未见未确认内容

    def test_transient_error_keeps_scene_and_history(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 瞬时错误（LLM 断流）= 暂停：上抛宿主呈现，暂存与历史保留可重试
        async def flaky(
            self: WorkbenchAgent, messages: list[Any], *, on_event: Any = None
        ) -> dict[str, Any]:
            await self.server.write_file("rules/a.yaml", RULES)
            raise RuntimeError("LLM 网关断流")

        monkeypatch.setattr(WorkbenchAgent, "_invoke", flaky)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        with pytest.raises(RuntimeError, match="断流"):
            asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))
        assert agent.server.staging
        assert any(m[1] == "生成包" for m in agent._messages if isinstance(m, tuple))

    def test_budget_exceeded_pauses(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # P2 预算缰绳：BudgetGuard 到界 = 暂停交还（不是失败）
        from agent_eval.core.exceptions import BudgetExceededError

        async def overspend(
            self: WorkbenchAgent, messages: list[Any], *, on_event: Any = None
        ) -> dict[str, Any]:
            raise BudgetExceededError("超预算")

        monkeypatch.setattr(WorkbenchAgent, "_invoke", overspend)
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))
        assert result.aborted_reason == "budget_exceeded"

    def test_budget_guard_wired_when_configured(self, tmp_path: Path) -> None:
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        assert agent._budget_guard is None  # 缺省不启用
        priced = WorkbenchAgent(
            tmp_path, config=WorkbenchAgentConfig(budget_usd=0.5), log_dir=tmp_path / "log"
        )
        assert priced._budget_guard is not None

    def test_salvage_repairs_orphan_tool_calls(self, tmp_path: Path) -> None:
        # P0：孤儿 tool_call 合成失败 ToolMessage（当年截断历史的真实原因）
        ai = SimpleNamespace(type="ai", content="", tool_calls=[{"id": "c1", "name": "write_file"}])
        repaired = repair_orphan_tool_calls([ai])
        assert len(repaired) == 2
        orphan = repaired[1]
        assert getattr(orphan, "tool_call_id", "") == "c1"
        assert "打断" in str(getattr(orphan, "content", ""))
        # 已配对的调用不重复合成
        paired = [
            ai,
            SimpleNamespace(type="tool", content="ok", tool_call_id="c1", name="write_file"),
        ]
        assert repair_orphan_tool_calls(paired) == paired

    def test_salvage_pulls_checkpoint_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 撞线后 aget_state 捞半途消息（含输入全线程），孤儿修复后并入宿主历史
        exc = self._recursion_exc()
        half_way = [
            SimpleNamespace(type="human", content="生成包"),
            SimpleNamespace(type="ai", content="", tool_calls=[{"id": "c9", "name": "request"}]),
        ]

        class _FakeGraph:
            async def aget_state(self, config: dict[str, Any]) -> Any:
                return SimpleNamespace(values={"messages": list(half_way)})

        async def boom(
            self: WorkbenchAgent, messages: list[Any], *, on_event: Any = None
        ) -> dict[str, Any]:
            self._graph = _FakeGraph()  # 模拟已组装图（aget_state 可用）
            self._last_thread_id = "wb-1"  # 真实 _invoke 的副产物（thread_id 已发）
            raise exc("limit")

        monkeypatch.setattr(WorkbenchAgent, "_invoke", boom)
        agent = WorkbenchAgent(
            tmp_path, config=WorkbenchAgentConfig(max_segments=1), log_dir=tmp_path / "log"
        )
        result = asyncio.run(agent.turn("生成包", confirm_fn=lambda r, d: True))
        assert result.aborted_reason == "segment_limit"  # max_segments=1：撞线即暂停
        assert len(agent._messages) == 3  # human + ai + 合成的失败 ToolMessage
        assert getattr(agent._messages[-1], "tool_call_id", "") == "c9"


class TestExecutionDomainAssembly:
    """执行域装配回归（Sprint 14b C7，arch/15 v4.12 §6.10）。"""

    @staticmethod
    def _exec_outcome():
        from agent_eval.cli.pipeline_core import PipelineOutcome

        return PipelineOutcome(
            stage="done",
            exit_code=0,
            run_id="20260101_000000",
            run_dir="/ws/runs/20260101_000000",
            metrics={"m:reward": 0.9},
            total_samples=2,
            gate={"mode": "off", "enabled": False, "passed": True},
            upload_receipt={"enabled": False},
            payload={"total": 2, "succeeded": 2},
            result=SimpleNamespace(report=SimpleNamespace(failure_breakdown={"safety": 1})),
        )

    def test_execution_server_assembles_five_tools(self, tmp_path: Path) -> None:
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        names = {t.name for t in agent.execution.to_langchain_tools()}
        assert names == {
            "run_evaluation",
            "list_eval_targets",
            "list_runs",
            "show_run",
            "upload_run",
        }
        assert {s.name for s in agent.execution.TOOL_SPECS} == names  # 面单一致

    def test_describe_tools_includes_execution_domain(self, tmp_path: Path) -> None:
        # 三 server 展平：包域 + 探测 + 执行域同进 {tools} 段
        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        described = agent._describe_tools()
        assert "run_evaluation" in described
        assert "list_eval_targets" in described
        assert "upload_run" in described

    def test_config_field_set_unchanged(self) -> None:
        # §6.7 回归：WorkbenchAgentConfig 零改动——执行域装配走构造 kwarg
        # （render_bridge）而非扩配置；字段集漂移 = 扩展机制失效信号
        import dataclasses

        assert {f.name for f in dataclasses.fields(WorkbenchAgentConfig)} == {
            "max_turns",
            "max_fix_rounds",
            "max_segments",
            "budget_usd",
            "max_dialogue_entries",
            "resume_max_entries",
            "resume_max_chars",
            "probe_budgets",
            "probe_timeout_s",
        }

    def test_interrupt_active_two_states(self, tmp_path: Path) -> None:
        import threading

        from agent_eval.cli.console.exec_bridge import ExecutionRenderBridge

        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        assert agent.interrupt_active_execution() is False  # 无活跃执行

        bridge = ExecutionRenderBridge(None)
        agent.bind_render_bridge(bridge)
        agent.execution.ctx.active_event = threading.Event()
        assert agent.interrupt_active_execution() is True  # 置位 + 封缄
        assert agent.execution.ctx.active_event.is_set()
        assert bridge._sealed  # 失联 worker 线程静音

    def test_new_turn_does_not_reset_active_event(self, tmp_path: Path) -> None:
        # 生命周期约定：active_event 归 run_evaluation，不随 REPL 换轮复位
        import threading

        agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
        event = threading.Event()
        agent.execution.ctx.active_event = event
        agent.execution.new_turn()
        assert agent.execution.ctx.active_event is event

    def test_execution_bypasses_session_budget(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """预算豁免回归：执行评测不消耗会话预算（BudgetGuard 仅挂 on_llm_end）。

        双保险断言：①空转 pipeline_core 走完整 run_evaluation 后 spent_usd 不变；
        ②结构性断言 PipelineParams 无 budget 字段（执行参数进不了预算通道）。
        """
        import dataclasses
        import threading

        import agent_eval.agent.workbench.execution.run_eval as run_eval_mod
        from agent_eval.cli.pipeline_core import PipelineParams

        assert not {f.name for f in dataclasses.fields(PipelineParams)} & {
            "budget_usd",
            "budget",
        }  # 结构性：执行参数无预算字段

        cfg = WorkbenchAgentConfig(budget_usd=1.0)
        agent = WorkbenchAgent(tmp_path, config=cfg, log_dir=tmp_path / "log")
        assert agent._budget_guard is not None and agent._budget_guard.spent_usd == 0

        core_calls: list[str] = []

        def fake_core(params, *, progress, cancel_event, credential_filler):
            core_calls.append("core")
            assert isinstance(cancel_event, threading.Event)
            return self._exec_outcome()

        monkeypatch.setattr(run_eval_mod, "pipeline_core", fake_core)

        async def ask_fn(question, *, options=None, secret=False):
            return "确认执行"

        agent.execution.ctx.ask_fn = ask_fn  # 与 bind_render_bridge 同风格：ctx 公开名直写
        result = asyncio.run(agent.execution.run_evaluation(package="demo-pkg"))
        assert result["status"] == "done"
        assert core_calls == ["core"]
        assert agent._budget_guard.spent_usd == 0  # 会话预算分文未动
