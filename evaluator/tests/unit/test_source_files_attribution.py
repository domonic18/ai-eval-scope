"""评估器 source_files 文件定位（docs/arch/15 §4.1）。

P1：format（B 档）/ commonsense.info_accuracy（A 档）/ vision.quality（A 档）
在 details.source_files 产出相对路径，供前端「涉及文件」chip 联动切换预览。
"""

from __future__ import annotations

from pathlib import Path

from agent_eval.evaluation.evaluators.commonsense_evaluators import (
    InfoAccuracyEvaluator,
)
from agent_eval.evaluation.evaluators.format_evaluators import (
    HtmlValidityEvaluator,
    ResponseFormatEvaluator,
)
from agent_eval.evaluation.evaluators.quality_evaluators import _aggregate_source_files
from agent_eval.evaluation.evaluators.vision_evaluators import (
    VisionQualityEvaluator,
)
from agent_eval.evaluation.text_utils import collect_text_content_with_markers

# ─── format.response_format（B 档：相对路径，非 basename）───


def test_response_format_source_files_relative_paths(tmp_path: Path) -> None:
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "lesson.html").write_text("<html><body>hi</body></html>")
    (tmp_path / "output" / "sub").mkdir()
    (tmp_path / "output" / "sub" / "notes.md").write_text("# notes")

    cr = ResponseFormatEvaluator().evaluate(tmp_path, {})

    files = {sf["filename"] for sf in cr.details["source_files"]}
    assert "lesson.html" in files
    assert "sub/notes.md" in files  # 相对路径（含子目录），非 basename


def test_response_format_source_files_on_fail(tmp_path: Path) -> None:
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "bad.txt").write_text("not a doc")

    cr = ResponseFormatEvaluator().evaluate(tmp_path, {})

    assert cr.details["source_files"] == [{"filename": "bad.txt"}]


# ─── format.html_validity（B 档）───


def test_html_validity_source_files_relative_paths(tmp_path: Path) -> None:
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "a.html").write_text("<html></html>")
    (tmp_path / "output" / "deep").mkdir()
    (tmp_path / "output" / "deep" / "b.html").write_text("<html><body>x</body></html>")

    cr = HtmlValidityEvaluator().evaluate(tmp_path, {})

    files = {sf["filename"] for sf in cr.details["source_files"]}
    assert files == {"a.html", "deep/b.html"}


# ─── commonsense.info_accuracy（A 档：findings[].file 聚合）───


def test_info_accuracy_source_files_from_findings() -> None:
    ev = InfoAccuracyEvaluator()
    file_texts = {"a.html": "内容", "sub/b.md": "内容"}
    findings = [
        {"file": "a.html", "severity": "error"},
        {"file": "sub/b.md", "severity": "warning"},
    ]

    cr = ev._compute_result(file_texts, findings, start=0.0, checks_total=2)

    files = {sf["filename"] for sf in cr.details["source_files"]}
    assert files == {"a.html", "sub/b.md"}  # 去重 + 保留相对路径


def test_info_accuracy_source_files_empty_when_no_findings() -> None:
    ev = InfoAccuracyEvaluator()
    cr = ev._compute_result({"a.html": "x"}, [], start=0.0, checks_total=0)
    # PASS（无 findings）时 source_files 为空 → 前端降级不显示 chip
    assert cr.details["source_files"] == []


# ─── vision.quality（A 档：per_document.doc_path → artifact_kind=shot）───


def test_vision_source_files_from_per_doc() -> None:
    ev = VisionQualityEvaluator()
    per_doc = [
        {
            "doc_name": "a",
            "doc_path": "dir/a.html",
            "ok": True,
            "scores": {},
            "screenshot": "a.png",
        },
        {
            "doc_name": "b",
            "doc_path": "b.html",
            "ok": True,
            "scores": {},
            "screenshot": "b.png",
        },
    ]

    cr = ev._build_vision_result(per_doc, screenshots=[], total_docs=2, elapsed=0.0)

    sfs = cr.details["source_files"]
    assert {sf["filename"] for sf in sfs} == {"dir/a.html", "b.html"}
    # vision 联动目标是截图
    assert all(sf["artifact_kind"] == "shot" for sf in sfs)


# ─── P2: C 档（soft/pref）合并文本标记 + involved_files 聚合 ───


def test_collect_text_content_with_markers(tmp_path: Path) -> None:
    out = tmp_path / "output"
    out.mkdir()
    (out / "a.md").write_text("内容A")
    (out / "sub").mkdir()
    (out / "sub" / "b.html").write_text("<html>x</html>")

    text = collect_text_content_with_markers(out)

    assert "=== FILE: a.md ===" in text
    assert "=== FILE: sub/b.html ===" in text  # 相对路径标记
    assert "内容A" in text


def test_aggregate_source_files_filters_hallucination() -> None:
    dims = [
        {"issues": [{"involved_files": ["a.html", "sub/b.md"]}, {"involved_files": ["a.html"]}]},
        {"issues": [{"involved_files": ["c.html", "ghost.html"]}]},  # ghost 不在 manifest
    ]
    manifest = {
        "modules": [{"children": [{"path": "a.html"}, {"path": "sub/b.md"}, {"path": "c.html"}]}]
    }
    sfs = _aggregate_source_files(dims, {"directory_manifest": manifest})
    # 去重 + 过滤幻觉文件名 ghost.html
    assert {sf["filename"] for sf in sfs} == {"a.html", "sub/b.md", "c.html"}


def test_aggregate_source_files_no_manifest_keeps_all() -> None:
    dims = [{"issues": [{"involved_files": ["x.html", "y.md"]}]}]
    sfs = _aggregate_source_files(dims, {})  # 无 manifest → 不过滤
    assert {sf["filename"] for sf in sfs} == {"x.html", "y.md"}


def test_aggregate_source_files_empty() -> None:
    assert _aggregate_source_files(None, {}) == []
    assert _aggregate_source_files([{"issues": []}], {}) == []


def test_aggregate_source_files_basename_resolved() -> None:
    # 判官常只给基名 → 归一为 manifest 中的全路径
    dims = [{"issues": [{"involved_files": ["建构性导学.html"]}]}]
    manifest = {"modules": [{"children": [{"path": "M1/建构性导学/建构性导学.html"}]}]}
    sfs = _aggregate_source_files(dims, {"directory_manifest": manifest})
    assert sfs == [{"filename": "M1/建构性导学/建构性导学.html"}]
