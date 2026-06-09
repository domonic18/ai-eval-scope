"""ReportGenerator 测试。"""

from __future__ import annotations

import json

from agent_eval.core.types import ConstraintTier, EvalStatus
from agent_eval.evaluation.models import (
    ConstraintResult,
    MetricsReport,
    SampleResult,
    StageResult,
)
from agent_eval.reporting.report_generator import ReportGenerator


class TestTaskReport:
    """任务级报告测试。"""

    def test_generate_task_report_pass(self, sample_result_pass: SampleResult) -> None:
        """生成通过样本的任务报告。"""
        gen = ReportGenerator()
        md, json_dict = gen.generate_task_report(sample_result_pass)

        assert isinstance(md, str)
        assert "task_001" in md
        assert "Reward" in md
        assert "格式门控" in md
        assert "✅" in md

    def test_generate_task_report_fail(self, sample_result_fail: SampleResult) -> None:
        """生成失败样本的任务报告。"""
        gen = ReportGenerator()
        md, json_dict = gen.generate_task_report(sample_result_fail)

        assert "❌" in md
        assert "已跳过" in md

    def test_task_report_json_serializable(
        self,
        sample_result_pass: SampleResult,
    ) -> None:
        """JSON 报告可序列化。"""
        gen = ReportGenerator()
        _, json_dict = gen.generate_task_report(sample_result_pass)

        text = json.dumps(json_dict, ensure_ascii=False)
        parsed = json.loads(text)
        assert parsed["sample_id"] == "task_001"

    def test_task_report_contains_scores(
        self,
        sample_result_pass: SampleResult,
    ) -> None:
        """任务报告包含得分概览。"""
        gen = ReportGenerator()
        md, _ = gen.generate_task_report(sample_result_pass)

        assert "S_format" in md
        assert "S_common" in md
        assert "S_soft" in md
        assert "S_pref" in md


class TestSummaryReport:
    """聚合报告测试。"""

    def test_generate_summary_report(self, metrics_report: MetricsReport) -> None:
        """生成聚合报告。"""
        gen = ReportGenerator()
        md, json_dict = gen.generate_summary_report(metrics_report)

        assert isinstance(md, str)
        assert "聚合报告" in md
        assert "DR" in md
        assert "CPR" in md
        assert "Reward" in md

    def test_summary_metrics_table(self, metrics_report: MetricsReport) -> None:
        """聚合报告包含指标表格。"""
        gen = ReportGenerator()
        md, _ = gen.generate_summary_report(metrics_report)

        assert "0.500" in md  # DR
        assert "0.500" in md  # CPR

    def test_summary_threshold_check(self, metrics_report: MetricsReport) -> None:
        """聚合报告包含阈值对比。"""
        gen = ReportGenerator(thresholds={"DR": 0.95, "CPR": 0.90})
        md, _ = gen.generate_summary_report(metrics_report)

        # DR=0.5 < 0.95 → BELOW
        assert "BELOW" in md or "❌" in md

    def test_summary_failure_breakdown(self, metrics_report: MetricsReport) -> None:
        """聚合报告包含失败项明细。"""
        gen = ReportGenerator()
        md, _ = gen.generate_summary_report(metrics_report)

        assert "失败项" in md
        assert "format.response_format" in md

    def test_summary_sample_scores(self, metrics_report: MetricsReport) -> None:
        """聚合报告包含样本得分一览。"""
        gen = ReportGenerator()
        md, _ = gen.generate_summary_report(metrics_report)

        assert "样本得分" in md
        assert "task_001" in md
        assert "task_002" in md

    def test_summary_json_structure(self, metrics_report: MetricsReport) -> None:
        """JSON 报告结构正确。"""
        gen = ReportGenerator()
        _, json_dict = gen.generate_summary_report(metrics_report)

        assert "run_id" in json_dict
        assert "metrics" in json_dict
        assert json_dict["metrics"]["DR"] == 0.5
        assert "failure_breakdown" in json_dict

    def test_summary_json_serializable(self, metrics_report: MetricsReport) -> None:
        """JSON 报告可序列化。"""
        gen = ReportGenerator()
        _, json_dict = gen.generate_summary_report(metrics_report)

        text = json.dumps(json_dict, ensure_ascii=False)
        assert json.loads(text) is not None

    def test_empty_metrics_report(self) -> None:
        """空 MetricsReport。"""
        gen = ReportGenerator()
        empty_report = MetricsReport(run_id="test")
        md, json_dict = gen.generate_summary_report(empty_report)

        assert "test" in md
        assert json_dict["total_samples"] == 0


