"""SummaryGenerator — 评估完成后生成人话版摘要报告。

读取 summary_prompt.yaml → 收集评估数据 → 调用 LLM → 返回结构化 JSON。
LLM 不可用时返回 None（不阻塞评估流程）。
"""

from __future__ import annotations

import json
from typing import Any

import structlog
import yaml

from agent_eval.config.paths import PACKAGE_ROOT
from agent_eval.core.types import EvalStatus
from agent_eval.evaluation.models import SampleResult
from agent_eval.llm.models import Message
from agent_eval.llm.pool import ProviderPool

logger = structlog.get_logger("evaluation.summary")

_PROMPT_PATH = PACKAGE_ROOT / "assets" / "configs" / "summary_prompt.yaml"


def _load_prompt() -> dict[str, str]:
    """加载 summary_prompt.yaml → {system, user_template}。"""
    data = yaml.safe_load(_PROMPT_PATH.read_text(encoding="utf-8"))
    return {
        "system": data.get("system", ""),
        "user_template": data.get("user_template", ""),
    }


class SummaryGenerator:
    """评估完成后，根据 metrics + 失败约束 + 指标定义，调用 LLM 生成摘要报告。

    LLM 不可用时（额度耗尽/网络异常/未配置）返回 None，不影响评估结果。
    """

    def __init__(self, pool: ProviderPool | None = None) -> None:
        self.pool = pool

    def generate(
        self,
        *,
        metrics: dict[str, float],
        sample_results: list[SampleResult],
        metric_definitions: list[dict[str, Any]] | None = None,
        scenario: str = "",
    ) -> dict[str, Any] | None:
        """生成摘要报告。

        Args:
            metrics: 指标 ID → 数值（来自 MetricsReport.metrics）。
            sample_results: 所有样本的评估结果（含约束结论）。
            metric_definitions: 指标定义列表（含 name/summary/threshold）。
            scenario: 评估场景名。

        Returns:
            结构化摘要 dict（headline/highlights/issues/suggestion），或 None。
        """
        if self.pool is None or self.pool.default is None:
            logger.info("summary_generator.skip", reason="no_llm_pool")
            return None

        # 收集失败约束摘要
        failures = self._collect_failures(sample_results)
        passed = sum(1 for s in sample_results if s.status.value in ("pass", "passed"))
        failed = len(sample_results) - passed

        # 准备指标定义描述
        defs_json = json.dumps(
            metric_definitions or [],
            ensure_ascii=False,
            default=str,
        )

        # 渲染 prompt
        prompt = _load_prompt()
        user_msg = prompt["user_template"].format(
            scenario=scenario or "通用",
            metrics_json=json.dumps(metrics, ensure_ascii=False, default=str, indent=2),
            metric_defs_json=defs_json,
            failures_json=json.dumps(failures, ensure_ascii=False, indent=2),
            total=len(sample_results),
            passed=passed,
            failed=failed,
        )

        # 调用 LLM
        try:
            client = self.pool.default
            resp = client.chat(
                messages=[
                    Message(role="system", content=prompt["system"]),
                    Message(role="user", content=user_msg),
                ],
                max_tokens=2048,
                temperature=0.0,
            )
        except Exception as e:
            logger.warning("summary_generator.llm_failed", error=str(e))
            return None

        # 解析 JSON
        return self._parse_json(resp.content)

    def _collect_failures(self, sample_results: list[SampleResult]) -> list[dict[str, Any]]:
        """从样本结果中收集失败约束的摘要。"""
        failures: list[dict[str, Any]] = []
        for s in sample_results:
            for cr in s.stage_results.values():
                for result in cr.constraint_results:
                    if result.status == EvalStatus.PASS:
                        continue
                    detail: dict[str, Any] = {
                        "name": result.name,
                        "reason": result.reason or "",
                        "tier": result.tier,
                        "sample_id": s.sample_id,
                    }
                    # 提取 source_files
                    details = result.details or {}
                    files: list[str] = []
                    for sf in details.get("source_files", []):
                        fn = sf.get("filename") if isinstance(sf, dict) else None
                        if fn:
                            files.append(fn)
                    if files:
                        detail["files"] = files
                    # 提取 top issues
                    issues: list[str] = []
                    for dim in details.get("dimensions", []):
                        for issue in dim.get("issues", []):
                            desc = issue.get("desc") if isinstance(issue, dict) else None
                            if desc:
                                issues.append(desc)
                    if issues:
                        detail["top_issues"] = issues[:3]
                    failures.append(detail)
        return failures

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any] | None:
        """从 LLM 文本响应中解析 JSON（容忍 ```json 代码块包裹）。"""
        if not text:
            return None
        cleaned = text.strip()
        # 剥离 ```json ... ```
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [ln for ln in lines if not ln.startswith("```")]
            cleaned = "\n".join(lines)
        try:
            result = json.loads(cleaned)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass
        # 尝试抽取首个 {...}
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                result = json.loads(cleaned[start : end + 1])
                if isinstance(result, dict):
                    return result
            except (json.JSONDecodeError, ValueError):
                pass
        logger.warning("summary_generator.parse_failed", text_preview=cleaned[:200])
        return None
