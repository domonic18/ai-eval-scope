"""JudgeOrchestrator 测试 — 完整 judge pipeline。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from agent_eval.core.exceptions import LLMResponseError
from agent_eval.llm.judge.file_prompt_store import FilePromptStore
from agent_eval.llm.judge.orchestrator import JudgeOrchestrator
from agent_eval.llm.judge.structured_output import StructuredOutputParser
from agent_eval.llm.models import LLMResponse, TokenUsage


def _setup_template(prompts_dir: Path, *, num_samples: int = 1) -> None:
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
        "num_samples": num_samples,
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
        mock_client.provider_info.max_tokens = None

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_client

        # 使用真实的 TemplateManager 和 StructuredOutputParser
        tm = FilePromptStore(prompts_dir)
        tm.load_all()
        parser = StructuredOutputParser()

        # Mock StabilityController — 单次采样
        from agent_eval.llm.judge.stability import StabilityController

        stability = StabilityController(num_samples=1)

        orchestrator = JudgeOrchestrator(
            pool=mock_pool,
            prompt_store=tm,
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
        mock_client.provider_info.max_tokens = None

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_client

        tm = FilePromptStore(prompts_dir)
        tm.load_all()
        from agent_eval.llm.judge.stability import StabilityController

        orchestrator = JudgeOrchestrator(
            pool=mock_pool,
            prompt_store=tm,
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
        mock_client.provider_info.max_tokens = None

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_client

        tm = FilePromptStore(prompts_dir)
        tm.load_all()
        from agent_eval.llm.judge.recorder import JudgeRecorder
        from agent_eval.llm.judge.stability import StabilityController

        orchestrator = JudgeOrchestrator(
            pool=mock_pool,
            prompt_store=tm,
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
        _setup_template(prompts_dir, num_samples=3)

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
        mock_client.provider_info.max_tokens = None

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_client

        tm = FilePromptStore(prompts_dir)
        tm.load_all()

        from agent_eval.llm.judge.stability import StabilityController

        orchestrator = JudgeOrchestrator(
            pool=mock_pool,
            prompt_store=tm,
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
        mock_client.provider_info.max_tokens = None

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_client

        tm = FilePromptStore(prompts_dir)
        tm.load_all()

        from agent_eval.llm.judge.stability import StabilityController

        orchestrator = JudgeOrchestrator(
            pool=mock_pool,
            prompt_store=tm,
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


class TestJudgeOrchestratorTracing:
    """JudgeOrchestrator trace 隔离测试。"""

    def test_uses_existing_trace_id_when_provided(self, tmp_path: Path) -> None:
        """传入 trace_id 时，应在外部 trace 下创建 span，而不是新建 trace。"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        _setup_template(prompts_dir)

        mock_client = MagicMock()
        mock_client.chat.return_value = LLMResponse(
            content='{"clarity": 8.0, "depth": 7.0}',
            provider_name="ds",
            model="m",
            usage=TokenUsage(100, 50, 150),
        )
        mock_client.provider_info = MagicMock()
        mock_client.provider_info.name = "ds"
        mock_client.provider_info.model = "m"
        mock_client.provider_info.max_tokens = None

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_client

        tm = FilePromptStore(prompts_dir)
        tm.load_all()
        from agent_eval.llm.judge.stability import StabilityController

        orchestrator = JudgeOrchestrator(
            pool=mock_pool,
            prompt_store=tm,
            stability=StabilityController(num_samples=1),
            parser=StructuredOutputParser(),
        )

        with (
            patch("agent_eval.llm.judge.orchestrator.create_trace") as mock_create_trace,
            patch("agent_eval.llm.judge.orchestrator.create_span") as mock_create_span,
        ):
            mock_fake_span = MagicMock()
            mock_create_span.return_value = mock_fake_span
            orchestrator.judge(
                constraint_id="c1",
                sample_id="s1",
                template_id="test_judge",
                variables={"content": "test"},
                evidence_dir=tmp_path / "ev",
                trace_id="run-trace-123",
            )

        # 不应新建 trace
        mock_create_trace.assert_not_called()
        # 应在指定 trace 下创建 span
        mock_create_span.assert_called_once()
        call_kwargs = mock_create_span.call_args.kwargs
        assert call_kwargs["trace_id"] == "run-trace-123"
        assert call_kwargs["name"] == "judge:c1"

    def test_creates_new_trace_when_trace_id_not_provided(self, tmp_path: Path) -> None:
        """未传入 trace_id 时，向后兼容新建独立 trace。"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        _setup_template(prompts_dir)

        mock_client = MagicMock()
        mock_client.chat.return_value = LLMResponse(
            content='{"clarity": 8.0, "depth": 7.0}',
            provider_name="ds",
            model="m",
            usage=TokenUsage(100, 50, 150),
        )
        mock_client.provider_info = MagicMock()
        mock_client.provider_info.name = "ds"
        mock_client.provider_info.model = "m"
        mock_client.provider_info.max_tokens = None

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_client

        tm = FilePromptStore(prompts_dir)
        tm.load_all()
        from agent_eval.llm.judge.stability import StabilityController

        orchestrator = JudgeOrchestrator(
            pool=mock_pool,
            prompt_store=tm,
            stability=StabilityController(num_samples=1),
            parser=StructuredOutputParser(),
        )

        with (
            patch("agent_eval.llm.judge.orchestrator.create_trace") as mock_create_trace,
            patch("agent_eval.llm.judge.orchestrator.create_span") as mock_create_span,
        ):
            mock_fake_span = MagicMock()
            mock_create_trace.return_value = (mock_fake_span, {"trace_id": "new-trace"})
            orchestrator.judge(
                constraint_id="c1",
                sample_id="s1",
                template_id="test_judge",
                variables={"content": "test"},
                evidence_dir=tmp_path / "ev",
            )

        mock_create_trace.assert_called_once()
        mock_create_span.assert_not_called()


class TestJudgeParseRetryAndFailureEvidence:
    """解析失败重试 + 失败调用证据落盘（run 20260912_111958 契约缺口 #2/#3/#4）。"""

    def _make_client(self, max_tokens: int | None = None) -> MagicMock:
        mock_client = MagicMock()
        mock_client.provider_info = MagicMock()
        mock_client.provider_info.name = "ds"
        mock_client.provider_info.model = "m"
        mock_client.provider_info.max_tokens = max_tokens
        return mock_client

    def _make_orchestrator(self, tmp_path: Path, mock_client: MagicMock) -> JudgeOrchestrator:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        _setup_template(prompts_dir)

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_client
        tm = FilePromptStore(prompts_dir)
        tm.load_all()

        from agent_eval.llm.judge.stability import StabilityController

        return JudgeOrchestrator(
            pool=mock_pool,
            prompt_store=tm,
            stability=StabilityController(num_samples=1),
            parser=StructuredOutputParser(),
        )

    def _judge(self, orchestrator: JudgeOrchestrator, tmp_path: Path) -> None:
        orchestrator.judge(
            constraint_id="c1",
            sample_id="s1",
            template_id="test_judge",
            variables={"content": "test"},
            evidence_dir=tmp_path / "ev",
        )

    def test_parse_retry_recovers(self, tmp_path: Path) -> None:
        """首次输出畸形（如截断半截 JSON）重试后痊愈：chat 调 2 次，结果成功。"""
        mock_client = self._make_client()
        mock_client.chat.side_effect = [
            LLMResponse(content='{"clarity": 8', provider_name="ds", model="m"),
            LLMResponse(content='{"clarity": 8.0, "depth": 7.0}', provider_name="ds", model="m"),
        ]
        orchestrator = self._make_orchestrator(tmp_path, mock_client)

        scores, record = orchestrator.judge(
            constraint_id="c1",
            sample_id="s1",
            template_id="test_judge",
            variables={"content": "test"},
            evidence_dir=tmp_path / "ev",
        )

        assert mock_client.chat.call_count == 2
        assert scores == {"clarity": 8.0, "depth": 7.0}
        assert record.raw_response == '{"clarity": 8.0, "depth": 7.0}'

    def test_parse_retry_exhausted_raises_last_error(self, tmp_path: Path) -> None:
        """重试耗尽抛末次 LLMResponseError：调用 max_retries+1 次。"""
        mock_client = self._make_client()
        mock_client.chat.return_value = LLMResponse(
            content="not json at all", provider_name="ds", model="m"
        )
        orchestrator = self._make_orchestrator(tmp_path, mock_client)

        with pytest.raises(LLMResponseError):
            self._judge(orchestrator, tmp_path)

        assert mock_client.chat.call_count == 4  # 1 次首发 + 3 次重试（默认 max_retries=3）

    def test_failure_evidence_persisted(self, tmp_path: Path) -> None:
        """judge 失败也落证据：judge_*_failed.json 含错误摘要/raw 尾部/生效参数。"""
        mock_client = self._make_client(max_tokens=8192)
        bad = "{" + "x" * 500  # 末次原始响应（畸形形态）
        mock_client.chat.return_value = LLMResponse(
            content=bad,
            provider_name="ds",
            model="m",
            usage=TokenUsage(100, 50, 150),
        )
        orchestrator = self._make_orchestrator(tmp_path, mock_client)
        evidence_dir = tmp_path / "ev"

        with pytest.raises(LLMResponseError):
            self._judge(orchestrator, tmp_path)

        files = list(evidence_dir.glob("judge_*_failed.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert data["error"].startswith("LLMResponseError")
        assert data["raw_response"] == bad
        assert data["max_tokens"] == 8192  # 生效参数随失败证据透出
        assert data["num_samples"] == 4  # 已收到原始响应的调用次数
        assert data["token_usage"]["total_tokens"] == 600  # 失败尝试的消耗同样累计
