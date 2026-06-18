"""可观测平台对接模块（ResultSink / IngestionClient / 离线队列）。

评估器（agent-eval eval）完成后，经此把结果推送到自托管可观测平台：
拼装事件 → 上传制品(presigned) → 发送事件(HMAC) → 失败入 SQLite 队列重放。

后端契约见 docs/arch/09 §七（摄取）/ §八（评估器对接）。
"""

from agent_eval.observability.config import ObservabilityConfig, load_config
from agent_eval.observability.sink import ResultSink

__all__ = ["ObservabilityConfig", "load_config", "ResultSink"]
