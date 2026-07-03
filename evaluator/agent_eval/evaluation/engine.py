"""PipelineEngine — 评估管线引擎。

编排级联评估流程：Stage1 格式门控 → Stage2 常识检查 → Stage3 质量评估。
支持缓存和短路控制。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from agent_eval.config import PIPELINE_DEFAULTS
from agent_eval.core.types import ConstraintTier, EvalStatus
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
    short_circuit_policy: str = (
        PIPELINE_DEFAULTS.short_circuit_policy
    )  # "fail_fast" | "continue_all"


@dataclass
class PipelineConfig:
    """管线配置。"""

    stages: list[StageConfig] = field(default_factory=list)
    reward_weights: dict[str, float] = field(
        default_factory=lambda: dict(PIPELINE_DEFAULTS.reward_weights)
    )


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
        # 1. 缓存检查（--no-cache 时跳过，强制重新评估）
        cache_key = self._compute_cache_key(sample, context)
        if not context.get("no_cache"):
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        sample_id = context.get("sample_id", "unknown")
        result = SampleResult(
            sample_id=sample_id,
            status=EvalStatus.PASS,
            content_hash=context.get("content_hash"),
        )

        import time

        total_start = time.monotonic()

        # 2. 逐阶段执行，短路终止
        #    仅 HARD_GATE 阶段（如 format）失败时阻塞后续阶段
        #    HARD_SCORE 阶段（如 commonsense）失败只影响本阶段得分，不阻塞后续
        for stage in self.stages:
            stage_result = stage.execute(sample, context)
            result.stage_results[stage.stage_id] = stage_result

            if not stage_result.gate_passed:
                # 判断该阶段是否为 HARD_GATE 类型（通过检查评估器 tier）
                is_hard_gate_stage = any(
                    ev.tier == ConstraintTier.HARD_GATE for ev in stage.evaluators
                )
                if is_hard_gate_stage:
                    # HARD_GATE 失败 → 阻塞所有后续阶段
                    self._mark_remaining_skipped(result, stage.stage_id)
                    break
                # HARD_SCORE 失败 → 标记失败但继续后续阶段

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
        # 视觉评估的截图内容随渲染器/CSS 变化，纳入 cache key 避免命中陈旧结果。
        # 默认空（非视觉场景不影响 key），调用方按需注入 vision_snapshot_hash。
        vision_hash = context.get("vision_snapshot_hash", "")
        llm_signature = context.get("llm_signature", "")
        # 内容指纹（pack 时算）：内容变 → content_hash 变 → cache key 变 → 自动重新评估，
        # 彻底避免「重新打包但命中陈旧缓存」的问题。
        content_hash = context.get("content_hash", "")
        content_str = (
            f"{content}:{rule_version}:{vision_hash}:{llm_signature}:{content_hash}:"
            f"{json.dumps(context.get('constraints', {}), sort_keys=True)}"
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
        # 内容指纹（溯源/版本标记，来自 pack manifest）
        _manifest = getattr(package, "manifest", None)
        if _manifest is not None and getattr(_manifest, "content_hash", None):
            context["content_hash"] = _manifest.content_hash

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


def build_pipeline(registry: EvaluatorRegistry, rule_set: Any) -> PipelineEngine:
    """从规则集构建管线 —— 评估器集合的唯一事实源。

    - stage 顺序与短路策略：取自 ``rule_set.cascade``（``stop_on_fail`` → ``fail_fast``）。
    - 评估器集合：取自 ``rule_set.rules``，``enabled: false`` 的规则跳过，``params`` 注入。
    - 视觉评估器是否纳入：取决于规则集中对应规则 ``enabled``（含 vision.* 即启用）。

    rule_set 为 None 时返回空管线（无评估器）。
    """
    stage_order: list[str] = []
    stage_policy: dict[str, str] = {}
    for st in getattr(rule_set, "cascade", None) or []:
        stage_order.append(st.stage)
        stage_policy[st.stage] = "fail_fast" if st.stop_on_fail else "continue_all"

    by_stage: dict[str, list[EvaluatorConfig]] = {s: [] for s in stage_order}
    for rule in getattr(rule_set, "rules", None) or []:
        if not getattr(rule, "enabled", True) or not getattr(rule, "evaluator", ""):
            continue
        stage = rule.stage or "quality"
        if stage not in by_stage:
            stage_order.append(stage)
            by_stage[stage] = []
            stage_policy.setdefault(stage, "continue_all")
        by_stage[stage].append(EvaluatorConfig(rule.evaluator, dict(rule.params or {})))

    config = PipelineConfig(
        stages=[
            StageConfig(
                id=s,
                short_circuit_policy=stage_policy.get(s, "continue_all"),
                evaluators=by_stage[s],
            )
            for s in stage_order
        ]
    )
    return PipelineEngine(config, registry)


def build_default_pipeline(registry: EvaluatorRegistry) -> PipelineEngine:
    """加载内置默认规则集并构建管线（``build_pipeline`` 的便捷封装）。

    默认采用 ``coursework-quality``（门控 + 质量评估，无视觉）——安全默认，不依赖 Chromium。
    评估器集合的唯一来源是规则集。
    """
    from agent_eval.config.loader import ConfigLoader
    from agent_eval.config.paths import paths

    rule_set = ConfigLoader.load_rule_set(paths.rules_dir / "coursework-quality.yaml")
    return build_pipeline(registry, rule_set)
