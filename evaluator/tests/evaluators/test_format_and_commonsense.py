"""格式评估器 + 常识评估器专项测试。

使用 tests/fixtures/golden/ 下的黄金样本验证评估器判定正确性。
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_eval.core.types import ConstraintTier, EvalStatus
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


# ─── 常识评估器 ───


class TestMathFormulaEvaluator:
    def test_correct_arithmetic(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("计算 2+3=5 和 10×2=20。")

        ev = registry.create("commonsense.math_formula")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS

    def test_wrong_arithmetic(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "wrong.md").write_text("2+3=6 是正确的。")

        ev = registry.create("commonsense.math_formula")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL

    def test_multi_term_no_false_positive(self, tmp_path: Path) -> None:
        """多项表达式不应产生子表达式误报。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text(
            "总数：24 + 32 + 27 = 83 本\n"
            "总分：42 + 38 + 45 = 125 分\n"
            "检验：268+145+87=500\n"
            "验证：28×8 + 22×9 + 35×4 = 224 + 198 + 140 = 562元\n"
        )

        ev = registry.create("commonsense.math_formula")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS, (
            f"多项表达式不应产生误报: {result.details.get('errors')}"
        )

    def test_multi_term_error_detected(self, tmp_path: Path) -> None:
        """多项表达式错误应被检测。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("方案：12×2 + 7 + 3 + 5 + 18 = 100 元")

        ev = registry.create("commonsense.math_formula")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL
        assert any("57" in e for e in result.details["errors"])

    def test_per_file_attribution(self, tmp_path: Path) -> None:
        """错误应携带文件名归属。"""
        out = _prepare_output(tmp_path)
        (out / "good.md").write_text("2+3=5")
        (out / "bad.md").write_text("5+3=9")

        ev = registry.create("commonsense.math_formula")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL
        assert any("bad.md" in e for e in result.details["errors"])
        assert not any("good.md" in e for e in result.details["errors"])

    # ─── 符号公式校验 ───

    def test_correct_circle_area(self, tmp_path: Path) -> None:
        """正确的圆面积公式 → PASS。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("圆的面积 S=πr²")

        ev = registry.create("commonsense.math_formula")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS

    def test_wrong_circle_area(self, tmp_path: Path) -> None:
        """圆面积用了周长公式 2πr → FAIL。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("圆的面积 S=2πr")

        ev = registry.create("commonsense.math_formula")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL
        assert any("圆" in e for e in result.details["errors"])

    def test_triangle_missing_half(self, tmp_path: Path) -> None:
        """三角形面积缺少 ½ → FAIL。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("三角形面积 S=ah")

        ev = registry.create("commonsense.math_formula")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL

    def test_correct_rectangle_area(self, tmp_path: Path) -> None:
        """正确的长方形面积公式 → PASS。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("长方形面积=长×宽")

        ev = registry.create("commonsense.math_formula")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS

    def test_unknown_formula_not_flagged(self, tmp_path: Path) -> None:
        """未知公式名不应产生误报。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("特殊五边形面积=S=3ab")

        ev = registry.create("commonsense.math_formula")
        result = ev.evaluate(tmp_path, {})
        # 无匹配的 domain_facts 条目 → 不报错
        assert result.status == EvalStatus.PASS

    def test_formula_in_html(self, tmp_path: Path) -> None:
        """HTML 中的公式应被检测。"""
        out = _prepare_output(tmp_path)
        (out / "page.html").write_text("<p>圆的面积公式是：S=2πr</p>")

        ev = registry.create("commonsense.math_formula")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL


class TestUnitConsistencyEvaluator:
    def test_correct_units(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "physics.md").write_text("浮力公式 F = ρ液 × g × V_排，其中 g = 9.8 m/s²")

        ev = registry.create("commonsense.unit_consistency")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS

    def test_wrong_g_unit(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "wrong.md").write_text("g = 9.8 m/s")

        ev = registry.create("commonsense.unit_consistency")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL


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


