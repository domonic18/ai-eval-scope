"""软约束与偏好约束评估器（5 项）。

LLM Judge:
- soft.teaching_logic: 教学逻辑（LLM_JUDGE）
- soft.content_diversity: 内容多样性（LLM_JUDGE）
- pref.style_preference: 风格偏好（LLM_JUDGE）
- pref.depth_preference: 深度偏好（LLM_JUDGE）
- pref.request_fulfillment: 需求满足度（LLM_JUDGE）
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from agent_eval.config import EVALUATOR_DEFAULTS
from agent_eval.core.exceptions import (
    LLMAuthError,
    LLMNetworkError,
    LLMQuotaExceededError,
    LLMRateLimitError,
    ProviderNotFoundError,
)
from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.models import ConstraintResult
from agent_eval.evaluation.registry import registry
from agent_eval.evaluation.text_utils import (
    collect_media_features,
    collect_module_texts,
    collect_text_content_with_markers,
    sample_module_brief,
)
from agent_eval.evaluation.text_utils import get_output_dir as _get_output_dir

# ─── LLM Judge 评估器 ───


def _band_of(score: float) -> str:
    """0-10 维度分 → 分档标签（与提示词评分锚点一致；band 由分派生，不让 LLM 给）。"""
    if score >= 9:
        return "优秀"
    if score >= 7:
        return "良好"
    if score >= 5:
        return "合格"
    if score >= 3:
        return "不足"
    return "严重不足"


def _manifest_filename_map(manifest: Any) -> dict[str, str] | None:
    """构建「全路径/基名 → 全路径」映射（用于校验 + 基名归一）。

    判官常只给文件基名（如 ``建构性导学.html``），这里既登记全路径也登记基名，
    基名冲突时取首个。manifest 缺失/异常返回 None（不校验，保留全部）。
    """
    if not isinstance(manifest, dict):
        return None
    mapping: dict[str, str] = {}
    for mod in manifest.get("modules") or []:
        for child in mod.get("children") or []:
            path = child.get("path")
            if not (isinstance(path, str) and path):
                continue
            mapping[path] = path
            mapping.setdefault(path.rsplit("/", 1)[-1], path)
    return mapping or None


def _aggregate_source_files(
    dimensions: list[dict[str, Any]] | None,
    context: dict[str, Any],
) -> list[dict[str, str]]:
    """聚合维度 issues[].involved_files → details.source_files（docs/arch/15 §4.4 C 档）。

    经 directory_manifest 校验，剔除判官幻觉的文件名；基名命中时归一为全路径。
    """
    if not dimensions:
        return []
    mapping = _manifest_filename_map(context.get("directory_manifest"))
    files: set[str] = set()
    for dim in dimensions:
        for issue in dim.get("issues") or []:
            for name in issue.get("involved_files") or []:
                if not isinstance(name, str):
                    continue
                name = name.strip()
                if not name:
                    continue
                if mapping is None:
                    files.add(name)
                else:
                    # 全路径优先；否则按基名归一为 manifest 中的全路径
                    resolved = mapping.get(name) or mapping.get(name.rsplit("/", 1)[-1])
                    if resolved:
                        files.add(resolved)
    return [{"filename": fn} for fn in sorted(files)]


# ─── 目录模式（大单元）粒度分组 ───


def _package_group(output_dir: Path | None) -> list[dict[str, Any]]:
    """单组（package 粒度 / 退化 / manifest 缺失）：全部文件合并为一组。"""
    text = collect_text_content_with_markers(output_dir) if output_dir else ""
    return [{"key": "__package__", "label": "整体", "files": [], "text": text, "file_count": 0}]


def _resolve_granularity_groups(
    manifest: Any, output_dir: Path | None, granularity: str, *, max_modules: int = 12
) -> list[dict[str, Any]]:
    """按评估粒度把产出物文件分成若干评估组（docs/arch/04 §5.5）。

    每组: ``{"key", "label", "files", "text", "file_count"}``。
    - ``package`` / manifest 缺失 / output_dir 缺失 → 单组（全部文件）
    - ``module`` → 读 manifest.modules；**退化检测**（无模块 / 单模块 / 每模块恰 1 文件=扁平）
      → 回退单组；模块数超 ``max_modules`` → 合并相邻模块到 max_modules 组（防 LLM 调用爆炸）；
      模块文本超 max_content_chars → sample_module_brief
    """
    if granularity != "module" or not isinstance(manifest, dict) or output_dir is None:
        return _package_group(output_dir)
    modules = manifest.get("modules") or []
    total_files = manifest.get("total_files") or sum(len(m.get("children") or []) for m in modules)
    # 退化检测：扁平根平铺（每文件自成 1 模块且文件在根、非子目录）→ 回退 package；
    # 单模块 → 回退。"每模块 1 文件的多模块"（文件在子目录）不算退化，保留 module 粒度。
    is_flat = len(modules) == total_files and all(
        "/" not in (c.get("path") or "") for m in modules for c in (m.get("children") or [])
    )
    if not modules or len(modules) == 1 or is_flat:
        return _package_group(output_dir)  # 退化 → 回退 package

    # max_modules 保护：模块数超限 → 合并相邻模块到 max_modules 组（合并 children，
    # collect 时统一处理），防大单元如 20 模块 × N 评估器 = LLM 调用爆炸
    if len(modules) > max_modules:
        chunk_size = max(1, math.ceil(len(modules) / max_modules))
        merged: list[dict[str, Any]] = []
        for i in range(0, len(modules), chunk_size):
            group_mods = modules[i : i + chunk_size]
            children = [c for m in group_mods for c in (m.get("children") or [])]
            first = group_mods[0].get("name") or group_mods[0].get("path") or "module"
            name = first if len(group_mods) == 1 else f"{first} 等 {len(group_mods)} 模块"
            merged.append({"name": name, "children": children})
        modules = merged

    max_chars = EVALUATOR_DEFAULTS.max_content_chars
    groups: list[dict[str, Any]] = []
    for mod in modules:
        children = mod.get("children") or []
        if not children:
            continue
        text = collect_module_texts(output_dir, children)
        if not text.strip():
            continue
        if len(text) > max_chars:  # 模块超长 → 采样兜底
            text = sample_module_brief(output_dir, children)
        groups.append(
            {
                "key": mod.get("name") or mod.get("path") or "module",
                "label": mod.get("name") or mod.get("path") or "module",
                "files": [c.get("path") for c in children if c.get("path")],
                "text": text,
                "file_count": len(children),
            }
        )
    return groups if len(groups) > 1 else _package_group(output_dir)


class BaseLLMJudgeEvaluator(BaseEvaluator):
    """LLM Judge 评估器基类 — 处理 LLM 评估的通用流程。

    子类只需设置类属性 template_id 并可选择性覆盖 _build_variables()。
    LLM 调用依赖 context 中的 judge_orchestrator 和 evidence_dir。
    当 orchestrator 不可用时，降级为 Rule-based 默认通过模式。
    """

    template_id: str = ""  # 子类必须设置
    pass_threshold: float | None = None  # HARD_SCORE 二值阈值；None=连续分（SOFT/PREF）
    # 目录模式（大单元）评估粒度：module=按模块（模块内自洽类，默认）；package=整单元一次
    # （跨模块类如 content_diversity/logical/chronological 覆盖为 package）。详见 docs/arch/04 §5.5。
    default_granularity: str = "module"

    def _effective_granularity(self) -> str:
        """优先规则层 params.directory_granularity，回退类默认。"""
        g = self.params.get("directory_granularity", self.default_granularity)
        return g if g in ("package", "module", "file") else self.default_granularity

    @property
    def _effective_template_id(self) -> str:
        """优先使用规则层传入的 prompt_id，回退到 params.template_id，最后才是类默认值。"""
        return self.params.get("prompt_id") or self.params.get("template_id") or self.template_id

    def evaluate(self, sample: Any, context: dict[str, Any]) -> ConstraintResult:
        import time

        start = time.monotonic()

        # 检查是否有可用的 JudgeOrchestrator
        orchestrator = context.get("judge_orchestrator")
        evidence_dir = context.get("evidence_dir")

        if orchestrator is None or evidence_dir is None:
            # LLM 不可用：跳过该评估器，不计入得分（避免默认 PASS 令 reward 虚高）
            elapsed = (time.monotonic() - start) * 1000
            return ConstraintResult(
                constraint_id=self.evaluator_id,
                name=self.name,
                tier=self.tier,
                status=EvalStatus.SKIP,
                score=0.0,
                reason=f"{self.name}（LLM 不可用，已跳过，不计入得分）",
                duration_ms=elapsed,
            )

        # 熔断：同 sample 内已检测到额度耗尽，后续 LLM 评估器直接跳过
        if context.get("llm_quota_exhausted"):
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.SKIP,
                score=0.0,
                reason=f"{self.name}（LLM 额度耗尽，已熔断跳过，不计入得分）",
                duration_ms=elapsed,
            )

        # 收集文档内容 + 按粒度分组（module → 多组；package/退化/缺 manifest → 单组）
        output_dir = _get_output_dir(sample)
        context["output_dir"] = output_dir  # 供 content_diversity 等子类 _build_variables 复用
        groups = _resolve_granularity_groups(
            context.get("directory_manifest"),
            output_dir,
            self._effective_granularity(),
            max_modules=self.params.get("max_modules", 12),
        )

        # 多组（module 粒度且非退化）：逐组评估 + module_results 聚合
        if len(groups) > 1:
            return self._evaluate_multi_group(
                groups,
                sample,
                context,
                orchestrator,
                evidence_dir,
                self.params.get("llm_provider"),
                start,
            )

        # 单组（package / 退化 / manifest 缺失）：原路径，零回归
        text = groups[0]["text"] if groups else ""

        if not text.strip():
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="文档内容为空，无法进行 LLM 评估",
                duration_ms=elapsed,
            )

        # 截断过长内容（避免超过 token 限制）
        max_chars = self.params.get("max_content_chars", EVALUATOR_DEFAULTS.max_content_chars)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[...内容已截断...]"

        # 调用 JudgeOrchestrator（通过钩子，视觉等子类可覆盖以传 images）
        try:
            scores, record, extra_details = self._invoke_judge(
                orchestrator,
                sample=sample,
                text=text,
                context=context,
                evidence_dir=evidence_dir,
                provider_name=self.params.get("llm_provider"),
            )
        except LLMQuotaExceededError as e:
            # 额度耗尽：设置熔断标志，同 sample 后续 LLM 评估器直接跳过
            context["llm_quota_exhausted"] = True
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.SKIP,
                score=0.0,
                reason=f"{self.name}（LLM 不可用：{type(e).__name__}，已跳过，不计入得分）",
                duration_ms=elapsed,
            )
        except (
            LLMAuthError,
            LLMNetworkError,
            LLMRateLimitError,
            ProviderNotFoundError,
        ) as e:
            # LLM 不可用（鉴权失败/网络/限流/未配置）→ 跳过，不计分、不 FAIL
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.SKIP,
                score=0.0,
                reason=f"{self.name}（LLM 不可用：{type(e).__name__}，已跳过，不计入得分）",
                duration_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.ERROR,
                score=0.0,
                reason=f"LLM Judge 调用失败: {e}",
                duration_ms=elapsed,
            )

        elapsed = (time.monotonic() - start) * 1000

        # 计算加权分数：各维度得分 × 权重 / 总权重
        template = orchestrator.templates.get(None, self._effective_template_id)
        if template and template.dimensions:
            total_weight = sum(d.weight for d in template.dimensions)
            weighted_score = sum(scores.get(d.dim_id, 0.0) * d.weight for d in template.dimensions)
            normalized = (weighted_score / total_weight / 10.0) if total_weight > 0 else 0.0
        else:
            # 无维度信息，取平均
            vals = list(scores.values())
            normalized = (sum(vals) / len(vals) / 10.0) if vals else 0.0

        normalized = max(0.0, min(1.0, normalized))

        # 构建评估原因 — 使用维度中文名
        score_parts = []
        if template and template.dimensions:
            for dim in template.dimensions:
                dim_score = scores.get(dim.dim_id, 0.0)
                score_parts.append(f"{dim.name}: {dim_score:.1f}")
        else:
            score_parts = [f"{k}: {v:.1f}" for k, v in scores.items()]

        reason = f"{self.name}（LLM 评估）：{', '.join(score_parts)}"
        if record and hasattr(record, "summary") and record.summary:
            reason += f" — {record.summary[:150]}"

        # 构建 details — 包含结构化维度详情和 LLM 总结
        details: dict[str, Any] = {
            "scores": scores,
            "confidence": record.confidence if record else {},
        }
        # 合并子类附加的详情（如视觉截图路径）
        if extra_details:
            details.update(extra_details)
        if record and hasattr(record, "summary"):
            details["summary"] = record.summary
        if template and template.dimensions:
            dim_details = record.dim_details if record and hasattr(record, "dim_details") else {}
            details["dimensions"] = [
                {
                    "id": dim.dim_id,
                    "name": dim.name,
                    "score": scores.get(dim.dim_id, 0.0),
                    "weight": dim.weight,
                    "band": _band_of(scores.get(dim.dim_id, 0.0)),
                    "confidence": (
                        record.confidence.get(dim.dim_id, "unknown") if record else "unknown"
                    ),
                    # 透传该维度可解释性字段（reason/issues/highlights）；旧提示词无则缺省
                    **(dim_details.get(dim.dim_id, {})),
                }
                for dim in template.dimensions
            ]
            # 文件定位（docs/arch/15 C 档）：聚合 issues[].involved_files，经 manifest 校验
            details["source_files"] = _aggregate_source_files(details["dimensions"], context)

        # 获取 judge record 路径
        record_path = None
        if record:
            judge_id = record.judge_id
            record_path = f"evidence/{judge_id}.json"

        # HARD_SCORE（pass_threshold 设值）→ 二值；SOFT/PREF（None）→ 连续分
        if self.pass_threshold is not None:
            passed = normalized >= self.pass_threshold
            status = EvalStatus.PASS if passed else EvalStatus.FAIL
            score = 1.0 if passed else 0.0
        else:
            status = (
                EvalStatus.PASS
                if normalized >= EVALUATOR_DEFAULTS.llm_judge_pass_threshold
                else EvalStatus.FAIL
            )
            score = normalized

        return ConstraintResult(
            constraint_id=self.evaluator_id,
            name=self.name,
            tier=self.tier,
            status=status,
            score=score,
            reason=reason,
            details=details,
            duration_ms=elapsed,
            judge_provider=record.provider_name if record else None,
            judge_model=record.model if record else None,
            judge_record_path=record_path,
        )

    def _invoke_judge(
        self,
        orchestrator: Any,
        *,
        sample: Any,
        text: str,
        context: dict[str, Any],
        evidence_dir: Any,
        provider_name: str | None,
    ) -> tuple[dict[str, Any], Any, dict[str, Any]]:
        """调用 JudgeOrchestrator 执行评估（钩子）。

        默认实现：构建模板变量后调用 orchestrator.judge()。
        子类（如视觉评估器）可覆盖以传入 images 等额外参数。

        Returns:
            (scores, JudgeRecord, extra_details) 三元组。
            extra_details 为附加到 ConstraintResult.details 的字段（可空 dict）。
        """
        variables = self._build_variables(text, context)
        ev = Path(evidence_dir) if not isinstance(evidence_dir, Path) else evidence_dir
        scores, record = orchestrator.judge(
            constraint_id=self.evaluator_id,
            sample_id=context.get("sample_id", "unknown"),
            template_id=self._effective_template_id,
            variables=variables,
            evidence_dir=ev,
            provider_name=provider_name,
            trace_id=context.get("trace_id"),
        )
        return scores, record, {}

    def _build_variables(self, text: str, context: dict[str, Any]) -> dict[str, Any]:
        """构建 Prompt 模板变量。子类可覆盖以添加特定变量。"""
        return {
            "content": text[: EVALUATOR_DEFAULTS.llm_judge_content_chars],
            "title": context.get("task_input", {}).get("title", "未知标题"),
            "subject": context.get("task_input", {}).get("subject", "未知学科"),
        }

    # ---- 目录模式（module 粒度）多组评估 ----

    @staticmethod
    def _weighted_normalized(scores: dict[str, Any], dims: Any) -> float:
        """维度加权 → 0-1 归一（提取自单组 evaluate，单组/多组共用口径）。"""
        if dims:
            total_weight = sum(d.weight for d in dims)
            weighted = sum(scores.get(d.dim_id, 0.0) * d.weight for d in dims)
            normalized = (weighted / total_weight / 10.0) if total_weight > 0 else 0.0
        else:
            vals = list(scores.values())
            normalized = (sum(vals) / len(vals) / 10.0) if vals else 0.0
        return max(0.0, min(1.0, normalized))

    def _format_module_reason(
        self, scores: dict[str, Any], dims: Any, record: Any, module_key: str
    ) -> str:
        """单模块评估原因（含维度分 + LLM summary）。"""
        if dims:
            parts = [f"{d.name}: {scores.get(d.dim_id, 0.0):.1f}" for d in dims]
        else:
            parts = [f"{k}: {v:.1f}" for k, v in scores.items()]
        r = f"[{module_key}] {', '.join(parts)}"
        if record and hasattr(record, "summary") and record.summary:
            r += f" — {record.summary[:100]}"
        return r

    def _evaluate_multi_group(
        self,
        groups: list[dict[str, Any]],
        sample: Any,
        context: dict[str, Any],
        orchestrator: Any,
        evidence_dir: Any,
        provider_name: str | None,
        start: float,
    ) -> ConstraintResult:
        """module 粒度多组评估：逐组 judge + 按 file_count 加权聚合 + module_results 归因。

        每组独立调 _invoke_judge；顶层 status/score 由各组加权均分派；module_results 记每模块
        子结果，端到端透传至 web SampleDetail（docs/arch/04 §5.5.3）。SOFT/PREF 连续分聚合；
        HARD（pass_threshold 设值）需各组全过才算过。
        """
        import time

        template = orchestrator.templates.get(None, self._effective_template_id)
        dims = template.dimensions if template and template.dimensions else []
        threshold = (
            self.pass_threshold
            if self.pass_threshold is not None
            else EVALUATOR_DEFAULTS.llm_judge_pass_threshold
        )
        per_module: list[dict[str, Any]] = []
        sum_score = 0.0
        sum_weight = 0
        first_record: Any = None
        for g in groups:
            try:
                scores, record, _ = self._invoke_judge(
                    orchestrator,
                    sample=sample,
                    text=g["text"],
                    context=context,
                    evidence_dir=evidence_dir,
                    provider_name=provider_name,
                )
            except LLMQuotaExceededError as e:
                context["llm_quota_exhausted"] = True
                elapsed = (time.monotonic() - start) * 1000
                return self._make_result(
                    status=EvalStatus.SKIP,
                    score=0.0,
                    reason=f"{self.name}（LLM 不可用：{type(e).__name__}，已跳过）",
                    duration_ms=elapsed,
                )
            except (LLMAuthError, LLMNetworkError, LLMRateLimitError, ProviderNotFoundError) as e:
                elapsed = (time.monotonic() - start) * 1000
                return self._make_result(
                    status=EvalStatus.SKIP,
                    score=0.0,
                    reason=f"{self.name}（LLM 不可用：{type(e).__name__}，已跳过）",
                    duration_ms=elapsed,
                )
            if first_record is None:
                first_record = record
            normalized = self._weighted_normalized(scores, dims)
            passed = normalized >= threshold
            per_module.append(
                {
                    "module": g["key"],
                    "score": round(normalized, 3),
                    "passed": passed,
                    "scores": (
                        {d.dim_id: round(scores.get(d.dim_id, 0.0), 2) for d in dims}
                        if dims
                        else {k: round(v, 2) for k, v in scores.items()}
                    ),
                    "reason": self._format_module_reason(scores, dims, record, g["key"]),
                    "file_count": g["file_count"],
                }
            )
            sum_score += normalized * g["file_count"]
            sum_weight += g["file_count"]

        overall = sum_score / sum_weight if sum_weight else 0.0
        if self.pass_threshold is not None:
            all_pass = all(m["passed"] for m in per_module)
            status, score = (EvalStatus.PASS, 1.0) if all_pass else (EvalStatus.FAIL, 0.0)
        else:
            status = EvalStatus.PASS if overall >= threshold else EvalStatus.FAIL
            score = overall
        elapsed = (time.monotonic() - start) * 1000
        reason = f"{self.name}（按 {len(per_module)} 个模块评估，加权均分 {overall:.2f}）"
        details: dict[str, Any] = {
            "scores": {},
            "module_count": len(per_module),
            "modules": [m["module"] for m in per_module],
        }
        return ConstraintResult(
            constraint_id=self.evaluator_id,
            name=self.name,
            tier=self.tier,
            status=status,
            score=score,
            reason=reason,
            details=details,
            duration_ms=elapsed,
            module_results=per_module,
            judge_provider=first_record.provider_name if first_record else None,
            judge_model=first_record.model if first_record else None,
        )


@registry.register("soft.teaching_logic")
class TeachingLogicEvaluator(BaseLLMJudgeEvaluator):
    """教学逻辑评估 — LLM 评审课件的教学结构、知识递进和互动设计。"""

    evaluator_id = "soft.teaching_logic"
    name = "教学逻辑"
    tier = ConstraintTier.SOFT
    method = EvalMethod.LLM_JUDGE
    template_id = "pedagogical_logic"


@registry.register("soft.content_diversity")
class ContentDiversityEvaluator(BaseLLMJudgeEvaluator):
    """内容多样性评估 — LLM 评审内容的丰富度和多样性。"""

    evaluator_id = "soft.content_diversity"
    name = "内容多样性"
    tier = ConstraintTier.SOFT
    method = EvalMethod.LLM_JUDGE
    template_id = "content_diversity"
    # 内容多样性语义上需全局视野（跨模块聚合），保持整单元单次评估
    default_granularity = "package"

    def _build_variables(self, text: str, context: dict[str, Any]) -> dict[str, Any]:
        variables = super()._build_variables(text, context)
        # 媒体特征对全文件原文统计（修 html_to_text 剥标签导致 <table>/<img> 对 HTML 源失效的 bug）
        output_dir = context.get("output_dir")
        if output_dir:
            variables.update(collect_media_features(Path(output_dir)))
        else:
            variables.update(
                {"has_formula": "否", "has_table": "否", "has_image": "否", "has_list": "否"}
            )
        return variables


@registry.register("pref.style_preference")
class StylePreferenceEvaluator(BaseLLMJudgeEvaluator):
    """风格偏好评估 — LLM 评审文档风格是否符合要求。"""

    evaluator_id = "pref.style_preference"
    name = "风格偏好"
    tier = ConstraintTier.PREFERENCE
    method = EvalMethod.LLM_JUDGE
    template_id = "style_preference"


@registry.register("pref.depth_preference")
class DepthPreferenceEvaluator(BaseLLMJudgeEvaluator):
    """深度偏好评估 — LLM 评审内容深度是否满足要求。"""

    evaluator_id = "pref.depth_preference"
    name = "深度偏好"
    tier = ConstraintTier.PREFERENCE
    method = EvalMethod.LLM_JUDGE
    template_id = "depth_preference"


@registry.register("pref.request_fulfillment")
class RequestFulfillmentEvaluator(BaseLLMJudgeEvaluator):
    """需求满足度评估 — LLM 评审产出是否满足原始需求。"""

    evaluator_id = "pref.request_fulfillment"
    name = "需求满足度"
    tier = ConstraintTier.PREFERENCE
    method = EvalMethod.LLM_JUDGE
    template_id = "request_fulfillment"

    def _build_variables(self, text: str, context: dict[str, Any]) -> dict[str, Any]:
        variables = super()._build_variables(text, context)
        # 添加原始需求信息
        task_input = context.get("task_input", {})
        variables["original_request"] = task_input.get("input", "未提供原始需求")
        variables["expected_output"] = task_input.get("expected", "未提供预期输出描述")
        return variables
