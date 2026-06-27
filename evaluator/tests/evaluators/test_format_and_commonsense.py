"""格式评估器 + 常识评估器专项测试。

使用 tests/fixtures/golden/ 下的黄金样本验证评估器判定正确性。
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_eval.core.types import EvalStatus
from agent_eval.evaluation.evaluators import *  # trigger registration
from agent_eval.evaluation.evaluators.commonsense_evaluators import _reset_fact_db_cache
from agent_eval.evaluation.registry import registry

FIXTURES = Path(__file__).parent.parent / "fixtures"
GOLDEN = FIXTURES / "golden"


def _prepare_output(tmp_path: Path) -> Path:
    """Create output/ subdir and return it so callers can place files there.

    Evaluators' ``_get_output_dir`` does ``sample / "output"`` when sample is a Path,
    so the test must create files in ``tmp_path / "output"`` and pass ``tmp_path`` as
    the sample argument.
    """
    out = tmp_path / "output"
    out.mkdir()
    return out


# ─── 格式评估器 ───


class TestResponseFormatEvaluator:
    def test_valid_md_documents(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "index.md").write_text("# Title\n\nContent here.")
        (out / "chapter.md").write_text("## Chapter\n\nMore content.")

        ev = registry.create("format.response_format", {"allowed_formats": ["md"]})
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS
        assert result.score == 1.0

    def test_valid_html_documents(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "index.html").write_text("<!DOCTYPE html><html><body>Hello</body></html>")

        ev = registry.create("format.response_format", {"allowed_formats": ["html"]})
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS

    def test_invalid_format(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "data.csv").write_text("a,b,c\n1,2,3")

        ev = registry.create("format.response_format", {"allowed_formats": ["md", "html"]})
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL
        assert result.score == 0.0

    def test_mixed_valid_and_invalid(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "good.md").write_text("# Good")
        (out / "bad.txt").write_text("plain text")

        ev = registry.create("format.response_format", {"allowed_formats": ["md"]})
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL

    def test_empty_directory(self, tmp_path: Path) -> None:
        ev = registry.create("format.response_format")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL


class TestHtmlValidityEvaluator:
    def test_valid_html(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "index.html").write_text(
            "<!DOCTYPE html><html><head><title>Test</title></head><body><p>Hello</p></body></html>"
        )

        ev = registry.create("format.html_validity")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS

    def test_unclosed_tag(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "bad.html").write_text("<html><body><p>Unclosed")

        ev = registry.create("format.html_validity")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL

    def test_no_html_files_pass(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("# Doc")

        ev = registry.create("format.html_validity", {"check_html_only": True})
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS

    def test_empty_html_file(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "empty.html").write_text("")

        ev = registry.create("format.html_validity")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL

    def test_text_quotes_not_false_positive(self, tmp_path: Path) -> None:
        """正文含奇数个文本双引号（不成对的强调）但标签结构完整 → 有效（核心回归）。"""
        out = _prepare_output(tmp_path)
        (out / "doc.html").write_text(
            '<html><body><p>正文含"范式"和电场"等术语</p></body></html>',
            encoding="utf-8",
        )

        ev = registry.create("format.html_validity")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS

    def test_unclosed_attribute_quote(self, tmp_path: Path) -> None:
        """属性引号未闭合（解析器吞掉后续标签）→ 无效。"""
        out = _prepare_output(tmp_path)
        (out / "bad.html").write_text(
            '<html><body><div class="foo>内容</div></body></html>',
            encoding="utf-8",
        )

        ev = registry.create("format.html_validity")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL

    def test_illegal_nesting(self, tmp_path: Path) -> None:
        """标签非法嵌套（<b><i></b></i>）→ 无效。"""
        out = _prepare_output(tmp_path)
        (out / "bad.html").write_text(
            "<html><body><b><i>text</b></i></body></html>",
            encoding="utf-8",
        )

        ev = registry.create("format.html_validity")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL


# ─── 常识评估器 ───


class TestInfoAccuracyEvaluator:
    """知识准确性评估器测试 — 三层检查架构。"""

    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        """每个测试前重置事实知识库缓存。"""
        _reset_fact_db_cache()
        yield
        _reset_fact_db_cache()

    # ─── 向后兼容：原有 3 个测试 ───

    def test_no_rules_pass(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("# 物理\n\n浮力是向上的力。")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS

    def test_must_contain_rule(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("# 浮力\n\n浮力的定义。")

        ev = registry.create(
            "commonsense.info_accuracy",
            {
                "fact_rules": [
                    {"type": "must_contain", "keyword": "阿基米德"},
                ],
            },
        )
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL

    def test_must_not_contain_rule(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("# 浮力\n\n浮力等于物体的重量。")

        ev = registry.create(
            "commonsense.info_accuracy",
            {
                "fact_rules": [
                    {"type": "must_not_contain", "pattern": "浮力等于物体的重量"},
                ],
            },
        )
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL

    # ─── Phase 1: 内置算术检查 ───

    def test_arithmetic_error_detected(self, tmp_path: Path) -> None:
        """错误算术表达式应被检测。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("买书花费：23 + 18 = 42 元")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL
        assert result.score == 0.0
        # 检查 findings 中有 arithmetic 类型错误
        findings = result.details.get("findings", [])
        arith_errors = [f for f in findings if f["check_type"] == "arithmetic"]
        assert len(arith_errors) > 0
        assert "算术错误" in arith_errors[0]["message"]

    def test_arithmetic_correct_passes(self, tmp_path: Path) -> None:
        """正确算术表达式不应报错。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("买书花费：23 + 18 = 41 元")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS
        findings = result.details.get("findings", [])
        arith_errors = [f for f in findings if f["check_type"] == "arithmetic"]
        assert len(arith_errors) == 0

    def test_arithmetic_vertical_calc_skipped(self, tmp_path: Path) -> None:
        """竖式计算上下文中的算术应被跳过。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("竖式计算：个位 7+9=16，写6进1；十位 3+2+1=6，结果是 67。")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        # 竖式计算上下文应被跳过，不会报错
        findings = result.details.get("findings", [])
        arith_errors = [f for f in findings if f["check_type"] == "arithmetic"]
        assert len(arith_errors) == 0

    # ─── Phase 1: 常数校验 ───

    def test_constant_error_detected(self, tmp_path: Path) -> None:
        """错误的科学常数应被检测。"""
        out = _prepare_output(tmp_path)
        (out / "const.md").write_text("圆周率 π = 3.20")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL
        findings = result.details.get("findings", [])
        const_errors = [f for f in findings if f["check_type"] == "constant"]
        assert len(const_errors) > 0
        assert "圆周率" in const_errors[0]["message"]

    def test_constant_correct_passes(self, tmp_path: Path) -> None:
        """正确的科学常数不应报错。"""
        out = _prepare_output(tmp_path)
        (out / "const.md").write_text("圆周率 π = 3.14")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        findings = result.details.get("findings", [])
        const_errors = [f for f in findings if f["check_type"] == "constant"]
        assert len(const_errors) == 0

    # ─── Phase 1: 常识错误检测 ───

    def test_misconception_warning(self, tmp_path: Path) -> None:
        """常识错误模式应被标记为 warning。"""
        out = _prepare_output(tmp_path)
        (out / "history.md").write_text("祖冲之是唐朝著名数学家。")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        findings = result.details.get("findings", [])
        misconceptions = [f for f in findings if f["check_type"] == "misconception"]
        assert len(misconceptions) > 0
        assert misconceptions[0]["severity"] == "warning"
        assert "祖冲之" in misconceptions[0]["message"]
        # warning 不影响 pass/fail
        assert result.details["warnings"] > 0

    # ─── Per-file 归属 ───

    def test_per_file_attribution(self, tmp_path: Path) -> None:
        """错误应携带文件名归属。"""
        out = _prepare_output(tmp_path)
        (out / "clean.md").write_text("这是一篇关于浮力的文章。")
        (out / "error.md").write_text("计算 5 + 3 = 9")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        findings = result.details.get("findings", [])
        arith_errors = [f for f in findings if f["check_type"] == "arithmetic"]
        assert len(arith_errors) > 0
        # 错误应归属于 error.md 而非 clean.md
        assert any("error.md" in f["file"] for f in arith_errors)
        assert not any("clean.md" in f["file"] for f in arith_errors)

    # ─── 计分 ───

    def test_raw_score_ratio(self, tmp_path: Path) -> None:
        """raw_score 应反映正确率。"""
        out = _prepare_output(tmp_path)
        # 1 个正确算术 + 1 个错误算术 = 2 checks, 1 error → raw_score=0.5
        (out / "math.md").write_text("23 + 18 = 41 是正确的，但 5 + 3 = 9 是错误的。")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        # 2 checks, 1 error → raw_score = 0.5, below threshold 0.8 → FAIL
        assert result.raw_score is not None
        assert 0 < result.raw_score < 1.0
        assert result.status == EvalStatus.FAIL

    def test_custom_threshold(self, tmp_path: Path) -> None:
        """自定义 pass_threshold 应影响判定。"""
        out = _prepare_output(tmp_path)
        # 1 correct arithmetic + 1 correct constant
        (out / "math.md").write_text("23 + 18 = 41，π = 3.14")

        ev = registry.create("commonsense.info_accuracy", {"pass_threshold": 1.0})
        result = ev.evaluate(tmp_path, {})
        # 无错误 → raw_score = 1.0 → 即使 threshold=1.0 也 PASS
        assert result.status == EvalStatus.PASS

    # ─── Phase 2: 新规则类型 ───

    def test_regex_match_rule(self, tmp_path: Path) -> None:
        """regex_match 规则应正确工作。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("圆周率是一个重要的数学常数。")

        # must_match=True: 应找到匹配 → PASS
        ev = registry.create(
            "commonsense.info_accuracy",
            {
                "fact_rules": [
                    {
                        "type": "regex_match",
                        "pattern": r"圆周率",
                        "must_match": True,
                        "name": "圆周率提及",
                    },
                ],
            },
        )
        result = ev.evaluate(tmp_path, {})
        findings = result.details.get("findings", [])
        rule_errors = [f for f in findings if f.get("rule_type") == "regex_match"]
        assert len(rule_errors) == 0

    def test_regex_match_not_found(self, tmp_path: Path) -> None:
        """regex_match must_match=True 但未找到 → 报错。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("这是一个简单的文档。")

        ev = registry.create(
            "commonsense.info_accuracy",
            {
                "fact_rules": [
                    {
                        "type": "regex_match",
                        "pattern": r"圆周率",
                        "must_match": True,
                        "name": "圆周率提及",
                    },
                ],
            },
        )
        result = ev.evaluate(tmp_path, {})
        findings = result.details.get("findings", [])
        rule_errors = [f for f in findings if f.get("rule_type") == "regex_match"]
        assert len(rule_errors) > 0

    def test_number_in_context_rule(self, tmp_path: Path) -> None:
        """number_in_context 规则应检查关键词附近数值。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("圆周率的近似值是3.20")

        ev = registry.create(
            "commonsense.info_accuracy",
            {
                "fact_rules": [
                    {
                        "type": "number_in_context",
                        "keyword": "圆周率",
                        "min": 3.14,
                        "max": 3.15,
                        "name": "圆周率数值",
                    },
                ],
            },
        )
        result = ev.evaluate(tmp_path, {})
        findings = result.details.get("findings", [])
        ctx_errors = [f for f in findings if f.get("rule_type") == "number_in_context"]
        assert len(ctx_errors) > 0

    def test_forbidden_pattern_rule(self, tmp_path: Path) -> None:
        """forbidden_pattern 规则应检测禁止模式。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("祖冲之是唐朝最伟大的数学家。")

        ev = registry.create(
            "commonsense.info_accuracy",
            {
                "fact_rules": [
                    {
                        "type": "forbidden_pattern",
                        "pattern": r"祖冲之.*唐朝",
                        "reason": "祖冲之非唐朝人",
                    },
                ],
            },
        )
        result = ev.evaluate(tmp_path, {})
        findings = result.details.get("findings", [])
        forbidden_errors = [f for f in findings if f.get("rule_type") == "forbidden_pattern"]
        assert len(forbidden_errors) > 0

    # ─── details 结构验证 ───

    def test_details_structure(self, tmp_path: Path) -> None:
        """details 应包含标准字段。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("23 + 18 = 41")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        assert "files_checked" in result.details
        assert "checks_total" in result.details
        assert "errors" in result.details
        assert "warnings" in result.details
        assert "findings" in result.details
        assert result.details["checks_total"] >= 0

    # ─── 多项表达式验证（课程场景高频格式） ───

    def test_multi_term_addition_correct(self, tmp_path: Path) -> None:
        """三项以上加法应正确验证完整表达式，而非子表达式。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text(
            "总花费：3 + 2 + 15 = 20 元\n总数：24 + 32 + 27 = 83 本\n总分：42 + 38 + 45 = 125 分"
        )

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS
        arith_errors = [
            f for f in result.details.get("findings", []) if f["check_type"] == "arithmetic"
        ]
        assert len(arith_errors) == 0

    def test_multi_term_addition_error(self, tmp_path: Path) -> None:
        """多项加法总和错误应被检测。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("购物方案：12×2 + 7 + 3 + 5 + 18 = 100 元")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL
        arith_errors = [
            f for f in result.details.get("findings", []) if f["check_type"] == "arithmetic"
        ]
        assert len(arith_errors) == 1
        assert "57" in arith_errors[0]["message"]

    def test_chained_equation_correct(self, tmp_path: Path) -> None:
        """链式等式（A = B + C = D）应只验证最终结果。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("验证：28×8 + 22×9 + 35×4 = 224 + 198 + 140 = 562元")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        arith_errors = [
            f for f in result.details.get("findings", []) if f["check_type"] == "arithmetic"
        ]
        assert len(arith_errors) == 0, (
            f"链式展开式不应产生误报: {[e['message'] for e in arith_errors]}"
        )

    def test_verification_sum_correct(self, tmp_path: Path) -> None:
        """验证和（268+145+87=500）不应被拆成子表达式报错。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("检验结果：268+145+87=500 ✓")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        arith_errors = [
            f for f in result.details.get("findings", []) if f["check_type"] == "arithmetic"
        ]
        assert len(arith_errors) == 0

    def test_division_with_remainder_correct(self, tmp_path: Path) -> None:
        """带余数除法（125 ÷ 3 = 41 余 2）应正确验证。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("平均每分钟：125 ÷ 3 = 41 余 2 个")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        arith_errors = [
            f for f in result.details.get("findings", []) if f["check_type"] == "arithmetic"
        ]
        assert len(arith_errors) == 0

    def test_division_with_remainder_error(self, tmp_path: Path) -> None:
        """带余数除法计算错误应被检测。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("平均每分钟：125 ÷ 3 = 42 余 2 个")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        arith_errors = [
            f for f in result.details.get("findings", []) if f["check_type"] == "arithmetic"
        ]
        assert len(arith_errors) == 1
        assert "余数错误" in arith_errors[0]["message"]


class TestInfoAccuracyLLM:
    """InfoAccuracyEvaluator 的 LLM Phase 3 路径测试。"""

    def _make_mock_record(self, judge_id="judge_ia_001", errors_found=None):
        """创建 mock JudgeRecord。"""
        rec = MagicMock()
        rec.judge_id = judge_id
        rec.provider_name = "deepseek_judge"
        rec.model = "deepseek-chat"
        rec.confidence = {"factual_correctness": "high", "statement_accuracy": "high"}
        rec.raw_response = {"errors_found": errors_found or []}
        return rec

    def _make_mock_orchestrator(self, scores, record, dims=None):
        """创建 mock JudgeOrchestrator。"""
        orch = MagicMock()
        orch.judge.return_value = (scores, record)

        mock_template = MagicMock()
        if dims is not None:
            mock_template.dimensions = dims
        else:
            # 默认 2 维度
            d1 = MagicMock(dim_id="factual_correctness", name="事实正确性", weight=0.6)
            d2 = MagicMock(dim_id="statement_accuracy", name="陈述准确性", weight=0.4)
            mock_template.dimensions = [d1, d2]
        orch.templates.get.return_value = mock_template
        return orch

    def _make_verdict_record(self, verdicts: list[dict], judge_id: str = "judge_fv_001"):
        """fact_verdict 的 mock JudgeRecord（parsed_scores 含 verdicts）。"""
        rec = MagicMock()
        rec.judge_id = judge_id
        rec.provider_name = "deepseek_judge"
        rec.model = "deepseek-chat"
        rec.confidence = {}
        rec.raw_response = ""
        rec.parsed_scores = {"verdict_quality": 9.0, "verdicts": verdicts}
        return rec

    def _make_dual_orchestrator(self, ia_result, fv_result):
        """两次 judge 调用（info_accuracy + fact_verdict）返回不同结果的 mock。

        fv_result 为 Exception 实例时，第二次 judge 抛该异常。
        """
        orch = MagicMock()
        orch.judge.side_effect = [ia_result, fv_result]
        ia_template = MagicMock()
        d1 = MagicMock(dim_id="factual_correctness", name="事实正确性", weight=0.6)
        d2 = MagicMock(dim_id="statement_accuracy", name="陈述准确性", weight=0.4)
        ia_template.dimensions = [d1, d2]
        orch.templates.get.return_value = ia_template
        return orch

    def test_llm_high_score_pass(self, tmp_path: Path) -> None:
        """LLM 高分 + 无规则错误 → PASS。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("圆周率 π ≈ 3.14，是数学中的重要常数。\n", encoding="utf-8")

        record = self._make_mock_record(errors_found=[])
        orch = self._make_mock_orchestrator(
            {"factual_correctness": 9.0, "statement_accuracy": 8.5}, record
        )

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(
            tmp_path,
            {
                "judge_orchestrator": orch,
                "evidence_dir": tmp_path / "evidence",
            },
        )

        assert result.status == EvalStatus.PASS
        assert result.score == 1.0
        assert result.judge_provider == "deepseek_judge"
        assert result.judge_model == "deepseek-chat"
        assert result.judge_record_path == "evidence/judge_ia_001.json"
        assert "LLM + 规则" in result.reason

    def test_llm_low_score_fail(self, tmp_path: Path) -> None:
        """LLM 低分 → FAIL（低于 pass_threshold 0.8）。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("一些教学内容\n", encoding="utf-8")

        record = self._make_mock_record(judge_id="judge_ia_002", errors_found=["信息不准确"])
        orch = self._make_mock_orchestrator(
            {"factual_correctness": 3.0, "statement_accuracy": 4.0}, record
        )

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(
            tmp_path,
            {
                "judge_orchestrator": orch,
                "evidence_dir": tmp_path / "evidence",
            },
        )

        assert result.status == EvalStatus.FAIL
        assert result.score == 0.0

    def test_llm_rule_errors_override(self, tmp_path: Path) -> None:
        """LLM 高分但规则检查有 error → FAIL。"""
        out = _prepare_output(tmp_path)
        # 包含算术错误，Phase 1 会发现 error
        (out / "doc.md").write_text("3 + 5 = 9\n", encoding="utf-8")

        record = self._make_mock_record(judge_id="judge_ia_003", errors_found=[])
        orch = self._make_mock_orchestrator(
            {"factual_correctness": 9.0, "statement_accuracy": 9.0}, record
        )

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(
            tmp_path,
            {
                "judge_orchestrator": orch,
                "evidence_dir": tmp_path / "evidence",
            },
        )

        # 规则有 error 即使 LLM 高分也 FAIL
        assert result.status == EvalStatus.FAIL
        assert result.score == 0.0
        assert "规则检查发现" in result.reason

    def test_constant_false_positive_filtered_by_llm(self, tmp_path: Path) -> None:
        """规则误报（金/信息密度误匹配"金的密度"）经 LLM 二次确认过滤 → PASS。"""
        out = _prepare_output(tmp_path)
        # 金(金字塔) + 密度(信息密度) + 数字 → 触发"金的密度"正则误报
        (out / "doc.html").write_text("倒金字塔结构，信息密度高。共6条。\n", encoding="utf-8")

        ia_record = self._make_mock_record(errors_found=[])
        fv_record = self._make_verdict_record(
            [{"index": 0, "is_real_error": False, "reason": "信息密度≠金的密度"}]
        )
        orch = self._make_dual_orchestrator(
            ({"factual_correctness": 10.0, "statement_accuracy": 10.0}, ia_record),
            ({"verdict_quality": 9.0}, fv_record),
        )

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(
            tmp_path,
            {"judge_orchestrator": orch, "evidence_dir": tmp_path / "evidence"},
        )

        assert result.status == EvalStatus.PASS
        assert orch.judge.call_count == 2  # info_accuracy + fact_verdict
        const = [f for f in result.details["findings"] if f.get("check_type") == "constant"]
        assert len(const) >= 1
        assert all(f.get("_llm_confirmed") is False for f in const)
        assert result.details["errors"] == 0  # 误报不计入一票否决

    def test_real_error_kept_by_llm(self, tmp_path: Path) -> None:
        """真错误（水的沸点错误）经 LLM 确认为真 → 仍 FAIL。"""
        out = _prepare_output(tmp_path)
        (out / "doc.html").write_text("水的沸点是 50 度。\n", encoding="utf-8")

        ia_record = self._make_mock_record(errors_found=[])
        fv_record = self._make_verdict_record(
            [{"index": 0, "is_real_error": True, "reason": "沸点应为100"}]
        )
        orch = self._make_dual_orchestrator(
            ({"factual_correctness": 10.0, "statement_accuracy": 10.0}, ia_record),
            ({"verdict_quality": 9.0}, fv_record),
        )

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(
            tmp_path,
            {"judge_orchestrator": orch, "evidence_dir": tmp_path / "evidence"},
        )

        assert result.status == EvalStatus.FAIL
        assert result.details["errors"] == 1

    def test_fact_verdict_failure_keeps_all(self, tmp_path: Path) -> None:
        """fact_verdict 调用异常 → 召回优先，error 全保留 → FAIL。"""
        out = _prepare_output(tmp_path)
        (out / "doc.html").write_text("水的沸点是 50 度。\n", encoding="utf-8")

        ia_record = self._make_mock_record(errors_found=[])
        orch = self._make_dual_orchestrator(
            ({"factual_correctness": 10.0, "statement_accuracy": 10.0}, ia_record),
            RuntimeError("fact_verdict timeout"),
        )

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(
            tmp_path,
            {"judge_orchestrator": orch, "evidence_dir": tmp_path / "evidence"},
        )

        assert result.status == EvalStatus.FAIL  # 召回优先
        assert result.details["errors"] == 1

    def test_no_error_skips_fact_verdict(self, tmp_path: Path) -> None:
        """无规则 error → fact_verdict 不被调用（0 额外 LLM 调用）。"""
        out = _prepare_output(tmp_path)
        (out / "doc.html").write_text("正常教学内容，无事实错误。\n", encoding="utf-8")

        ia_record = self._make_mock_record(errors_found=[])
        orch = self._make_mock_orchestrator(
            {"factual_correctness": 10.0, "statement_accuracy": 10.0}, ia_record
        )

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(
            tmp_path,
            {"judge_orchestrator": orch, "evidence_dir": tmp_path / "evidence"},
        )

        assert result.status == EvalStatus.PASS
        assert orch.judge.call_count == 1  # 仅 info_accuracy

    def test_info_accuracy_llm_decoupled_from_rule_findings(self, tmp_path: Path) -> None:
        """解耦：info_accuracy LLM 调用的 variables 不含规则可疑条目。

        规则 findings（含误报）由 fact_verdict 过滤后经 rule_errors 计分，
        不再注入 LLM 整体评分输入（避免污染，见 docs/arch/12 §3.4）。
        """
        out = _prepare_output(tmp_path)
        # 触发规则误报（金的密度式跨匹配：金 + 信息密度 + 数字）
        (out / "doc.html").write_text("倒金字塔结构，信息密度高。共6条。\n", encoding="utf-8")

        ia_record = self._make_mock_record(errors_found=[])
        fv_record = self._make_verdict_record(
            [{"index": 0, "is_real_error": False, "reason": "误报"}]
        )
        orch = self._make_dual_orchestrator(
            ({"factual_correctness": 10.0, "statement_accuracy": 10.0}, ia_record),
            ({"verdict_quality": 9.0}, fv_record),
        )

        ev = registry.create("commonsense.info_accuracy")
        ev.evaluate(
            tmp_path,
            {"judge_orchestrator": orch, "evidence_dir": tmp_path / "evidence"},
        )

        # 第一次 judge = info_accuracy 整体评分，其 variables 不应含规则 findings
        ia_variables = orch.judge.call_args_list[0].kwargs["variables"]
        assert "warnings" not in ia_variables
        assert "errors" not in ia_variables

    def test_llm_exception_fallback(self, tmp_path: Path) -> None:
        """LLM 调用异常 → 回退到 Phase 1-2 结果。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("正常教学内容\n", encoding="utf-8")

        orch = MagicMock()
        orch.judge.side_effect = RuntimeError("API timeout")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(
            tmp_path,
            {
                "judge_orchestrator": orch,
                "evidence_dir": tmp_path / "evidence",
            },
        )

        # 回退到 Phase 1-2，无错误 → PASS
        assert result.status == EvalStatus.PASS

    def test_llm_no_dimensions(self, tmp_path: Path) -> None:
        """无维度模板 → 使用简单平均。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("教学内容\n", encoding="utf-8")

        record = self._make_mock_record(judge_id="judge_ia_004", errors_found=[])
        orch = self._make_mock_orchestrator(
            {"a": 8.0, "b": 9.0},
            record,
            dims=[],  # 空维度
        )

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(
            tmp_path,
            {
                "judge_orchestrator": orch,
                "evidence_dir": tmp_path / "evidence",
            },
        )

        # (8+9)/2/10 = 0.85 >= 0.8 → PASS
        assert result.status == EvalStatus.PASS

    def test_llm_multi_file_truncation(self, tmp_path: Path) -> None:
        """多文件内容截断。"""
        out = _prepare_output(tmp_path)
        # 创建多个文件，总内容超过 max_content_chars
        for i in range(5):
            (out / f"doc_{i}.md").write_text("内容" * 2000, encoding="utf-8")

        record = self._make_mock_record(judge_id="judge_ia_005", errors_found=[])
        orch = self._make_mock_orchestrator(
            {"factual_correctness": 8.0, "statement_accuracy": 8.0}, record
        )

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(
            tmp_path,
            {
                "judge_orchestrator": orch,
                "evidence_dir": tmp_path / "evidence",
            },
        )

        assert result.status == EvalStatus.PASS


# ─── LogicalConsistency LLM 路径测试 ───


class TestLogicalConsistencyLLM:
    """LogicalConsistencyEvaluator 的 LLM 路径测试。"""

    def _make_mock_record(self, judge_id="judge_lc_001"):
        """创建 mock JudgeRecord。"""
        rec = MagicMock()
        rec.judge_id = judge_id
        rec.provider_name = "deepseek_judge"
        rec.model = "deepseek-chat"
        rec.confidence = {"internal_consistency": "high", "causal_logic": "high"}
        return rec

    def _make_mock_orchestrator(self, scores, record, dims=None):
        """创建 mock JudgeOrchestrator。"""
        orch = MagicMock()
        orch.judge.return_value = (scores, record)

        mock_template = MagicMock()
        if dims is not None:
            mock_template.dimensions = dims
        else:
            d1 = MagicMock(dim_id="internal_consistency", name="内部一致性", weight=0.4)
            d2 = MagicMock(dim_id="causal_logic", name="因果逻辑", weight=0.3)
            d3 = MagicMock(dim_id="classification_logic", name="分类逻辑", weight=0.3)
            mock_template.dimensions = [d1, d2, d3]
        orch.templates.get.return_value = mock_template
        return orch

    def test_llm_high_score_pass(self, tmp_path: Path) -> None:
        """LLM 高分 → PASS。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("教学" * 30, encoding="utf-8")

        record = self._make_mock_record()
        orch = self._make_mock_orchestrator(
            {"internal_consistency": 8.5, "causal_logic": 7.0, "classification_logic": 9.0},
            record,
        )

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(
            tmp_path,
            {
                "judge_orchestrator": orch,
                "evidence_dir": tmp_path / "evidence",
            },
        )

        assert result.status == EvalStatus.PASS
        assert result.score == 1.0
        assert result.judge_provider == "deepseek_judge"
        assert result.judge_model == "deepseek-chat"
        assert result.judge_record_path == "evidence/judge_lc_001.json"
        assert "LLM" in result.reason

    def test_llm_low_score_fail(self, tmp_path: Path) -> None:
        """LLM 低分（< 0.6）→ FAIL。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("教学" * 30, encoding="utf-8")

        record = self._make_mock_record(judge_id="judge_lc_002")
        orch = self._make_mock_orchestrator(
            {"internal_consistency": 2.0, "causal_logic": 3.0, "classification_logic": 2.0},
            record,
        )

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(
            tmp_path,
            {
                "judge_orchestrator": orch,
                "evidence_dir": tmp_path / "evidence",
            },
        )

        assert result.status == EvalStatus.FAIL
        assert result.score == 0.0

    def test_llm_exception_degrades_to_pass(self, tmp_path: Path) -> None:
        """LLM 调用异常 → 降级为 PASS。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("教学" * 30, encoding="utf-8")

        orch = MagicMock()
        orch.judge.side_effect = RuntimeError("Connection refused")

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(
            tmp_path,
            {
                "judge_orchestrator": orch,
                "evidence_dir": tmp_path / "evidence",
            },
        )

        assert result.status == EvalStatus.PASS
        assert "降级" in result.reason
        assert "Connection refused" in result.reason

    def test_llm_no_dimensions(self, tmp_path: Path) -> None:
        """无维度模板 → 使用简单平均。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("教学" * 30, encoding="utf-8")

        record = self._make_mock_record(judge_id="judge_lc_003")
        orch = self._make_mock_orchestrator(
            {"a": 7.0, "b": 8.0},
            record,
            dims=[],  # 空维度
        )

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(
            tmp_path,
            {
                "judge_orchestrator": orch,
                "evidence_dir": tmp_path / "evidence",
            },
        )

        # (7+8)/2/10 = 0.75 >= 0.6 → PASS
        assert result.status == EvalStatus.PASS
        assert result.score == 1.0

    def test_llm_borderline_score(self, tmp_path: Path) -> None:
        """LLM 分数恰好等于阈值 0.6 → PASS。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("教学" * 30, encoding="utf-8")

        record = self._make_mock_record(judge_id="judge_lc_004")
        # 维度加权恰好 0.6
        orch = self._make_mock_orchestrator(
            {"internal_consistency": 6.0, "causal_logic": 6.0, "classification_logic": 6.0},
            record,
        )

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(
            tmp_path,
            {
                "judge_orchestrator": orch,
                "evidence_dir": tmp_path / "evidence",
            },
        )

        assert result.status == EvalStatus.PASS

    def test_llm_content_truncation(self, tmp_path: Path) -> None:
        """超长内容被截断。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("内容" * 10000, encoding="utf-8")

        record = self._make_mock_record(judge_id="judge_lc_005")
        orch = self._make_mock_orchestrator(
            {"internal_consistency": 8.0, "causal_logic": 8.0, "classification_logic": 8.0},
            record,
        )

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(
            tmp_path,
            {
                "judge_orchestrator": orch,
                "evidence_dir": tmp_path / "evidence",
            },
        )

        assert result.status == EvalStatus.PASS
