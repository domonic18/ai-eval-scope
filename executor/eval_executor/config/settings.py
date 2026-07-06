"""配置 -- Pydantic BaseSettings 读取环境变量。

复用 Web 的 PLATFORM_* 变量（数据库、加密 key），executor 自身用 EVALEXECUTOR_* 前缀。
executor 不监听端口（SCF 事件函数 + Job 镜像），无 PORT 配置。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行配置（从仓库根 .env 读取）。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_file_encoding="utf-8")

    # ── 复用 Web 的变量 ──
    database_url: str = Field(
        alias="PLATFORM_DATABASE_URL",
        description="共享 Web 的 PG 连接串（eval_jobs 表在 public schema）",
    )
    key_encryption_key: str = Field(
        default="dev-insecure-encryption-key",
        alias="PLATFORM_KEY_ENCRYPTION_KEY",
        description="AES-256-GCM 解密 api_keys.token_encrypted 的主密钥（key = SHA256(此值)）",
    )

    # ── executor 自身（EVALEXECUTOR_*）──
    worker_enabled: bool = Field(
        default=False,
        alias="EVALEXECUTOR_WORKER_ENABLED",
        description="本地 worker 模式：无 SCF event 时轮询 eval_jobs（本地开发用）",
    )
    worker_concurrency: int = Field(default=2, alias="EVALEXECUTOR_WORKER_CONCURRENCY")
    web_base_url: str = Field(
        default="http://localhost:9000",
        alias="EVALEXECUTOR_WEB_BASE_URL",
        description="Web 平台地址（生成 web_run_url）",
    )
    workspace_dir: Path = Field(
        default=Path("/tmp/executor-workspace"),
        alias="EVALEXECUTOR_WORKSPACE",
        description="执行工作区（下载输入、打包、评估产物）",
    )
    poll_interval_sec: float = Field(
        default=1.0,
        alias="EVALEXECUTOR_POLL_INTERVAL_SEC",
        description="worker 轮询 queued 任务的间隔",
    )
    http_timeout_sec: float = Field(
        default=120.0,
        alias="EVALEXECUTOR_HTTP_TIMEOUT_SEC",
        description="经 presigned URL 下载输入的 HTTP 超时",
    )


def get_settings() -> Settings:
    """加载配置（每次调用重新读取，便于测试注入）。"""
    return Settings()  # type: ignore[call-arg]