class TestChronologicalOrderEvaluator:
    """时序正确性检查评估器测试。

    当前实现为空壳（始终 PASS），测试验证：
    1. 提取逻辑的正确性（years_found、sequences_found）
    2. 文档行为的稳定性（始终 PASS）
    3. 已知局限（年份误提取、序号不校验递增）
    """

    def test_pass_correct_year_order(self, tmp_path: Path) -> None:
        """年份递增出现 → PASS，details 含正确年份列表。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("1949年新中国成立。1978年改革开放。2001年加入WTO。")

        ev = registry.create("commonsense.chronological_order")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS
        assert result.score == 1.0
        assert result.details["years_found"] == [1949, 1978, 2001]

    def test_pass_year_regression_not_reported(self, tmp_path: Path) -> None:
        """年份回溯（如回顾历史）→ 仍然 PASS（空实现，暂不报告）。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("1978年改革开放。回顾1949年新中国成立。")

        ev = registry.create("commonsense.chronological_order")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS
        assert result.details["years_found"] == [1978, 1949]

    def test_pass_no_years(self, tmp_path: Path) -> None:
        """无年份 → PASS，years_found 为空。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("这是一段没有年份的文本。")

        ev = registry.create("commonsense.chronological_order")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS
        assert result.details["years_found"] == []

    def test_sequences_found(self, tmp_path: Path) -> None:
        """序号提取应统计数量。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("第一步：准备材料。\n第二步：开始实验。\n第三步：记录结果。")

        ev = registry.create("commonsense.chronological_order")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS
        assert result.details["sequences_found"] >= 3

    def test_mixed_chinese_arabic_sequences(self, tmp_path: Path) -> None:
        """混合中/阿拉伯数字序号（第一步 → 第4步）仍 PASS，但应被提取。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("第一步：准备。\n第4步：重新检查。")

        ev = registry.create("commonsense.chronological_order")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS
        # 至少提取到 2 个序号
        assert result.details["sequences_found"] >= 2

    def test_duration_not_extracted_as_year(self, tmp_path: Path) -> None:
        """\"100年后\" 不应被提取为年份 100。

        这是当前实现的已知局限——正则 `(?:公元)?(\\d{3,4})\\s*年`
        会将 \"100年后\" 匹配为 year=100。
        当修复后此测试应断言 100 不在 years_found 中。
        """
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("科学家预测100年后气温上升2-4摄氏度。")

        ev = registry.create("commonsense.chronological_order")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS
        # 已知局限：当前会错误提取 "100年后" 为 year=100
        # 修复后改为: assert 100 not in result.details["years_found"]
        assert 100 not in result.details["years_found"], "「100年后」是时间段而非年份，不应被提取。"

    def test_details_structure(self, tmp_path: Path) -> None:
        """details 应包含标准字段。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("1949年新中国成立。第一步：准备。")

        ev = registry.create("commonsense.chronological_order")
        result = ev.evaluate(tmp_path, {})
        assert "files_checked" in result.details
        assert "years_found" in result.details
        assert "sequences_found" in result.details
        assert "content_length" in result.details

    def test_fail_empty_content(self, tmp_path: Path) -> None:
        """空文档内容 → FAIL。"""
        out = _prepare_output(tmp_path)
        (out / "empty.md").write_text("   ")

        ev = registry.create("commonsense.chronological_order")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL
        assert result.score == 0.0

    def test_fail_no_output_dir(self, tmp_path: Path) -> None:
        """无 output 目录 → FAIL。"""
        ev = registry.create("commonsense.chronological_order")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL
        assert result.score == 0.0

    def test_html_tags_stripped(self, tmp_path: Path) -> None:
        """HTML 标签应被去除后再提取年份。"""
        out = _prepare_output(tmp_path)
        (out / "page.html").write_text("<html><body><p>1949年</p><p>1978年</p></body></html>")

        ev = registry.create("commonsense.chronological_order")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS
        assert 1949 in result.details["years_found"]
        assert 1978 in result.details["years_found"]

    def test_year_filtering_range(self, tmp_path: Path) -> None:
        """年份应在 (0, 2100] 范围内；超出范围的数字不提取。
        同时验证持续时间模式（N年后/历史/内/间）不提取。
        """
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("99999年代码量。100年后气温上升。500年历史。1949年新中国。")

        ev = registry.create("commonsense.chronological_order")
        result = ev.evaluate(tmp_path, {})
        # 99999 > 2100 → 不提取
        assert 99999 not in result.details["years_found"]
        # 100年后 → 时间段，不提取
        assert 100 not in result.details["years_found"]
        # 500年历史 → 时间段，不提取
        assert 500 not in result.details["years_found"]
        # 1949 在范围内 → 提取
        assert 1949 in result.details["years_found"]

    def test_reference_courseware_years(self, tmp_path: Path) -> None:
        """模拟参考课件中的年份提取结果。

        参考 docs/reference/大单元学习总导 中出现的年份：
        1966（陈景润）、2013（教材版本，×2）、2050（虚构场景）。
        "100年后"不应被提取。
        """
        out = _prepare_output(tmp_path)
        (out / "doc.html").write_text(
            "在1966年取得了关键突破。"
            "年级：三年级上（2013年版）。"
            "2050年，你成为了一名城市设计师。"
            "科学家预测100年后气温上升2-4摄氏度。"
        )

        ev = registry.create("commonsense.chronological_order")
        result = ev.evaluate(tmp_path, {})
        years = result.details["years_found"]

        # 应提取的正确年份
        assert 1966 in years, "陈景润年份 1966 应被提取"
        assert 2013 in years, "教材版本年份 2013 应被提取"
        assert 2050 in years, "虚构场景年份 2050 应被提取"

        # 已知局限：100 不应被提取（修复后验证）
        assert 100 not in years, "「100年后」是时间段而非年份，不应被提取"


