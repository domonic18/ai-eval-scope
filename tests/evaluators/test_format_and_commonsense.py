"""格式评估器 + 常识评估器专项测试。

使用 tests/fixtures/golden/ 下的黄金样本验证评估器判定正确性。
"""

from pathlib import Path

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


class TestDocumentCountEvaluator:
    def test_count_within_range(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        for i in range(5):
            (out / f"doc_{i}.md").write_text(f"# Doc {i}")

        ev = registry.create("format.document_count", {"min": 1, "max": 10})
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS

    def test_count_too_few(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "only.md").write_text("# Only")

        ev = registry.create("format.document_count", {"min": 3, "max": 10})
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL
        assert result.score == 0.0

    def test_count_too_many(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        for i in range(25):
            (out / f"doc_{i}.md").write_text(f"# Doc {i}")

        ev = registry.create("format.document_count", {"min": 1, "max": 20})
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL


class TestStructureComplianceEvaluator:
    def test_valid_md_structure(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "index.md").write_text(
            "# Title\n\n## Section 1\n\n### Subsection\n\n## Section 2\n"
        )

        ev = registry.create("format.structure_compliance", {"max_heading_depth": 4})
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS

    def test_heading_too_deep(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "deep.md").write_text(
            "# H1\n## H2\n### H3\n#### H4\n##### H5\n###### H6\n"
        )

        ev = registry.create("format.structure_compliance", {"max_heading_depth": 4})
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL

    def test_no_headings(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "flat.md").write_text("Just some text without any headings.")

        ev = registry.create("format.structure_compliance")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL

    def test_valid_html_structure(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "index.html").write_text(
            "<html><body><h1>Title</h1><h2>Section</h2></body></html>"
        )

        ev = registry.create("format.structure_compliance", {"max_heading_depth": 4})
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS


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


class TestDirectoryStructureEvaluator:
    def test_flat_mode_skips(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "index.md").write_text("# Doc")

        ev = registry.create("format.directory_structure")
        result = ev.evaluate(tmp_path, {})  # 无 manifest
        assert result.status == EvalStatus.PASS
        assert result.score == 1.0

    def test_directory_mode_pass(self, tmp_path: Path) -> None:
        import json

        output = tmp_path / "output"
        output.mkdir()
        (output / "_manifest.json").write_text(json.dumps({
            "mode": "directory",
            "total_files": 4,
            "hierarchy_depth": 3,
            "modules": [
                {"name": "M1", "path": "M1/", "file_count": 2},
                {"name": "M2", "path": "M2/", "file_count": 2},
            ],
        }))

        ev = registry.create("format.directory_structure")
        result = ev.evaluate(tmp_path, {
            "constraints": {"expected_modules": 2, "hierarchy_depth": 5},
        })
        assert result.status == EvalStatus.PASS

    def test_directory_mode_wrong_module_count(self, tmp_path: Path) -> None:
        import json

        output = tmp_path / "output"
        output.mkdir()
        (output / "_manifest.json").write_text(json.dumps({
            "mode": "directory",
            "total_files": 2,
            "hierarchy_depth": 2,
            "modules": [
                {"name": "M1", "path": "M1/", "file_count": 2},
            ],
        }))

        ev = registry.create("format.directory_structure")
        result = ev.evaluate(tmp_path, {
            "constraints": {"expected_modules": 3},
        })
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


class TestUnitConsistencyEvaluator:
    def test_correct_units(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "physics.md").write_text(
            "浮力公式 F = ρ液 × g × V_排，其中 g = 9.8 m/s²"
        )

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

        ev = registry.create("commonsense.info_accuracy", {
            "fact_rules": [
                {"type": "must_contain", "keyword": "阿基米德"},
            ],
        })
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.FAIL

    def test_must_not_contain_rule(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("# 浮力\n\n浮力等于物体的重量。")

        ev = registry.create("commonsense.info_accuracy", {
            "fact_rules": [
                {"type": "must_not_contain", "pattern": "浮力等于物体的重量"},
            ],
        })
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
        (out / "math.md").write_text(
            "竖式计算：个位 7+9=16，写6进1；十位 3+2+1=6，结果是 67。"
        )

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
        ev = registry.create("commonsense.info_accuracy", {
            "fact_rules": [
                {"type": "regex_match", "pattern": r"圆周率", "must_match": True, "name": "圆周率提及"},
            ],
        })
        result = ev.evaluate(tmp_path, {})
        findings = result.details.get("findings", [])
        rule_errors = [f for f in findings if f.get("rule_type") == "regex_match"]
        assert len(rule_errors) == 0

    def test_regex_match_not_found(self, tmp_path: Path) -> None:
        """regex_match must_match=True 但未找到 → 报错。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("这是一个简单的文档。")

        ev = registry.create("commonsense.info_accuracy", {
            "fact_rules": [
                {"type": "regex_match", "pattern": r"圆周率", "must_match": True, "name": "圆周率提及"},
            ],
        })
        result = ev.evaluate(tmp_path, {})
        findings = result.details.get("findings", [])
        rule_errors = [f for f in findings if f.get("rule_type") == "regex_match"]
        assert len(rule_errors) > 0

    def test_number_in_context_rule(self, tmp_path: Path) -> None:
        """number_in_context 规则应检查关键词附近数值。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("圆周率的近似值是3.20")

        ev = registry.create("commonsense.info_accuracy", {
            "fact_rules": [
                {"type": "number_in_context", "keyword": "圆周率", "min": 3.14, "max": 3.15, "name": "圆周率数值"},
            ],
        })
        result = ev.evaluate(tmp_path, {})
        findings = result.details.get("findings", [])
        ctx_errors = [f for f in findings if f.get("rule_type") == "number_in_context"]
        assert len(ctx_errors) > 0

    def test_forbidden_pattern_rule(self, tmp_path: Path) -> None:
        """forbidden_pattern 规则应检测禁止模式。"""
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("祖冲之是唐朝最伟大的数学家。")

        ev = registry.create("commonsense.info_accuracy", {
            "fact_rules": [
                {"type": "forbidden_pattern", "pattern": r"祖冲之.*唐朝", "reason": "祖冲之非唐朝人"},
            ],
        })
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
            "总花费：3 + 2 + 15 = 20 元\n"
            "总数：24 + 32 + 27 = 83 本\n"
            "总分：42 + 38 + 45 = 125 分"
        )

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS
        arith_errors = [
            f for f in result.details.get("findings", [])
            if f["check_type"] == "arithmetic"
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
            f for f in result.details.get("findings", [])
            if f["check_type"] == "arithmetic"
        ]
        assert len(arith_errors) == 1
        assert "57" in arith_errors[0]["message"]

    def test_chained_equation_correct(self, tmp_path: Path) -> None:
        """链式等式（A = B + C = D）应只验证最终结果。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text(
            "验证：28×8 + 22×9 + 35×4 = 224 + 198 + 140 = 562元"
        )

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        arith_errors = [
            f for f in result.details.get("findings", [])
            if f["check_type"] == "arithmetic"
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
            f for f in result.details.get("findings", [])
            if f["check_type"] == "arithmetic"
        ]
        assert len(arith_errors) == 0

    def test_division_with_remainder_correct(self, tmp_path: Path) -> None:
        """带余数除法（125 ÷ 3 = 41 余 2）应正确验证。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("平均每分钟：125 ÷ 3 = 41 余 2 个")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        arith_errors = [
            f for f in result.details.get("findings", [])
            if f["check_type"] == "arithmetic"
        ]
        assert len(arith_errors) == 0

    def test_division_with_remainder_error(self, tmp_path: Path) -> None:
        """带余数除法计算错误应被检测。"""
        out = _prepare_output(tmp_path)
        (out / "math.md").write_text("平均每分钟：125 ÷ 3 = 42 余 2 个")

        ev = registry.create("commonsense.info_accuracy")
        result = ev.evaluate(tmp_path, {})
        arith_errors = [
            f for f in result.details.get("findings", [])
            if f["check_type"] == "arithmetic"
        ]
        assert len(arith_errors) == 1
        assert "余数错误" in arith_errors[0]["message"]


class TestChronologicalOrderEvaluator:
    def test_pass(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("# 历史\n\n1949年新中国成立。1978年改革开放。")

        ev = registry.create("commonsense.chronological_order")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS


class TestLogicalConsistencyEvaluator:
    def test_default_pass(self, tmp_path: Path) -> None:
        out = _prepare_output(tmp_path)
        (out / "doc.md").write_text("Some content.")

        ev = registry.create("commonsense.logical_consistency")
        result = ev.evaluate(tmp_path, {})
        assert result.status == EvalStatus.PASS
        assert result.tier == ConstraintTier.HARD_SCORE
