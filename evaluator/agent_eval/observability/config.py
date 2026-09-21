"""读取 AGENT_EVAL_* 环境变量，生成 ObservabilityConfig。

约定（单一 Bearer Key）：
  AGENT_EVAL_HOST          平台地址（默认 http://localhost:9000）
  AGENT_EVAL_WEB_BASE      平台页面基址（默认=AGENT_EVAL_HOST；UI 独立域名部署时才需设置）
  AGENT_EVAL_API_KEY       eval-...（单一 API Key，Bearer 鉴权）
  AGENT_EVAL_PROJECT       目标项目（uuid 或 slug，可选；缺省=Key 所属项目）
  AGENT_EVAL_UPLOAD        true/1 启用摄取（默认 false，需显式开启）
  AGENT_EVAL_QUEUE_DIR     离线队列目录（默认 <workspace>/.ingest_queue）

未配置凭据 → enabled() 为 False，ResultSink 自动跳过（不报错）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agent_eval.config import OBSERVABILITY_DEFAULTS


@dataclass(frozen=True)
class ObservabilityConfig:
    """可观测平台对接配置（运行期不可变快照）。"""

    enabled: bool
    host: str
    web_base: str
    api_key: str
    project: str | None
    upload: bool
    ingest_url: str
    artifacts_url: str
    health_url: str
    # 制品上传 presigned PUT 的端点侧："external"（默认，宿主 CLI/浏览器可达）
    # 或 "internal"（与 web 同内网，本地栈 executor 容器内唯一可达端点）
    presign_audience: str
    timeout_sec: float
    max_retries: int
    backoff_base_sec: float
    backoff_max_sec: float
    batch_max_events: int
    queue_max_attempts: int
    queue_replay_batch: int
    queue_dir: Path
    client_version: str

    def has_credentials(self) -> bool:
        return bool(self.api_key)

    def run_view_url(self, run_id: str) -> str:
        """运行详情页地址（页面路由固定 ``/run/:id``，后端按 externalRunId 兼容查询）。"""
        return f"{self.web_base}/run/{run_id}" if run_id else ""


def _truthy(val: str | None) -> bool:
    return bool(val and val.strip().lower() in {"1", "true", "yes", "on"})


def _client_version() -> str:
    try:
        from agent_eval import __version__  # 局部 import 避免循环

        return f"agent-eval/{__version__}"
    except Exception:
        return "agent-eval/dev"


def load_config(
    *,
    workspace: Path | None = None,
    upload_override: bool | None = None,
    env: dict[str, str] | None = None,
) -> ObservabilityConfig:
    """从环境变量加载配置。

    - upload_override：CLI --upload/--no-upload 显式覆盖 AGENT_EVAL_UPLOAD。
    - env：测试注入；缺省读 os.environ。
    """
    e = env if env is not None else os.environ
    d = OBSERVABILITY_DEFAULTS

    host = e.get("AGENT_EVAL_HOST", d.host).rstrip("/")
    # 页面基址缺省同 host（当前部署 UI 与 ingest 同域 :9000）；独立域名时显式覆盖
    web_base = e.get("AGENT_EVAL_WEB_BASE", "").strip().rstrip("/") or host
    api_key = e.get("AGENT_EVAL_API_KEY", "").strip()
    project = e.get("AGENT_EVAL_PROJECT", "").strip() or None

    upload = _truthy(e.get("AGENT_EVAL_UPLOAD"))
    if upload_override is not None:
        upload = upload_override

    queue_dir_env = e.get("AGENT_EVAL_QUEUE_DIR", "").strip()
    if queue_dir_env:
        queue_dir = Path(queue_dir_env)
    elif workspace is not None:
        queue_dir = workspace / ".ingest_queue"
    else:
        queue_dir = Path(".ingest_queue")

    # 制品上传方网络位置：executor 容器经 AGENT_EVAL_PRESIGN_AUDIENCE=internal 声明；
    # 非 internal 值（含空）一律容错归一为 external（既有宿主行为）
    presign_audience = (
        "internal"
        if e.get("AGENT_EVAL_PRESIGN_AUDIENCE", "").strip().lower() == "internal"
        else "external"
    )

    enabled = upload and bool(api_key)

    return ObservabilityConfig(
        enabled=enabled,
        host=host,
        web_base=web_base,
        api_key=api_key,
        project=project,
        upload=upload,
        ingest_url=host + d.ingest_path,
        artifacts_url=host + d.artifacts_path,
        health_url=host + d.health_path,
        presign_audience=presign_audience,
        timeout_sec=d.timeout_sec,
        max_retries=d.max_retries,
        backoff_base_sec=d.backoff_base_sec,
        backoff_max_sec=d.backoff_max_sec,
        batch_max_events=d.batch_max_events,
        queue_max_attempts=d.queue_max_attempts,
        queue_replay_batch=d.queue_replay_batch,
        queue_dir=queue_dir,
        client_version=_client_version(),
    )
