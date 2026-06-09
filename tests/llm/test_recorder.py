"""JudgeRecorder 测试 — JudgeRecord 文件持久化。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_eval.llm.judge.recorder import JudgeRecorder
from agent_eval.llm.models import JudgeRecord, TokenUsage


class TestJudgeRecorder:
    """JudgeRecorder 测试。"""

    def test_save_creates_file(self, tmp_path: Path) -> None:
        """save 创建 JSON 文件。"""
        record = JudgeRecord(
            judge_id="judge_test_001",
            constraint_id="soft.teaching_logic",
            sample_id="sample_01",
            provider_name="deepseek_judge",
            model="deepseek-chat",
            template_id="pedagogical_logic",
            timestamp="2026-06-09T14:30:00+00:00",
        )
        evidence_dir = tmp_path / "evidence"
        result_path = JudgeRecorder.save(record, evidence_dir)

        assert result_path.exists()
        assert result_path.name == "judge_test_001.json"
        assert evidence_dir.is_dir()

    def test_save_content(self, tmp_path: Path) -> None:
        """save 写入的 JSON 内容正确。"""
        record = JudgeRecord(
            judge_id="j1",
            constraint_id="c1",
            sample_id="s1",
            provider_name="p1",
            model="m1",
            template_id="t1",
            final_scores={"clarity": 8.0},
            confidence={"clarity": "high"},
        )
        result_path = JudgeRecorder.save(record, tmp_path)
        data = json.loads(result_path.read_text(encoding="utf-8"))

        assert data["judge_id"] == "j1"
        assert data["final_scores"]["clarity"] == 8.0
        assert data["confidence"]["clarity"] == "high"

    def test_load_roundtrip(self, tmp_path: Path) -> None:
        """save → load 往返一致。"""
        original = JudgeRecord(
            judge_id="j_rt",
            constraint_id="c_rt",
            sample_id="s_rt",
            provider_name="p_rt",
            model="m_rt",
            template_id="t_rt",
            raw_response='{"score": 7}',
            parsed_scores={"score": 7},
            final_scores={"score": 7.0},
            confidence={"score": "high"},
            num_samples=3,
            total_duration_ms=5000.0,
            token_usage=TokenUsage(300, 150, 450),
            timestamp="2026-06-09T14:00:00+00:00",
        )
        path = JudgeRecorder.save(original, tmp_path)
        loaded = JudgeRecorder.load(path)

        assert loaded.judge_id == original.judge_id
        assert loaded.provider_name == original.provider_name
        assert loaded.final_scores == original.final_scores
        assert loaded.token_usage is not None
        assert loaded.token_usage.total_tokens == 450
        assert loaded.num_samples == 3

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        """save 自动创建父目录。"""
        record = JudgeRecord(
            judge_id="j_dir",
            constraint_id="c",
            sample_id="s",
            provider_name="p",
            model="m",
            template_id="t",
        )
        nested_dir = tmp_path / "a" / "b" / "c"
        path = JudgeRecorder.save(record, nested_dir)
        assert path.exists()

    def test_load_nonexistent_file(self, tmp_path: Path) -> None:
        """加载不存在的文件抛异常。"""
        with pytest.raises(FileNotFoundError):
            JudgeRecorder.load(tmp_path / "nonexistent.json")
