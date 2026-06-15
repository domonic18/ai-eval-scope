"""视觉评估在级联管线中的集成测试。

验证：vision.quality 在 quality 阶段运行，截图落 evidence，溯源填充，
s_soft 按显式 soft_weights（含 vision.quality）正确聚合。
为聚焦视觉集成（避开格式门控对 quality 阶段的短路），用仅含 quality 阶段的自定义管线。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_eval.evaluation.engine import (
    EvaluatorConfig,
    PipelineConfig,
    PipelineEngine,
    StageConfig,
)
from agent_eval.evaluation.registry import registry

# 触发评估器注册（含 vision）
import agent_eval.evaluation.evaluators  # noqa: F401


class _FakeDim:
    def __init__(self, dim_id: str, weight: float = 1.0) -> None:
        self.dim_id = dim_id
        self.name = dim_id
        self.weight = weight


class _FakeTemplate:
    def __init__(self, scores: dict[str, float]) -> None:
        self.dimensions = [_FakeDim(k) for k in scores]
        self.num_samples = 1
        self.temperature = 0.0
        self.seed = 42


class _FakeTemplates:
    def __init__(self, score_map: dict[str, dict[str, float]]) -> None:
        self._m = score_map

    def get(self, tid: str) -> _FakeTemplate:
        return _FakeTemplate(self._m.get(tid, {}))


class _FakeRecord:
    def __init__(self, provider: str, model: str) -> None:
        self.provider_name = provider
        self.model = model
        self.judge_id = f"judge_{provider}_t"
        self.confidence = {}
        self.summary = ""


class _FakeOrchestrator:
    """根据 template_id 返回固定 (scores, record)；templates 返回对应维度。"""

    def __init__(
        self, score_map: dict[str, dict[str, float]], provider_model: dict[str, tuple[str, str]]
    ) -> None:
        self.templates = _FakeTemplates(score_map)
        self._score_map = score_map
        self._pm = provider_model

    def judge(
        self,
        *,
        constraint_id,
        sample_id,
        template_id,
        variables,
        evidence_dir,
        provider_name=None,
        images=None,
    ):
        scores = self._score_map.get(template_id, {})
        provider, model = self._pm.get(template_id, ("ds", "m"))
        return scores, _FakeRecord(provider, model)


@pytest.mark.integration
class TestCascadeVisionIntegration:
    """视觉评估级联集成。"""

    def test_vision_in_cascade_and_weighted(self, tmp_path: Path) -> None:
        """vision.quality 进 quality 阶段，截图落 evidence，s_soft 含 vision 权重。"""
        # 样本：output 含一个 md 文档
        pkg = tmp_path / "pkg"
        out = pkg / "output"
        out.mkdir(parents=True)
        (out / "lesson.md").write_text("# 课程\n\n教学内容", encoding="utf-8")

        # 截图：mock renderer 将 PNG 写入 out_dir（= evidence_dir），模拟真实行为
        def _fake_render(sources, *, out_dir, **kw):
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            p = out_dir / "shot_000.png"
            p.write_bytes(b"\x89PNG\r\n\x1a\n")
            return [p]

        renderer = MagicMock()
        renderer.render.side_effect = _fake_render

        # FakeOrchestrator：vision 4 维均 8.0（→0.8），teaching_logic 8.0（→0.8）
        score_map = {
            "visual_quality": {
                "layout": 8.0,
                "color_scheme": 8.0,
                "information_hierarchy": 8.0,
                "readability": 8.0,
            },
            "pedagogical_logic": {"teaching_logic_dim": 8.0},
        }
        provider_model = {
            "visual_quality": ("kimi_vision", "kimi-2.6"),
            "pedagogical_logic": ("deepseek_judge", "deepseek-chat"),
        }
        orch = _FakeOrchestrator(score_map, provider_model)

        # 自定义管线：仅 quality 阶段（vision + 一个文本 LLM 评估器）
        config = PipelineConfig(
            stages=[
                StageConfig(
                    id="quality",
                    short_circuit_policy="continue_all",
                    evaluators=[
                        EvaluatorConfig(
                            "vision.quality",
                            {"template_id": "visual_quality", "llm_provider": "kimi_vision"},
                        ),
                        EvaluatorConfig(
                            "soft.teaching_logic", {"template_id": "pedagogical_logic"}
                        ),
                    ],
                )
            ]
        )
        engine = PipelineEngine(config, registry)
        # 显式 soft_weights（含 vision.quality）
        engine.aggregator.soft_weights = {
            "soft.teaching_logic": 0.4,
            "vision.quality": 0.6,
        }

        context = {
            "judge_orchestrator": orch,
            "evidence_dir": tmp_path / "ev",
            "screenshot_renderer": renderer,
            "sample_id": "s1",
            "task_input": {"title": "测试", "subject": "数学"},
        }
        result = engine.evaluate_sample(pkg, context)

        # 找到 vision.quality 结果
        q_stage = result.stage_results["quality"]
        vision_cr = next(
            cr for cr in q_stage.constraint_results if cr.constraint_id == "vision.quality"
        )
        assert vision_cr.score == pytest.approx(0.8)
        assert vision_cr.judge_provider == "kimi_vision"
        assert vision_cr.judge_model == "kimi-2.6"
        assert "screenshot_paths" in vision_cr.details
        # 截图落 evidence 目录
        ev_files = list((tmp_path / "ev").glob("*.png"))
        assert len(ev_files) == 1

        # s_soft = (0.4*0.8 + 0.6*0.8) / 1.0 = 0.8（含 vision 权重）
        assert result.s_soft == pytest.approx(0.8)
