"""format.content_completeness 内容完整性门控测试。

覆盖：包内自适应阈值判定（占位命中 / 合法短页不误报 / 媒体豁免）、LLM 二次确认
（排除误报 / 确认空壳 / 异常降级保留规则判定）、边界（无文件 / 单文件跳过初筛）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent_eval.core.types import EvalStatus
from agent_eval.evaluation.evaluators.content_completeness import ContentCompletenessEvaluator


def _html(body: str, head: str = "") -> str:
    return (
        f"<!doctype html><html><head><meta charset='utf-8'>{head}</head><body>{body}</body></html>"
    )


def _page(title: str, paragraphs: int = 8) -> str:
    body = f"<h1>{title}</h1>" + "".join(
        f"<p>{title}的第{i}段教学内容，讲解定义、例题与练习，包含充分的知识信息。</p>"
        for i in range(paragraphs)
    )
    return _html(body)


# 复刻真实占位文件：格式合法、剥标签后正文约 79 字、无媒体元素
_PLACEHOLDER = _html(
    "<main><h1>该结构位置暂无内容</h1><p>模块 / 标签文件夹 / 文件</p>"
    "<p>这是系统为 AI 测评动态生成的占位文件。请将该位置判定为内容缺失。</p></main>"
)


def _make_package(tmp_path: Path, files: dict[str, str]) -> dict[str, str]:
    for rel, content in files.items():
        fp = tmp_path / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    return {"output_dir": str(tmp_path)}


def _evaluate(sample: dict, context: dict | None = None):
    ev = ContentCompletenessEvaluator()
    return ev.evaluate(sample, context or {})


# ─── 规则层（无 LLM orchestrator → 直接采用规则初筛结果）───


def test_placeholder_page_fails_gate(tmp_path):
    """占位文件正文量远低于包内中位数 → 门控 FAIL，reason 定位到具体文件。"""
    sample = _make_package(
        tmp_path,
        {
            "定义对比/正方体定义.html": _page("正方体定义", paragraphs=20),
            "定义对比/长方体定义.html": _page("长方体定义", paragraphs=18),
            "模块/空内容.html": _PLACEHOLDER,
        },
    )
    r = _evaluate(sample)
    assert r.status == EvalStatus.FAIL
    assert "模块/空内容.html" in r.reason
    assert r.details["empty_count"] == 1
    assert r.details["total_files"] == 3
    # 涉及文件联动（docs/arch/15）：空壳文件进 source_files
    assert {"filename": "模块/空内容.html"} in r.details["source_files"]


def test_normal_package_passes(tmp_path):
    sample = _make_package(
        tmp_path,
        {
            "a.html": _page("长方体定义", paragraphs=20),
            "b.html": _page("正方体定义", paragraphs=18),
        },
    )
    r = _evaluate(sample)
    assert r.status == EvalStatus.PASS
    assert r.details["empty_count"] == 0


def test_media_rich_short_page_exempt(tmp_path):
    """短正文但含表格/图片（图解型课件页）→ 媒体豁免，不判空。"""
    sample = _make_package(
        tmp_path,
        {
            "text.html": _page("长方体定义", paragraphs=20),
            "chart.html": _html("<h1>结构图解</h1><table><tr><td>面</td><td>6</td></tr></table>"),
        },
    )
    r = _evaluate(sample)
    assert r.status == EvalStatus.PASS
    assert r.details["empty_count"] == 0


def test_legal_short_cover_flagged_without_llm(tmp_path):
    """规则层宽召回：足够短的合法封面落入疑似区即 FAIL（召回优先，与 info_accuracy
    的 fact_verdict 降级语义一致）——合法短页与占位提示的语义区分交给 LLM 确认层。"""
    cover = _html("<h1>第一单元 长方体</h1><p>本单元学习长方体与正方体的认识。</p>")
    sample = _make_package(
        tmp_path,
        {
            "cover.html": cover,
            "p1.html": _page("长方体定义", paragraphs=6),
            "p2.html": _page("正方体定义", paragraphs=7),
        },
    )
    r = _evaluate(sample)
    assert r.status == EvalStatus.FAIL
    assert "cover.html" in r.reason


def test_llm_filters_legal_short_cover(tmp_path):
    """完整链路：合法短封面被规则初筛命中后，经 LLM 裁定排除 → 不 FAIL。"""
    cover = _html("<h1>第一单元 长方体</h1><p>本单元学习长方体与正方体的认识。</p>")
    sample = _make_package(
        tmp_path,
        {
            "cover.html": cover,
            "p1.html": _page("长方体定义", paragraphs=6),
            "p2.html": _page("正方体定义", paragraphs=7),
        },
    )
    ctx = _llm_context(
        tmp_path, [{"index": 0, "is_empty": False, "reason": "单元封面页，含标题与导语"}]
    )
    r = _evaluate(sample, ctx)
    assert r.status == EvalStatus.PASS
    assert r.details["empty_count"] == 0


def test_no_content_files_fails(tmp_path):
    (tmp_path / "asset.bin").write_bytes(b"\x00\x01")
    r = _evaluate({"output_dir": str(tmp_path)})
    assert r.status == EvalStatus.FAIL
    assert "无内容文件" in r.reason


def test_single_text_file_skips_screening(tmp_path):
    """单文件包无法稳健估计包内典型水平 → 放行（宁缺毋滥，软分兜底）。"""
    sample = _make_package(tmp_path, {"only.html": _PLACEHOLDER})
    r = _evaluate(sample)
    assert r.status == EvalStatus.PASS
    assert r.details["adaptive_threshold"] is None


# ─── LLM 二次确认 ───


def _llm_context(tmp_path: Path, verdicts: list[dict] | None, *, error: bool = False):
    record = SimpleNamespace(parsed_scores={"verdicts": verdicts or []})

    def _judge(**kw):
        if error:
            raise RuntimeError("llm down")
        return {"verdict_quality": 9.0}, record

    orchestrator = SimpleNamespace(judge=_judge)
    return {
        "judge_orchestrator": orchestrator,
        "evidence_dir": tmp_path / "evidence",
        "task_input": {"title": "长方体", "subject": "数学"},
    }


def _suspect_package(tmp_path: Path) -> dict:
    return _make_package(
        tmp_path,
        {
            "p1.html": _page("长方体定义", paragraphs=20),
            "p2.html": _page("正方体定义", paragraphs=18),
            "模块/空内容.html": _PLACEHOLDER,
        },
    )


def test_llm_verdict_filters_false_positive(tmp_path):
    """LLM 裁定疑似文件实为合法短页（is_empty=false）→ 不 FAIL。"""
    sample = _suspect_package(tmp_path)
    ctx = _llm_context(
        tmp_path, [{"index": 0, "is_empty": False, "reason": "封面页，含单元标题与导语"}]
    )
    r = _evaluate(sample, ctx)
    assert r.status == EvalStatus.PASS
    assert r.details["verified_by_llm"] is True
    assert r.details["empty_count"] == 0


def test_llm_verdict_confirms_empty(tmp_path):
    """LLM 确认占位（is_empty=true）→ FAIL，reason 携带 LLM 依据。"""
    sample = _suspect_package(tmp_path)
    ctx = _llm_context(
        tmp_path,
        [{"index": 0, "is_empty": True, "reason": "仅为占位提示文字，无教学内容"}],
    )
    r = _evaluate(sample, ctx)
    assert r.status == EvalStatus.FAIL
    assert "无教学内容" in r.details["empty_files"][0]["reason"]


def test_llm_failure_falls_back_to_rule(tmp_path):
    """LLM 调用异常 → 保留规则判定（召回优先）。"""
    sample = _suspect_package(tmp_path)
    ctx = _llm_context(tmp_path, None, error=True)
    r = _evaluate(sample, ctx)
    assert r.status == EvalStatus.FAIL
    assert r.details["verified_by_llm"] is False


def test_max_empty_ratio_tolerance(tmp_path):
    """容忍比例放宽（max_empty_ratio=0.5）→ 1/3 空壳未超限 → PASS。"""
    sample = _suspect_package(tmp_path)
    ev = ContentCompletenessEvaluator()
    ev.setup({"max_empty_ratio": 0.5})
    r = ev.evaluate(sample, {})
    assert r.status == EvalStatus.PASS
    assert "未超过容忍比例" in r.reason
