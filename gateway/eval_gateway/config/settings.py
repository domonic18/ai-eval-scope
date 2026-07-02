"""配置 -- Pydantic BaseSettings 读取环境变量。

复用 Web 的 PLATFORM_* 变量（数据库、加密 key），gateway 自身用 EVALGATEWAY_* 前缀。
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
        description="共享 Web 的 PG 连接串（gateway 在独立 schema gateway 建 jobs 表）",
    )
    key_encryption_key: str = Field(
        default="dev-insecure-encryption-key",
        alias="PLATFORM_KEY_ENCRYPTION_KEY",
        description="AES-256-GCM 解密 api_keys.token_encrypted 的主密钥（key = SHA256(此值)）",
    )

    # ── gateway 自身（EVALGATEWAY_*）──
    port: int = Field(
        default=9000, alias="EVALGATEWAY_PORT", description="容器监听端口（SCF 要求 9000）"
    )
    worker_concurrency: int = Field(default=2, alias="EVALGATEWAY_WORKER_CONCURRENCY")
    max_upload_mb: int = Field(default=50, alias="EVALGATEWAY_MAX_UPLOAD_MB")
    web_base_url: str = Field(
        default="http://localhost:9000",
        alias="EVALGATEWAY_WEB_BASE_URL",
        description="Web 平台地址（生成 web_run_url）",
    )
    upload_dir: Path = Field(
        default=Path("./workspace/gateway/uploads"),
        alias="EVALGATEWAY_UPLOAD_DIR",
        description="上传内容物化目录",
    )
    poll_interval_sec: float = Field(
        default=1.0,
        alias="EVALGATEWAY_POLL_INTERVAL_SEC",
        description="worker 轮询 queued 任务的间隔",
    )
    enable_vision: bool = Field(
        default=False,
        alias="EVALGATEWAY_ENABLE_VISION",
        description=(
            "启用多模态视觉评估。opt-in：需镜像内预装 Chromium（见 docker/gateway/Dockerfile "
            "的 `playwright install chromium`）。未启用或浏览器缺失时，视觉维度自动降级为跳过，"
            "不阻塞评估。"
        ),
    )


def get_settings() -> Settings:
    """加载配置（每次调用重新读取，便于测试注入）。"""
    return Settings()  # type: ignore[call-arg]
