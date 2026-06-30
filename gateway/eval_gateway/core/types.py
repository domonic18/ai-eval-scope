"""核心枚举 — 定义在 core/types.py，统一 (str, Enum) + 中文 docstring。"""

from __future__ import annotations

from enum import Enum


class JobStatus(str, Enum):
    """任务状态 -- 决定 worker 调度与第三方查询呈现。"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class InputKind(str, Enum):
    """内容承载方式 -- 第三方递交待评估内容的渠道。"""

    UPLOAD = "upload"
    INLINE = "inline"


class Scope(str, Enum):
    """评估粒度 -- 单元（文件夹多文件）或单页（单文件）。"""

    UNIT = "unit"
    SINGLE = "single"