class TestLogicalConsistencyEvaluator:
    """逻辑一致性检查评估器测试 — Rule-based 降级模式。

    验证：
    1. 算术表达式不误判为变量矛盾
    2. 真正的变量赋值矛盾能被检测
    3. 跨文件变量不互相比较
    4. details 包含文件归属和上下文
    """

    def test_default_pass(self, tmp_path: Path) -> None:
        """无变量赋值模式 → PASS。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("Some content.")

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS
        assert result.tier == ConstraintTier.HARD_SCORE

    def test_arithmetic_not_false_positive(self, tmp_path: Path) -> None:
        """算术表达式（24+8=32、83-47=36）不应产生变量矛盾。

        旧正则将纯数字（"8""47"）当作变量名，产生 28 处假阳性。
        新正则只匹配具名变量（字母/中文开头），排除纯数字。
        """
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text(
            "计算：24 + 8 = 32 本\n"
            "验算：83 - 47 = 36\n"
            "验证：101 × 50 = 5050\n"
            "竖式：个位 7+9=16，写6进1；十位 6+8+1=15\n"
        )

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS, (
            f"算术表达式不应产生假阳性: {result.details.get('errors')}"
        )

    def test_chinese_equal_not_split(self, tmp_path: Path) -> None:
        """\"等于\" 不应被拆为 \"变量等=值\"。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("十位 4加5等于10，写0进1。\n百位 2加1等于4。\n")

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS

    def test_real_variable_contradiction(self, tmp_path: Path) -> None:
        """同一文件中具名变量赋值矛盾应被检测。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("总面积=567平方米。\n根据计算，总面积=658平方米。\n")

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL
        findings = result.details.get("findings", [])
        assert len(findings) > 0
        assert any("总面积" in f.get("variable", "") for f in findings)

    def test_cross_file_no_false_positive(self, tmp_path: Path) -> None:
        """不同文件中同名变量不应互相比较。"""
        out = _prepare_output(tmp_path)
        (out / "a.md").write_text("总价 = 350 元")
        (out / "b.md").write_text("总价 = 500 元")

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS, "不同文件中的同名变量不应被当作矛盾"

    def test_same_file_contradiction_detected(self, tmp_path: Path) -> None:
        """同一文件中同名变量不同值应被检测。"""
        out = _prepare_output(tmp_path)
        (out / "a.md").write_text("方案一：总价 = 350 元\n方案二：总价 = 500 元")

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL

    def test_details_have_file_attribution(self, tmp_path: Path) -> None:
        """findings 应包含 file 字段和 contexts。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("学生数=45人。学生数=50人。")

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL
        findings = result.details.get("findings", [])
        assert len(findings) > 0
        f = findings[0]
        assert "file" in f
        assert "variable" in f
        assert "values" in f
        assert "contexts" in f

    def test_short_ascii_vars_skipped(self, tmp_path: Path) -> None:
        """单字母变量（如 x=1, x=2）应被跳过（数学公式常见）。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("设 x=5。方程 x=10 的解。")

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS

    def test_chinese_named_var_detected(self, tmp_path: Path) -> None:
        """中文命名的变量赋值矛盾应被检测。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("三年级一班有学生数=42人。\n但实际上学生数=45人。\n")

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL
        findings = result.details.get("findings", [])
        assert any("学生数" in f.get("variable", "") for f in findings)

    def test_reference_courseware_no_false_positive(self, tmp_path: Path) -> None:
        """参考课件中的算术内容不应产生假阳性。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text(
            "示例：算完36+47=83后，估算80左右合理，用83-47=36验证正确。\n"
            "方案一：18 + 12 + 7 + 3 + 5 = 45 元\n"
            "最优方案：12×2 + 7 + 3 + 5 + 18 = 100 元\n"
            "101×50=5050。高斯配对法。\n"
            "竖式：个位3+8=11，写1进1；十位2+1+1=4\n"
        )

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS, (
            f"参考课件算术内容不应产生假阳性: {result.details.get('errors')}"
        )

    def test_fail_no_output_dir(self, tmp_path: Path) -> None:
        """无 output 目录 → FAIL。"""
        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL
        assert result.score == 0.0

    def test_fail_empty_content(self, tmp_path: Path) -> None:
        """空文档 → FAIL。"""
        out = _prepare_output(tmp_path)
        (out / "empty.md").write_text("   ")

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL
        assert result.score == 0.0


# ─── InfoAccuracy LLM Phase 3 测试 ───


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
