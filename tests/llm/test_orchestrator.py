"""JudgeOrchestrator 测试 — 完整 judge pipeline。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from agent_eval.llm.judge.orchestrator import JudgeOrchestrator
from agent_eval.llm.judge.structured_output import StructuredOutputParser
from agent_eval.llm.judge.template_manager import TemplateManager
from agent_eval.llm.models import LLMResponse, TokenUsage


def _setup_template(prompts_dir: Path) -> None:
    """创建测试用模板文件。"""
    template_data = {
        "template_id": "test_judge",
        "name": "测试评审",
        "dimensions": [
            {"dim_id": "clarity", "name": "清晰度", "description": "清晰度评估", "weight": 0.6},
            {"dim_id": "depth", "name": "深度", "description": "深度评估", "weight": 0.4},
        ],
        "system_prompt": "你是一个评审专家。",
        "user_prompt_template": "请评审：{{ content }}",
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
        "num_samples": 1,
    }
    (prompts_dir / "test_judge.yaml").write_text(
        yaml.dump(template_data, allow_unicode=True), encoding="utf-8"
    )


class TestJudgeOrchestrator:
    """JudgeOrchestrator 测试。"""

    def test_full_pipeline(self, tmp_path: Path) -> None:
        """完整 pipeline：模板渲染 → LLM 调用 → 采样 → 记录。"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        _setup_template(prompts_dir)

        # Mock ProviderPool
        mock_client = MagicMock()
        mock_client.chat.return_value = LLMResponse(
            content='{"clarity": 8.0, "depth": 7.0}',
            provider_name="ds_judge",
            model="deepseek-chat",
            usage=TokenUsage(100, 50, 150),
        )
        mock_client.provider_info = MagicMock()
        mock_client.provider_info.name = "ds_judge"
        mock_client.provider_info.model = "deepseek-chat"

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_client

        # 使用真实的 TemplateManager 和 StructuredOutputParser
        tm = TemplateManager(prompts_dir)
        tm.load_all()
        parser = StructuredOutputParser()

        # Mock StabilityController — 单次采样
        from agent_eval.llm.judge.stability import StabilityController
        stability = StabilityController(num_samples=1)

        orchestrator = JudgeOrchestrator(
            pool=mock_pool,
            template_manager=tm,
            stability=stability,
            parser=parser,
        )

        evidence_dir = tmp_path / "evidence"
        scores, record = orchestrator.judge(
            constraint_id="soft.teaching_logic",
            sample_id="sample_01",
            template_id="test_judge",
            variables={"content": "一元一次方程"},
            evidence_dir=evidence_dir,
        )

        # 验证结果
        assert scores["clarity"] == 8.0
        assert scores["depth"] == 7.0
        assert record.constraint_id == "soft.teaching_logic"
        assert record.sample_id == "sample_01"
        assert record.provider_name == "ds_judge"
        assert record.model == "deepseek-chat"
        assert record.num_samples == 1

        # 验证 evidence 文件已生成
        evidence_files = list(evidence_dir.glob("*.json"))
        assert len(evidence_files) == 1

    def test_provider_selection(self, tmp_path: Path) -> None:
        """指定 Provider 名称。"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        _setup_template(prompts_dir)

        mock_client = MagicMock()
        mock_client.chat.return_value = LLMResponse(
            content='{"clarity": 9.0, "depth": 8.0}',
            provider_name="kimi",
            model="kimi-2.6",
        )
        mock_client.provider_info = MagicMock()
        mock_client.provider_info.name = "kimi"
        mock_client.provider_info.model = "kimi-2.6"

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_client

        tm = TemplateManager(prompts_dir)
        tm.load_all()
        from agent_eval.llm.judge.stability import StabilityController
        orchestrator = JudgeOrchestrator(
            pool=mock_pool,
            template_manager=tm,
            stability=StabilityController(num_samples=1),
            parser=StructuredOutputParser(),
        )

        scores, record = orchestrator.judge(
            constraint_id="c1",
            sample_id="s1",
            template_id="test_judge",
            variables={"content": "test"},
            evidence_dir=tmp_path / "ev",
            provider_name="kimi",
        )

        mock_pool.get.assert_called_once_with("kimi")
        assert record.provider_name == "kimi"

    def test_record_persistence(self, tmp_path: Path) -> None:
        """JudgeRecord 正确持久化。"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        _setup_template(prompts_dir)

        mock_client = MagicMock()
        mock_client.chat.return_value = LLMResponse(
            content='{"clarity": 6.0, "depth": 5.0}',
            provider_name="ds",
            model="m",
            usage=TokenUsage(50, 25, 75),
        )
        mock_client.provider_info = MagicMock()
        mock_client.provider_info.name = "ds"
        mock_client.provider_info.model = "m"

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_client

        tm = TemplateManager(prompts_dir)
        tm.load_all()
        from agent_eval.llm.judge.recorder import JudgeRecorder
        from agent_eval.llm.judge.stability import StabilityController

        orchestrator = JudgeOrchestrator(
            pool=mock_pool,
            template_manager=tm,
            stability=StabilityController(num_samples=1),
            parser=StructuredOutputParser(),
        )

        evidence_dir = tmp_path / "ev"
        scores, record = orchestrator.judge(
            constraint_id="c1",
            sample_id="s1",
            template_id="test_judge",
            variables={"content": "test"},
            evidence_dir=evidence_dir,
        )

        # 从文件加载并验证
        record_file = list(evidence_dir.glob("*.json"))[0]
        loaded = JudgeRecorder.load(record_file)
        assert loaded.judge_id == record.judge_id
        assert loaded.provider_name == "ds"
        assert loaded.final_scores["clarity"] == 6.0
        assert loaded.token_usage is not None
        assert loaded.token_usage.total_tokens == 75

    def test_token_usage_accumulation(self, tmp_path: Path) -> None:
        """多次采样累计 token 用量。"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        _setup_template(prompts_dir)

        call_count = 0
        usage_sequence = [
            TokenUsage(100, 50, 150),
            TokenUsage(110, 55, 165),
            TokenUsage(105, 52, 157),
        ]

        def mock_chat(messages, **kwargs):
            nonlocal call_count
            resp = LLMResponse(
                content='{"clarity": 8.0, "depth": 7.0}',
                provider_name="ds",
                model="m",
                usage=usage_sequence[call_count],
            )
            call_count += 1
            return resp

        mock_client = MagicMock()
        mock_client.chat.side_effect = mock_chat
        mock_client.provider_info = MagicMock()
        mock_client.provider_info.name = "ds"
        mock_client.provider_info.model = "m"

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_client

        tm = TemplateManager(prompts_dir)
        tm.load_all()

        from agent_eval.llm.judge.stability import StabilityController
        orchestrator = JudgeOrchestrator(
            pool=mock_pool,
            template_manager=tm,
            stability=StabilityController(num_samples=3),
            parser=StructuredOutputParser(),
        )

        scores, record = orchestrator.judge(
            constraint_id="c1",
            sample_id="s1",
            template_id="test_judge",
            variables={"content": "test"},
            evidence_dir=tmp_path / "ev",
        )

        # 累计 token: 150 + 165 + 157 = 472
        assert record.token_usage is not None
        assert record.token_usage.total_tokens == 472
        assert record.num_samples == 3

    def test_error_in_llm_call(self, tmp_path: Path) -> None:
        """LLM 调用失败时传播异常。"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        _setup_template(prompts_dir)

        mock_client = MagicMock()
        mock_client.chat.side_effect = Exception("API error")
        mock_client.provider_info = MagicMock()
        mock_client.provider_info.name = "ds"
        mock_client.provider_info.model = "m"

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_client

        tm = TemplateManager(prompts_dir)
        tm.load_all()

        from agent_eval.llm.judge.stability import StabilityController
        orchestrator = JudgeOrchestrator(
            pool=mock_pool,
            template_manager=tm,
            stability=StabilityController(num_samples=1),
            parser=StructuredOutputParser(),
        )

        with pytest.raises(Exception, match="API error"):
            orchestrator.judge(
                constraint_id="c1",
                sample_id="s1",
                template_id="test_judge",
                variables={"content": "test"},
                evidence_dir=tmp_path / "ev",
            )
