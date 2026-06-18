"""TemplateManager 测试 — 模板加载与渲染。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_eval.core.exceptions import LLMError
from agent_eval.llm.judge.template_manager import (
    JudgeDimension,
    JudgeTemplate,
    TemplateManager,
)


def _write_template(path: Path, data: dict) -> None:
    """写入 YAML 模板文件。"""
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")


SAMPLE_TEMPLATE = {
    "template_id": "test_judge",
    "name": "测试评审模板",
    "dimensions": [
        {
            "dim_id": "clarity",
            "name": "清晰度",
            "description": "内容是否清晰易懂",
            "weight": 0.6,
            "score_range": [0.0, 10.0],
        },
        {
            "dim_id": "depth",
            "name": "深度",
            "description": "内容深度",
            "weight": 0.4,
        },
    ],
    "system_prompt": "你是一个专业的课件评审专家。",
    "user_prompt_template": "请评审以下课件内容：\n\n标题：{{ title }}\n内容：{{ content }}",
    "output_schema": {
        "type": "object",
        "properties": {
            "clarity": {"type": "number"},
            "depth": {"type": "number"},
        },
        "required": ["clarity", "depth"],
    },
    "temperature": 0.0,
    "seed": 42,
    "num_samples": 3,
}


class TestJudgeDimension:
    """JudgeDimension 数据类测试。"""

    def test_defaults(self) -> None:
        dim = JudgeDimension(dim_id="x", name="X", description="D")
        assert dim.weight == 1.0
        assert dim.score_range == (0.0, 10.0)


class TestJudgeTemplate:
    """JudgeTemplate 数据类测试。"""

    def test_defaults(self) -> None:
        t = JudgeTemplate(template_id="t1", name="T1")
        assert t.dimensions == []
        assert t.output_schema == {}
        assert t.temperature == 0.0
        assert t.seed == 42
        assert t.num_samples == 3


class TestTemplateManager:
    """TemplateManager 测试。"""

    def test_load_all(self, prompts_dir: Path) -> None:
        """加载目录下所有模板。"""
        _write_template(prompts_dir / "test_judge.yaml", SAMPLE_TEMPLATE)
        mgr = TemplateManager(prompts_dir)
        mgr.load_all()
        assert "test_judge" in mgr.template_ids

    def test_load_yml_extension(self, prompts_dir: Path) -> None:
        """支持 .yml 扩展名。"""
        _write_template(
            prompts_dir / "other.yml",
            {
                "template_id": "other",
                "name": "Other",
            },
        )
        mgr = TemplateManager(prompts_dir)
        mgr.load_all()
        assert "other" in mgr.template_ids

    def test_get_existing(self, prompts_dir: Path) -> None:
        """获取已加载的模板。"""
        _write_template(prompts_dir / "test_judge.yaml", SAMPLE_TEMPLATE)
        mgr = TemplateManager(prompts_dir)
        mgr.load_all()
        t = mgr.get("test_judge")
        assert t.name == "测试评审模板"
        assert len(t.dimensions) == 2
        assert t.dimensions[0].dim_id == "clarity"
        assert t.dimensions[0].weight == 0.6

    def test_get_missing(self, prompts_dir: Path) -> None:
        """获取不存在的模板抛 LLMError。"""
        mgr = TemplateManager(prompts_dir)
        mgr.load_all()
        with pytest.raises(LLMError, match="未找到 Prompt 模板"):
            mgr.get("nonexistent")

    def test_render_substitution(self, prompts_dir: Path) -> None:
        """Jinja2 变量替换。"""
        _write_template(prompts_dir / "test_judge.yaml", SAMPLE_TEMPLATE)
        mgr = TemplateManager(prompts_dir)
        mgr.load_all()
        sys_prompt, user_prompt = mgr.render(
            "test_judge",
            {"title": "一元一次方程", "content": "解方程 x + 1 = 2"},
        )
        assert sys_prompt == "你是一个专业的课件评审专家。"
        assert "一元一次方程" in user_prompt
        assert "解方程 x + 1 = 2" in user_prompt

    def test_render_missing_variable(self, prompts_dir: Path) -> None:
        """变量缺失时抛 LLMError（StrictUndefined）。"""
        _write_template(prompts_dir / "test_judge.yaml", SAMPLE_TEMPLATE)
        mgr = TemplateManager(prompts_dir)
        mgr.load_all()
        with pytest.raises(LLMError, match="变量缺失"):
            mgr.render("test_judge", {"title": "test"})  # 缺 content

    def test_empty_template_dir(self, tmp_path: Path) -> None:
        """空目录不报错。"""
        mgr = TemplateManager(tmp_path / "nonexistent")
        mgr.load_all()
        assert mgr.template_ids == []

    def test_skip_invalid_yaml(self, prompts_dir: Path) -> None:
        """跳过没有 template_id 的 YAML 文件。"""
        (prompts_dir / "invalid.yaml").write_text("foo: bar\n", encoding="utf-8")
        mgr = TemplateManager(prompts_dir)
        mgr.load_all()
        assert mgr.template_ids == []

    def test_template_preserves_schema(self, prompts_dir: Path) -> None:
        """模板保留 output_schema。"""
        _write_template(prompts_dir / "test_judge.yaml", SAMPLE_TEMPLATE)
        mgr = TemplateManager(prompts_dir)
        mgr.load_all()
        t = mgr.get("test_judge")
        assert "properties" in t.output_schema
        assert "clarity" in t.output_schema["properties"]
