"""JudgeRecord 文件持久化。"""

from __future__ import annotations

import json
from pathlib import Path

from agent_eval.llm.models import JudgeRecord


class JudgeRecorder:
    """JudgeRecord 文件持久化。

    将 JudgeRecord 保存为 JSON 文件到 evidence 目录，
    支持从文件加载反序列化。
    """

    @staticmethod
    def save(record: JudgeRecord, evidence_dir: Path) -> Path:
        """保存 JudgeRecord 为 JSON 文件。

        Args:
            record: JudgeRecord 实例。
            evidence_dir: 证据目录路径。

        Returns:
            保存的文件路径。
        """
        evidence_dir.mkdir(parents=True, exist_ok=True)
        file_path = evidence_dir / f"{record.judge_id}.json"
        file_path.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return file_path

    @staticmethod
    def load(record_path: Path) -> JudgeRecord:
        """从 JSON 文件加载 JudgeRecord。

        Args:
            record_path: JSON 文件路径。

        Returns:
            JudgeRecord 实例。
        """
        data = json.loads(record_path.read_text(encoding="utf-8"))
        return JudgeRecord.from_dict(data)
