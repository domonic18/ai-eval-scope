"""PipelineEngine — 评估管线引擎。

编排级联评估流程：Stage1 格式门控 → Stage2 常识检查 → Stage3 质量评估。
支持缓存和短路控制。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from agent_eval.core.types import EvalStatus
from agent_eval.evaluation.aggregator import ScoreAggregator
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.metrics import MetricsCalculator
from agent_eval.evaluation.models import SampleResult, StageResult
from agent_eval.evaluation.registry import EvaluatorRegistry
from agent_eval.evaluation.stage import PipelineStage


@dataclass
class EvaluatorConfig:
    """评估器配置。"""

    name: str  # 评估器 ID，如 "format.response_format"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class StageConfig:
    """单个阶段的配置。"""

    id: str  # "format" | "commonsense" | "quality"
    evaluators: list[EvaluatorConfig] = field(default_factory=list)
    short_circuit_policy: str = "fail_fast"  # "fail_fast" | "continue_all"


@dataclass
class PipelineConfig:
    """管线配置。"""

    stages: list[StageConfig] = field(default_factory=list)
    reward_weights: dict[str, float] = field(default_factory=lambda: {"w3": 1.0, "w4": 1.0})


class PipelineEngine:
    """评估管线引擎 — 编排级联评估流程。

    使用示例:
        engine = PipelineEngine(config, registry, aggregator, metrics_calc)
        report = engine.evaluate_batch(packages, rule_set)
    """

    def __init__(
        self,
        config: PipelineConfig,
        registry: EvaluatorRegistry,
        aggregator: ScoreAggregator | None = None,
        metrics_calculator: MetricsCalculator | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.aggregator = aggregator or ScoreAggregator(
            w3=config.reward_weights.get("w3", 1.0),
            w4=config.reward_weights.get("w4", 1.0),
        )
        self.metrics_calculator = metrics_calculator or MetricsCalculator()
        self.stages: list[PipelineStage] = []
        self._cache: dict[str, SampleResult] = {}
        self._build_stages()

    def _build_stages(self) -> None:
        """根据配置构建级联阶段。"""
        for stage_conf in self.config.stages:
            evaluators: list[BaseEvaluator] = []
            for ev_conf in stage_conf.evaluators:
                try:
                    evaluator = self.registry.create(ev_conf.name, ev_conf.params)
                    evaluators.append(evaluator)
                except Exception as e:
                    # 评估器创建失败时记录但不中断（可能该评估器尚未实现）
                    import structlog

                    logger = structlog.get_logger("pipeline")
                    logger.warning(
                        "评估器创建失败，跳过",
                        evaluator_id=ev_conf.name,
                        error=str(e),
                    )

            self.stages.append(
                PipelineStage(
                    stage_id=stage_conf.id,
                    evaluators=evaluators,
                    short_circuit_policy=stage_conf.short_circuit_policy,
                )
            )

    def evaluate_sample(
        self,
        sample: Any,
        context: dict[str, Any],
    ) -> SampleResult:
        """评估单个样本。

        Args:
            sample: 待评估的样本（ExecutionPackage 或 Path）。
            context: 评估上下文（含约束条件、任务信息等）。

        Returns:
            SampleResult 实例。
        """
        # 1. 缓存检查
        cache_key = self._compute_cache_key(sample, context)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        sample_id = context.get("sample_id", "unknown")
        result = SampleResult(sample_id=sample_id, status=EvalStatus.PASS)

        import time

        total_start = time.monotonic()

        # 2. 逐阶段执行，短路终止
        for stage in self.stages:
            stage_result = stage.execute(sample, context)
            result.stage_results[stage.stage_id] = stage_result

            if not stage_result.gate_passed:
                self._mark_remaining_skipped(result, stage.stage_id)
                break

        # 3. 评分聚合
        score = self.aggregator.aggregate(result)
        result.s_format = score.s_format
        result.s_common = score.s_common
        result.s_soft = score.s_soft
        result.s_pref = score.s_pref
        result.reward = score.reward
        result.total_duration_ms = (time.monotonic() - total_start) * 1000

        # 4. 确定最终状态
        if any(sr.status == EvalStatus.FAIL for sr in result.stage_results.values()):
            result.status = EvalStatus.FAIL

        self._cache[cache_key] = result
        return result

    def evaluate_batch(
        self,
        packages: list[Any],
        rule_set: Any = None,
        *,
        run_id: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> Any:
        """批量评估所有样本。

        Args:
            packages: 样本列表。
            rule_set: 规则集（用于构建上下文）。
            run_id: 运行 ID。
            extra_context: 额外上下文（如 judge_orchestrator、evidence_dir），
                           合并到每个样本的上下文中。

        Returns:
            MetricsReport 实例。
        """
        results: list[SampleResult] = []

        for i, pkg in enumerate(packages):
            context = self._build_context(pkg, rule_set, index=i)
            if extra_context:
                context.update(extra_context)
            results.append(self.evaluate_sample(pkg, context))

        return self.metrics_calculator.compute(results, run_id=run_id)

    def _compute_cache_key(self, sample: Any, context: dict[str, Any]) -> str:
        """计算缓存 Key（基于样本内容 + 规则集版本）。"""
        content = str(sample)
        rule_version = context.get("rule_set_version", "")
        content_str = (
            f"{content}:{rule_version}:{json.dumps(context.get('constraints', {}), sort_keys=True)}"
        )
        return hashlib.sha256(content_str.encode()).hexdigest()

    def _mark_remaining_skipped(self, result: SampleResult, failed_stage_id: str) -> None:
        """将失败阶段之后的阶段标记为 SKIP。"""
        remaining = False
        for stage in self.stages:
            if remaining:
                result.stage_results[stage.stage_id] = StageResult(
                    stage_id=stage.stage_id,
                    status=EvalStatus.SKIP,
                    gate_passed=False,
                )
            if stage.stage_id == failed_stage_id:
                remaining = True

    def _build_context(self, package: Any, rule_set: Any, *, index: int = 0) -> dict[str, Any]:
        """构建评估上下文。"""
        context: dict[str, Any] = {
            "sample_id": f"sample_{index:03d}",
            "constraints": {},
        }

        # 从 ExecutionPackage 提取信息
        if hasattr(package, "task_data") and package.task_data:
            task_data = package.task_data
            context["sample_id"] = task_data.get("id", context["sample_id"])
            context["constraints"] = task_data.get("constraints", {})
            context["task_input"] = task_data.get("input", {})

        # 从 ExecutionPackage 提取目录清单
        if hasattr(package, "directory_manifest") and package.directory_manifest is not None:
            context["directory_manifest"] = package.directory_manifest.model_dump()

        # 从 RuleSet 提取版本
        if rule_set is not None:
            if hasattr(rule_set, "version"):
                context["rule_set_version"] = rule_set.version

        return context

    def clear_cache(self) -> None:
        """清空评估缓存。"""
        self._cache.clear()


def build_default_pipeline(registry: EvaluatorRegistry) -> PipelineEngine:
    """构建默认的三阶段级联管线。

    阶段:
        1. format (fail_fast): 格式门控
        2. commonsense (fail_fast): 常识检查
        3. quality (continue_all): 质量评估
    """
    config = PipelineConfig(
        stages=[
            StageConfig(
                id="format",
                short_circuit_policy="fail_fast",
                evaluators=[
                    EvaluatorConfig("format.response_format", {"allowed_formats": ["md", "html"]}),
                    EvaluatorConfig("format.document_count", {}),
                    EvaluatorConfig("format.structure_compliance", {}),
                    EvaluatorConfig("format.html_validity", {"check_html_only": True}),
                ],
            ),
            StageConfig(
                id="commonsense",
                short_circuit_policy="fail_fast",
                evaluators=[
                    EvaluatorConfig("commonsense.info_accuracy", {}),
                    EvaluatorConfig("commonsense.chronological_order"),
                    EvaluatorConfig("commonsense.logical_consistency"),
                    EvaluatorConfig("commonsense.math_formula"),
                    EvaluatorConfig("commonsense.unit_consistency"),
                ],
            ),
            StageConfig(
                id="quality",
                short_circuit_policy="continue_all",
                evaluators=[
                    # LLM Judge 软约束
                    EvaluatorConfig("soft.teaching_logic", {"template_id": "pedagogical_logic"}),
                    EvaluatorConfig("soft.content_diversity", {"template_id": "content_diversity"}),
                    # LLM Judge 偏好约束
                    EvaluatorConfig("pref.style_preference", {"template_id": "style_preference"}),
                    EvaluatorConfig("pref.depth_preference", {"template_id": "depth_preference"}),
                    EvaluatorConfig(
                        "pref.request_fulfillment", {"template_id": "request_fulfillment"}
                    ),
                ],
            ),
        ],
    )
    return PipelineEngine(config, registry)