class TestConstraintToRuleResult:
    """ConstraintResult → rule_results.json 转换测试。"""

    def test_basic_conversion(self) -> None:
        """基本字段转换。"""
        gen = ReportGenerator()
        cr = ConstraintResult(
            constraint_id="format.response_format",
            name="文件格式检查",
            tier=ConstraintTier.HARD_GATE,
            status=EvalStatus.PASS,
            score=1.0,
            reason="通过",
        )
        result = gen.constraint_to_rule_result(cr)

        assert result["rule_id"] == "format.response_format"
        assert result["constraint_id"] == "format.response_format"
        assert result["passed"] is True
        assert result["score"] == 1.0
        assert result["tier"] == "hard_gate"

    def test_llm_judge_fields(self) -> None:
        """LLM Judge 溯源字段。"""
        gen = ReportGenerator()
        cr = ConstraintResult(
            constraint_id="soft.teaching_logic",
            name="教学逻辑",
            tier=ConstraintTier.SOFT,
            status=EvalStatus.PASS,
            score=0.8,
            reason="LLM 评估通过",
            judge_provider="deepseek_judge",
            judge_model="deepseek-chat",
            judge_record_path="evidence/judge_xxx.json",
        )
        result = gen.constraint_to_rule_result(cr)

        assert result["judge_provider"] == "deepseek_judge"
        assert result["judge_model"] == "deepseek-chat"
        assert result["judge_record_path"] == "evidence/judge_xxx.json"

    def test_no_llm_fields_omitted(self) -> None:
        """无 LLM 字段时不包含。"""
        gen = ReportGenerator()
        cr = ConstraintResult(
            constraint_id="format.document_count",
            name="文档数量检查",
            tier=ConstraintTier.HARD_GATE,
            status=EvalStatus.FAIL,
            score=0.0,
            reason="文档数为 0",
        )
        result = gen.constraint_to_rule_result(cr)

        assert "judge_provider" not in result
        assert "judge_model" not in result

    def test_module_results_preserved(self) -> None:
        """目录模式 module_results 保留。"""
        gen = ReportGenerator()
        cr = ConstraintResult(
            constraint_id="format.directory_structure",
            name="目录结构检查",
            tier=ConstraintTier.HARD_GATE,
            status=EvalStatus.PASS,
            score=1.0,
            reason="通过",
            module_results=[{"module": "M1", "file_count": 2, "passed": True}],
        )
        result = gen.constraint_to_rule_result(cr)

        assert "module_results" in result
        assert len(result["module_results"]) == 1


class TestSampleToRuleResults:
    """SampleResult → rule_results.json 列表测试。"""

    def test_flatten_all_constraints(
        self,
        sample_result_pass: SampleResult,
    ) -> None:
        """扁平化所有约束结果。"""
        gen = ReportGenerator()
        results = gen.sample_to_rule_results(sample_result_pass)

        # 包含 format + commonsense + quality 的所有约束
        assert len(results) >= 4  # 至少 4 个约束
        constraint_ids = [r["constraint_id"] for r in results]
        assert "format.response_format" in constraint_ids

    def test_skip_stage_no_results(self) -> None:
        """SKIP 阶段不产生结果。"""
        gen = ReportGenerator()
        sample = SampleResult(
            sample_id="test",
            status=EvalStatus.FAIL,
            stage_results={
                "format": StageResult(
                    stage_id="format",
                    status=EvalStatus.FAIL,
                    constraint_results=[
                        ConstraintResult(
                            constraint_id="format.response_format",
                            name="格式检查",
                            tier=ConstraintTier.HARD_GATE,
                            status=EvalStatus.FAIL,
                            score=0.0,
                            reason="失败",
                        ),
                    ],
                    gate_passed=False,
                ),
                "commonsense": StageResult(
                    stage_id="commonsense",
                    status=EvalStatus.SKIP,
                    gate_passed=False,
                ),
            },
        )
        results = gen.sample_to_rule_results(sample)

        # 只有 format 阶段的结果
        assert len(results) == 1
        assert results[0]["constraint_id"] == "format.response_format"
