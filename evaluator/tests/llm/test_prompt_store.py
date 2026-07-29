"""PromptStore / FilePromptStore 单测（Phase 1）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_eval.core.exceptions import LLMError
from agent_eval.llm.judge.file_prompt_store import FilePromptStore
from agent_eval.llm.judge.prompt_store import PromptStore, PromptTemplateSummary


def _write_prompt(d: Path, template_id: str, scenario: str | None = None) -> None:
    content: dict = {
        "template_id": template_id,
        "name": template_id,
        "system_prompt": f"system {template_id}",
        "user_prompt_template": "Hello {{ name }}",
        "dimensions": [{"dim_id": "d1", "name": "维度1"}],
    }
    if scenario:
        content["scenario"] = scenario
    (d / f"{template_id}.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")


class TestFilePromptStore:
    def test_is_prompt_store(self, tmp_path: Path) -> None:
        assert isinstance(FilePromptStore(tmp_path), PromptStore)

    def test_load_and_get(self, tmp_path: Path) -> None:
        _write_prompt(tmp_path, "t1")
        store = FilePromptStore(tmp_path)
        store.load_all()
        assert store.get(None, "t1").template_id == "t1"
        assert "t1" in store.template_ids

    def test_get_missing_raises(self, tmp_path: Path) -> None:
        store = FilePromptStore(tmp_path)
        store.load_all()
        with pytest.raises(LLMError):
            store.get(None, "nope")

    def test_scenario_mismatch_raises(self, tmp_path: Path) -> None:
        _write_prompt(tmp_path, "t1", scenario="courseware")
        store = FilePromptStore(tmp_path)
        store.load_all()
        with pytest.raises(LLMError):
            store.get("code", "t1")  # 模板属 courseware，查 code → 报错

    def test_scenario_none_and_match_ok(self, tmp_path: Path) -> None:
        _write_prompt(tmp_path, "t1", scenario="courseware")
        store = FilePromptStore(tmp_path)
        store.load_all()
        assert store.get(None, "t1").template_id == "t1"  # None 不过滤
        assert store.get("courseware", "t1").template_id == "t1"  # 匹配

    def test_list_and_filter(self, tmp_path: Path) -> None:
        _write_prompt(tmp_path, "t1", scenario="courseware")
        _write_prompt(tmp_path, "t2", scenario="code")
        store = FilePromptStore(tmp_path)
        store.load_all()
        assert {s.template_id for s in store.list()} == {"t1", "t2"}
        assert {s.template_id for s in store.list("courseware")} == {"t1"}
        assert all(isinstance(s, PromptTemplateSummary) for s in store.list())

    def test_render(self, tmp_path: Path) -> None:
        _write_prompt(tmp_path, "t1")
        store = FilePromptStore(tmp_path)
        store.load_all()
        t = store.get(None, "t1")
        system, user = store.render(t, {"name": "world"})
        assert system == "system t1"
        assert user == "Hello world"

    def test_render_missing_var_raises(self, tmp_path: Path) -> None:
        _write_prompt(tmp_path, "t1")
        store = FilePromptStore(tmp_path)
        store.load_all()
        with pytest.raises(LLMError):
            store.render(store.get(None, "t1"), {})  # name 缺失

    def test_nonexistent_dir_empty(self, tmp_path: Path) -> None:
        store = FilePromptStore(tmp_path / "nope")
        store.load_all()  # 不崩，仅 warning
        assert store.template_ids == []
        assert store.list() == []
