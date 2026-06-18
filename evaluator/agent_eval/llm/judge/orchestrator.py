"""JudgeOrchestrator — LLM Judge 调用编排器。

串联模板渲染、Provider 选择、稳定性控制、溯源记录完整 pipeline。
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from agent_eval.config import JUDGE_ID_DATETIME_FORMAT
from agent_eval.llm.judge.recorder import JudgeRecorder
from agent_eval.llm.judge.stability import StabilityController
from agent_eval.llm.judge.structured_output import StructuredOutputParser
from agent_eval.llm.judge.template_manager import TemplateManager
from agent_eval.llm.models import JudgeRecord, Message, TokenUsage
from agent_eval.llm.pool import ProviderPool
from agent_eval.llm.tracing import create_span, create_trace

logger = structlog.get_logger("judge.orchestrator")


def _hash_images(images: list[str]) -> list[str]:
    """计算图片引用的哈希列表（用于溯源，不含图片本体）。

    data URI 取 base64 数据部分；URL 直接取哈希。
    """
    hashes: list[str] = []
    for img in images:
        payload = img.split(",", 1)[-1] if img.startswith("data:") else img
        hashes.append(hashlib.sha256(payload.encode()).hexdigest()[:16])
    return hashes


def _coerce_score(value: Any) -> float:
    """把 LLM 返回的维度分值规约为 float。

    模板要求维度为 number，但部分 LLM（尤其多模态模型在低内容页上）会自作主张返回
    嵌套对象 `{"score": 8, "issues": [...]}` 或字符串 "8"。此处统一容错：
    - number → float
    - dict → 取其中的 score/value/rating/分 键（递归一层），缺失则 0.0
    - str → 提取首个数字
    - 其他 → 0.0
    规约后裁剪到 [0, 10]（与模板 score_range 对齐）。
    """
    if isinstance(value, bool):  # bool 是 int 子类，先排除
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for k in ("score", "value", "rating", "分", "分数", "得分"):
            if k in value:
                return _coerce_score(value[k])
        return 0.0
    if isinstance(value, str):
        m = re.search(r"-?\d+(?:\.\d+)?", value)
        return float(m.group()) if m else 0.0
    return 0.0


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
        images: list[str] | None = None,
        judge_id_suffix: str | None = None,
        trace_id: str | None = None,
    ) -> tuple[dict[str, Any], JudgeRecord]:
        """执行完整 judge pipeline。

        Args:
            constraint_id: 约束 ID。
            sample_id: 样本 ID。
            template_id: Prompt 模板 ID。
            variables: 模板变量。
            evidence_dir: 证据保存目录。
            provider_name: 指定 Provider 名称。None 使用默认。
            images: 多模态图片引用列表（data URI 或 URL）。非空时走
                chat_with_vision（视觉评估），None 时走普通 chat。
            judge_id_suffix: judge_id 与 evidence 文件名的附加后缀。当同一约束
                在一次评估内被多次调用（如逐文档视觉评估）时必填，否则时间戳到秒
                的 judge_id 会碰撞、evidence 文件互相覆盖。
            trace_id: 外层评测运行创建的 Langfuse trace ID。传入时，本次 judge 调用
                会作为该 trace 下的 span，而不是新建 trace。不同评测任务传入不同
                trace_id，即可在 Langfuse 中隔离不同任务的 LLM 调用日志。

        Returns:
            (scores_dict, JudgeRecord) 元组。
        """
        # 1. 获取 Provider
        client = self.pool.get(provider_name)
        provider_info = client.provider_info

        # 2. 渲染模板
        template = self.templates.get(template_id)
        system_prompt, user_prompt = self.templates.render(template_id, variables)

        # 3. Langfuse Trace（v4 API: start_observation）
        # 若外层已传入 trace_id，本次 judge 作为该 trace 下的 span；
        # 否则新建独立 trace（向后兼容，单测/独立调用场景）。
        if trace_id:
            root_span = create_span(
                name=f"judge:{constraint_id}",
                trace_id=trace_id,
                metadata={
                    "sample_id": sample_id,
                    "template_id": template_id,
                    "provider": provider_info.name,
                    "model": provider_info.model,
                },
            )
        else:
            trace_info = create_trace(
                name=f"judge:{constraint_id}",
                metadata={
                    "sample_id": sample_id,
                    "template_id": template_id,
                    "provider": provider_info.name,
                    "model": provider_info.model,
                },
            )
            root_span = trace_info[0] if trace_info else None

        # 4. 采样并记录
        all_raw_responses: list[str] = []
        total_tokens = TokenUsage()

        def single_judge(sample_index: int) -> dict[str, float]:
            messages = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt),
            ]

            # Langfuse Generation — 记录单次 LLM 调用
            generation = None
            if root_span:
                generation = root_span.start_observation(
                    name=f"sample_{sample_index}",
                    as_type="generation",
                    input={
                        "system": system_prompt,
                        "user": user_prompt,
                        **({"num_images": len(images)} if images else {}),
                    },
                    model=f"{provider_info.name}/{provider_info.model}",
                    model_parameters={
                        "temperature": template.temperature,
                        "seed": template.seed + sample_index,
                    },
                )

            if images:
                response = client.chat_with_vision(
                    messages,
                    images,
                    seed=template.seed + sample_index,
                    temperature=template.temperature,
                )
            else:
                response = client.chat(
                    messages,
                    seed=template.seed + sample_index,
                    temperature=template.temperature,
                )

            # Langfuse Generation — 更新输出和 token 用量
            if generation:
                usage_details = {}
                if response.usage:
                    usage_details = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                    }
                generation.update(
                    output=response.content,
                    usage_details=usage_details,
                )
                generation.end()

            all_raw_responses.append(response.content)

            # 累计 token 用量
            if response.usage:
                total_tokens.prompt_tokens += response.usage.prompt_tokens
                total_tokens.completion_tokens += response.usage.completion_tokens
                total_tokens.total_tokens += response.usage.total_tokens

            # 解析结构化输出
            parsed = self.parser.parse(response.content, template.output_schema)
            # 确保维度分数为 float，同时保留 summary 等非维度字段
            result: dict[str, Any] = {}
            for dim in template.dimensions:
                result[dim.dim_id] = _coerce_score(parsed.get(dim.dim_id, 0.0))
            # 保留 summary 等非维度字段（用于可解释性）
            for key in parsed:
                if key not in result:
                    result[key] = parsed[key]
            return result

        # 5. 稳定性控制 — 多次采样（采样次数由模板指定，视觉模板可设 num_samples=1）
        start_time = time.monotonic()
        stable_result = self.stability.evaluate_stable(
            single_judge, template.dimensions, num_samples=template.num_samples
        )
        total_duration_ms = (time.monotonic() - start_time) * 1000

        # 6. 生成 JudgeRecord
        timestamp = datetime.now(tz=UTC).isoformat()
        last_parsed = stable_result.all_samples[-1] if stable_result.all_samples else {}
        summary_text = str(last_parsed.get("summary", ""))
        judge_id = (
            f"judge_{constraint_id}_{datetime.now(tz=UTC).strftime(JUDGE_ID_DATETIME_FORMAT)}"
        )
        if judge_id_suffix:
            # 后缀只允许安全字符，避免污染文件名
            safe_suffix = re.sub(r"[^A-Za-z0-9_.-]", "_", judge_id_suffix)
            judge_id = f"{judge_id}_{safe_suffix}"
        record = JudgeRecord(
            judge_id=judge_id,
            constraint_id=constraint_id,
            sample_id=sample_id,
            provider_name=provider_info.name,
            model=provider_info.model,
            template_id=template_id,
            temperature=template.temperature,
            seed=template.seed,
            raw_response=all_raw_responses[-1] if all_raw_responses else "",
            parsed_scores=last_parsed,
            final_scores=stable_result.scores,
            confidence=stable_result.confidence,
            num_samples=stable_result.num_samples,
            summary=summary_text,
            total_duration_ms=total_duration_ms,
            token_usage=total_tokens,
            timestamp=timestamp,
            image_hashes=_hash_images(images) if images else [],
        )

        # 7. 结束 Langfuse Trace
        if root_span:
            root_span.update(
                output={"scores": stable_result.scores, "confidence": stable_result.confidence},
            )
            root_span.end()

        # 8. 持久化 JudgeRecord
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
