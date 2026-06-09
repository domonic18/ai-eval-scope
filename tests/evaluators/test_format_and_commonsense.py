"""格式评估器 + 常识评估器专项测试。

使用 tests/fixtures/golden/ 下的黄金样本验证评估器判定正确性。
"""

from pathlib import Path

from agent_eval.core.types import ConstraintTier, EvalStatus
from agent_eval.evaluation.evaluators import *  # trigger registration
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
