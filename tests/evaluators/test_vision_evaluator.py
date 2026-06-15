"""VisionQualityEvaluator 测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from agent_eval.core.types import EvalMethod
from agent_eval.evaluation.evaluators.vision_evaluators import VisionQualityEvaluator


def _make_record(provider="kimi_vision", model="kimi-2.6") -> MagicMock:
    """构造 mock JudgeRecord。"""
    rec = MagicMock()
    rec.provider_name = provider
    rec.model = model
    rec.judge_id = "judge_vision.quality_20260615_010000"
    rec.confidence = {
        "layout": "high",
        "color_scheme": "high",
        "information_hierarchy": "high",
        "readability": "high",
    }
    rec.summary = "排版清晰、配色协调"
    return rec


class TestVisionQualityEvaluator:
    """VisionQualityEvaluator 测试。"""

    def test_metadata(self) -> None:
        """评估器元信息正确。"""
        ev = VisionQualityEvaluator()
        ev.setup({"llm_provider": "kimi_vision"})
        assert ev.evaluator_id == "vision.quality"
        assert ev.tier.value == "soft"
        assert ev.method == EvalMethod.VISION
        assert ev.template_id == "visual_quality"

    def test_degrade_no_orchestrator(self, tmp_path: Path) -> None:
        """无 judge_orchestrator 时降级 PASS/0.7。"""
        ev = VisionQualityEvaluator()
        result = ev.evaluate(tmp_path, context={})
        assert result.status.value == "pass"
        assert result.score == 0.7

    def test_degrade_no_renderer(self, tmp_path: Path) -> None:
        """有 orchestrator 但无 renderer 时降级。"""
        ev = VisionQualityEvaluator()
        result = ev.evaluate(
            tmp_path,
            context={"judge_orchestrator": MagicMock(), "evidence_dir": tmp_path / "ev"},
        )
        assert result.status.value == "pass"
        assert result.score == 0.7
        assert "渲染器" in result.reason

    def test_degrade_no_docs(self, tmp_path: Path) -> None:
        """无 HTML/Markdown 文档时降级。"""
        pkg = tmp_path / "pkg"
        (pkg / "output").mkdir(parents=True)  # 空 output
        ev = VisionQualityEvaluator()
        result = ev.evaluate(
            pkg,
            context={
                "judge_orchestrator": MagicMock(),
                "evidence_dir": tmp_path / "ev",
                "screenshot_renderer": MagicMock(),
            },
        )
        assert result.score == 0.7
        assert "文档" in result.reason

    def test_full_vision_eval(self, tmp_path: Path) -> None:
        """完整视觉评估：渲染 → judge(images=) → 归一化 + 溯源填充。"""
        # 准备样本 output 目录含一个 md 文档
        pkg = tmp_path / "pkg"
        out = pkg / "output"
        out.mkdir(parents=True)
        (out / "lesson.md").write_text("# 课程\n\n内容", encoding="utf-8")

        # mock renderer：返回一个真实存在的 PNG
        shot = tmp_path / "shot.png"
        shot.write_bytes(b"\x89PNG\r\n\x1a\n")

        renderer = MagicMock()
        renderer.render.return_value = [shot]

        # mock orchestrator：judge 返回 (scores, record)
        orchestrator = MagicMock()
        scores = {
            "layout": 8.0,
            "color_scheme": 7.0,
            "information_hierarchy": 9.0,
            "readability": 8.0,
        }
        orchestrator.judge.return_value = (scores, _make_record())

        ev = VisionQualityEvaluator()
        ev.setup({"llm_provider": "kimi_vision"})

        result = ev.evaluate(
            pkg,
            context={
                "judge_orchestrator": orchestrator,
                "evidence_dir": tmp_path / "ev",
                "screenshot_renderer": renderer,
                "sample_id": "s1",
                "task_input": {"title": "测试课程"},
            },
        )

        # judge 被调用，且传了 images
        orchestrator.judge.assert_called_once()
        call_kwargs = orchestrator.judge.call_args.kwargs
        assert call_kwargs["template_id"] == "visual_quality"
        assert call_kwargs["provider_name"] == "kimi_vision"
        images = call_kwargs["images"]
        assert len(images) == 1
        assert images[0].startswith("data:image/png;base64,")
        # 视觉变量（StrictUndefined 安全）
        assert call_kwargs["variables"]["title"] == "测试课程"
        assert call_kwargs["variables"]["num_documents"] == 1

        # 归一化得分：加权 (8*.3 + 7*.25 + 9*.25 + 8*.2)/1.0/10 = 0.8
        assert abs(result.score - 0.8) < 1e-6
        assert result.status.value == "pass"

        # 溯源填充
        assert result.judge_provider == "kimi_vision"
        assert result.judge_model == "kimi-2.6"
        assert result.judge_record_path == "evidence/judge_vision.quality_20260615_010000.json"
        # 截图路径进 details
        assert "screenshot_paths" in result.details
        assert len(result.details["screenshot_paths"]) == 1

    def test_render_failure_degrades(self, tmp_path: Path) -> None:
        """渲染失败时降级。"""
        pkg = tmp_path / "pkg"
        out = pkg / "output"
        out.mkdir(parents=True)
        (out / "a.md").write_text("# x", encoding="utf-8")

        renderer = MagicMock()
        renderer.render.side_effect = RuntimeError("browser crash")

        ev = VisionQualityEvaluator()
        result = ev.evaluate(
            pkg,
            context={
                "judge_orchestrator": MagicMock(),
                "evidence_dir": tmp_path / "ev",
                "screenshot_renderer": renderer,
            },
        )
        assert result.score == 0.7
        assert "渲染失败" in result.reason
