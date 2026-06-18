"""StabilityController 测试 — 多次采样取中位数 + 置信度。"""

from __future__ import annotations

import pytest

from agent_eval.llm.judge.stability import StabilityController
from agent_eval.llm.judge.template_manager import JudgeDimension


def _make_dims(*ids: str) -> list[JudgeDimension]:
    """创建测试维度列表。"""
    return [JudgeDimension(dim_id=d, name=d, description=f"Dimension {d}") for d in ids]


class TestStabilityController:
    """StabilityController 测试。"""

    def test_single_sample(self) -> None:
        """单次采样直接返回。"""
        ctrl = StabilityController(num_samples=1)
        dims = _make_dims("clarity")
        result = ctrl.evaluate_stable(
            judge_fn=lambda seed: {"clarity": 8.0},
            dimensions=dims,
        )
        assert result.scores["clarity"] == 8.0
        assert result.confidence["clarity"] == "high"
        assert result.num_samples == 1

    def test_three_samples_median(self) -> None:
        """三次采样取中位数。"""
        scores_sequence = [
            {"clarity": 7.0},
            {"clarity": 9.0},
            {"clarity": 5.0},
        ]
        ctrl = StabilityController(num_samples=3)
        result = ctrl.evaluate_stable(
            judge_fn=lambda seed: scores_sequence[seed],
            dimensions=_make_dims("clarity"),
        )
        # median(5, 7, 9) = 7.0
        assert result.scores["clarity"] == 7.0
        assert result.num_samples == 3

    def test_high_confidence(self) -> None:
        """低标准差 → 高置信度。"""
        scores_sequence = [
            {"clarity": 8.0},
            {"clarity": 8.1},
            {"clarity": 7.9},
        ]
        ctrl = StabilityController(num_samples=3, stddev_threshold=1.5)
        result = ctrl.evaluate_stable(
            judge_fn=lambda seed: scores_sequence[seed],
            dimensions=_make_dims("clarity"),
        )
        assert result.confidence["clarity"] == "high"

    def test_low_confidence_high_stddev(self) -> None:
        """高标准差 → 低置信度。"""
        scores_sequence = [
            {"clarity": 2.0},
            {"clarity": 8.0},
            {"clarity": 10.0},
        ]
        ctrl = StabilityController(num_samples=3, stddev_threshold=1.5)
        result = ctrl.evaluate_stable(
            judge_fn=lambda seed: scores_sequence[seed],
            dimensions=_make_dims("clarity"),
        )
        assert result.confidence["clarity"] == "low"

    def test_custom_threshold(self) -> None:
        """自定义标准差阈值。"""
        scores_sequence = [
            {"clarity": 5.0},
            {"clarity": 10.0},
            {"clarity": 5.0},
        ]
        # stddev ≈ 2.89, 阈值 3.0 → high
        ctrl_high = StabilityController(num_samples=3, stddev_threshold=3.0)
        result = ctrl_high.evaluate_stable(
            judge_fn=lambda seed: scores_sequence[seed],
            dimensions=_make_dims("clarity"),
        )
        assert result.confidence["clarity"] == "high"

        # 阈值 2.0 → low
        ctrl_low = StabilityController(num_samples=3, stddev_threshold=2.0)
        result = ctrl_low.evaluate_stable(
            judge_fn=lambda seed: scores_sequence[seed],
            dimensions=_make_dims("clarity"),
        )
        assert result.confidence["clarity"] == "low"

    def test_multiple_dimensions(self) -> None:
        """多维度独立计算。"""
        scores_sequence = [
            {"clarity": 8.0, "depth": 5.0},
            {"clarity": 8.1, "depth": 1.0},
            {"clarity": 7.9, "depth": 9.0},
        ]
        ctrl = StabilityController(num_samples=3, stddev_threshold=1.5)
        dims = _make_dims("clarity", "depth")
        result = ctrl.evaluate_stable(
            judge_fn=lambda seed: scores_sequence[seed],
            dimensions=dims,
        )
        # clarity: stable → high
        assert result.confidence["clarity"] == "high"
        # depth: 1, 5, 9 → stddev ≈ 4 → low
        assert result.confidence["depth"] == "low"
        assert result.scores["clarity"] == pytest.approx(8.0)
        assert result.scores["depth"] == pytest.approx(5.0)

    def test_all_samples_recorded(self) -> None:
        """all_samples 记录所有采样结果。"""
        scores_sequence = [
            {"clarity": 7.0},
            {"clarity": 8.0},
            {"clarity": 9.0},
        ]
        ctrl = StabilityController(num_samples=3)
        result = ctrl.evaluate_stable(
            judge_fn=lambda seed: scores_sequence[seed],
            dimensions=_make_dims("clarity"),
        )
        assert len(result.all_samples) == 3
        assert result.all_samples[0]["clarity"] == 7.0
        assert result.all_samples[2]["clarity"] == 9.0
