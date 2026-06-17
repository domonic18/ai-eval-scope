"""可观测平台对接默认参数（ResultSink / IngestionClient 用）。

仿 LangfuseDefaults：仅提供默认值；实际启用须经 AGENT_EVAL_* 环境变量配置凭据。
可观测平台后端契约见 docs/arch/09 §七（摄取）/ §八（评估器对接）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObservabilityDefaults:
    """可观测平台对接默认参数。"""

    # 未设置 AGENT_EVAL_HOST 时的默认平台地址（本地 docker compose 起栈）。
    host: str = "http://localhost:3000"

    # 摄取端点（HMAC 鉴权）。
    ingest_path: str = "/api/public/ingest"
    # 制品 presigned 申请端点。
    artifacts_path: str = "/api/public/artifacts/url"
    # 平台健康检查端点（启动自检）。
    health_path: str = "/health"

    # HTTP 单请求超时（秒）。
    timeout_sec: float = 30.0
    # 摄取失败重试次数（429/5xx）。
    max_retries: int = 5
    # 退避基数（秒），实际 = base * 2**attempt + jitter。
    backoff_base_sec: float = 1.0
    # 退避上限（秒）。
    backoff_max_sec: float = 60.0

    # 单批事件数上限（与后端 PLATFORM_INGEST_MAX_BATCH 对齐）。
    batch_max_events: int = 500

    # 离线队列：最大尝试次数，超过则入死信。
    queue_max_attempts: int = 10
    # 离线队列：重放批次大小。
    queue_replay_batch: int = 100


OBSERVABILITY_DEFAULTS = ObservabilityDefaults()
