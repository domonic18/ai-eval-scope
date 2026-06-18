"""JudgeOrchestrator 视觉路径测试 — judge(images=...) 分支。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from agent_eval.llm.judge.orchestrator import JudgeOrchestrator
from agent_eval.llm.judge.structured_output import StructuredOutputParser
from agent_eval.llm.judge.template_manager import TemplateManager
from agent_eval.llm.models import LLMResponse


def _setup_vision_template(prompts_dir: Path) -> None:
    """创建视觉测试模板（num_samples=1）。"""
    template_data = {
        "template_id": "test_vision",
        "name": "视觉测试",
        "dimensions": [
            {"dim_id": "layout", "name": "排版", "description": "排版", "weight": 1.0},
        ],
        "system_prompt": "你是视觉评审。",
        "user_prompt_template": "评估：{{ title }} {{ num_documents }}",
        "output_schema": {
            "type": "object",
            "properties": {"layout": {"type": "number"}},
            "required": ["layout"],
        },
        "temperature": 0.0,
        "seed": 42,
        "num_samples": 1,
    }
    (prompts_dir / "test_vision.yaml").write_text(
        yaml.dump(template_data, allow_unicode=True), encoding="utf-8"
    )


def _make_client(provider_name="kimi_vision", model="kimi-2.6") -> MagicMock:
    """构造 mock LLM client。"""
    client = MagicMock()
    client.provider_info = MagicMock()
    client.provider_info.name = provider_name
    client.provider_info.model = model
    return client


class TestJudgeOrchestratorVision:
    """JudgeOrchestrator.judge(images=...) 测试。"""

    def test_vision_calls_chat_with_vision(self, tmp_path: Path) -> None:
        """images 非空时调用 chat_with_vision 而非 chat。"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        _setup_vision_template(prompts_dir)

        client = _make_client()
        client.chat_with_vision.return_value = LLMResponse(
            content='{"layout": 8.0}', provider_name="kimi_vision", model="kimi-2.6"
        )
        pool = MagicMock()
        pool.get.return_value = client

        tm = TemplateManager(prompts_dir)
        tm.load_all()
        orch = JudgeOrchestrator(
            pool=pool, template_manager=tm, stability=MagicMock(), parser=StructuredOutputParser()
        )
        # stability 真实调用以拿到 num_samples=1
        from agent_eval.llm.judge.stability import StabilityController

        orch.stability = StabilityController()

        scores, record = orch.judge(
            constraint_id="vision.quality",
            sample_id="s1",
            template_id="test_vision",
            variables={"title": "T", "num_documents": 1},
            evidence_dir=tmp_path / "ev",
            images=["data:image/png;base64,QUJD"],
        )

        # chat_with_vision 被调用，chat 未被调用
        client.chat_with_vision.assert_called_once()
        client.chat.assert_not_called()
        # images 透传（messages 与 images 均为位置参数）
        args, kwargs = client.chat_with_vision.call_args
        assert args[1] == ["data:image/png;base64,QUJD"]

        # 得分正确
        assert scores["layout"] == 8.0
        # image_hashes 填充（溯源）
        assert len(record.image_hashes) == 1

    def test_text_calls_chat(self, tmp_path: Path) -> None:
        """无 images 时仍走 chat（回归）。"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        _setup_vision_template(prompts_dir)

        client = _make_client()
        client.chat.return_value = LLMResponse(
            content='{"layout": 7.0}', provider_name="ds", model="m"
        )
        pool = MagicMock()
        pool.get.return_value = client

        tm = TemplateManager(prompts_dir)
        tm.load_all()
        from agent_eval.llm.judge.stability import StabilityController

        orch = JudgeOrchestrator(
            pool=pool,
            template_manager=tm,
            stability=StabilityController(),
            parser=StructuredOutputParser(),
        )

        orch.judge(
            constraint_id="c1",
            sample_id="s1",
            template_id="test_vision",
            variables={"title": "T", "num_documents": 1},
            evidence_dir=tmp_path / "ev",
            # 无 images
        )

        client.chat.assert_called_once()
        client.chat_with_vision.assert_not_called()

    def test_image_hashes_differ_by_content(self, tmp_path: Path) -> None:
        """不同图片内容产生不同 image_hashes。"""
        from agent_eval.llm.judge.orchestrator import _hash_images

        h1 = _hash_images(["data:image/png;base64,AAA"])
        h2 = _hash_images(["data:image/png;base64,BBB"])
        assert h1 != h2
        assert len(h1[0]) == 16
