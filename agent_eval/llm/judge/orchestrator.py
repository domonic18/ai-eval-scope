"""JudgeOrchestrator — LLM Judge 调用编排器。

串联模板渲染、Provider 选择、稳定性控制、溯源记录完整 pipeline。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_eval.llm.judge.recorder import JudgeRecorder
from agent_eval.llm.judge.stability import StabilityController
from agent_eval.llm.judge.structured_output import StructuredOutputParser
from agent_eval.llm.judge.template_manager import TemplateManager
from agent_eval.llm.models import JudgeRecord, Message, TokenUsage
from agent_eval.llm.pool import ProviderPool


class JudgeOrchestrator:
    """LLM Judge 调用编排器。

    职责：
    1. 接收评估请求（constraint_id + sample_id + template_id + variables）
    2. 从 ProviderPool 获取指定 Provider
    3. 渲染 Prompt 模板
    4. 调用 StabilityController 进行多次采样
    5. 生成 JudgeRecord 并持久化到 evidence 目录
    6. 返回评估结果
    """

    def __init__(
        self,
        pool: ProviderPool,
        template_manager: TemplateManager,
        stability: StabilityController,
        parser: StructuredOutputParser,
    ) -> None:
        """初始化编排器。

        Args:
            pool: Provider 管理池。
            template_manager: Prompt 模板管理器。
            stability: 稳定性控制器。
            parser: 结构化输出解析器。
        """
        self.pool = pool
        self.templates = template_manager
        self.stability = stability
        self.parser = parser

    def judge(
        self,
        *,
        constraint_id: str,
        sample_id: str,
        template_id: str,
        variables: dict[str, Any],
        evidence_dir: Path,
        provider_name: str | None = None,
    ) -> tuple[dict[str, Any], JudgeRecord]:
        """执行完整 judge pipeline。

        Args:
            constraint_id: 约束 ID。
            sample_id: 样本 ID。
            template_id: Prompt 模板 ID。
            variables: 模板变量。
            evidence_dir: 证据保存目录。
            provider_name: 指定 Provider 名称。None 使用默认。

        Returns:
            (scores_dict, JudgeRecord) 元组。
        """
        # 1. 获取 Provider
        client = self.pool.get(provider_name)
        provider_info = client.provider_info

        # 2. 渲染模板
        template = self.templates.get(template_id)
        system_prompt, user_prompt = self.templates.render(template_id, variables)

        # 3. 采样并记录
        all_raw_responses: list[str] = []
        total_tokens = TokenUsage()

        def single_judge(sample_index: int) -> dict[str, float]:
            messages = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt),
            ]
            response = client.chat(
                messages,
                seed=template.seed + sample_index,
                temperature=template.temperature,
            )
            all_raw_responses.append(response.content)

            # 累计 token 用量
            if response.usage:
                total_tokens.prompt_tokens += response.usage.prompt_tokens
                total_tokens.completion_tokens += response.usage.completion_tokens
                total_tokens.total_tokens += response.usage.total_tokens

            # 解析结构化输出
            parsed = self.parser.parse(response.content, template.output_schema)
            return {dim.dim_id: float(parsed.get(dim.dim_id, 0.0)) for dim in template.dimensions}

        # 4. 稳定性控制 — 多次采样
        start_time = time.monotonic()
        stable_result = self.stability.evaluate_stable(single_judge, template.dimensions)
        total_duration_ms = (time.monotonic() - start_time) * 1000

        # 5. 生成 JudgeRecord
        timestamp = datetime.now(tz=UTC).isoformat()
        record = JudgeRecord(
            judge_id=f"judge_{constraint_id}_{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}",
            constraint_id=constraint_id,
            sample_id=sample_id,
            provider_name=provider_info.name,
            model=provider_info.model,
            template_id=template_id,
            temperature=template.temperature,
            seed=template.seed,
            raw_response=all_raw_responses[-1] if all_raw_responses else "",
            parsed_scores=stable_result.all_samples[-1] if stable_result.all_samples else {},
            final_scores=stable_result.scores,
            confidence=stable_result.confidence,
            num_samples=stable_result.num_samples,
            total_duration_ms=total_duration_ms,
            token_usage=total_tokens,
            timestamp=timestamp,
        )

        # 6. 持久化 JudgeRecord
        JudgeRecorder.save(record, evidence_dir)

        return stable_result.scores, record

    def _build_reason(
        self,
        scores: dict[str, float],
        confidence: dict[str, str],
        template_id: str,
    ) -> str:
        """构建评估原因描述。"""
        template = self.templates.get(template_id)
        parts = []
        for dim in template.dimensions:
            score = scores.get(dim.dim_id, 0.0)
            conf = confidence.get(dim.dim_id, "unknown")
            parts.append(f"{dim.name}: {score:.1f} (置信度: {conf})")
        return "; ".join(parts)
