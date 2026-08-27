"""SUTSession 与 SessionStore — 会话产物及其持久化（arch/03 §4.0.1/§4.0.4/§4.0.5）。

SUTSession = token/挂载方式 + 过期时间；进程内缓存 + 落盘持久化
（workspace/sut_sessions/、0600 权限，过期自动清理）——落盘文件等同凭证管理；
评测状态聚集于 workspace，清 workspace 即全新重测（arch/03 §7a.8）。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from pydantic import BaseModel, Field

# 会话落盘目录（可 env 覆盖）。默认 workspace/sut_sessions/（arch/03 §7a.8）：
# 评测状态单一聚集于 workspace——清 workspace 即全新重测（含登录态）；
# 目录 0600 语义不变。迁移自 ~/.agent_eval/sut_sessions（旧目录存在时自动搬迁）。
SESSION_DIR_ENV = "AGENT_EVAL_SUT_SESSION_DIR"
LEGACY_SESSION_DIR = Path.home() / ".agent_eval" / "sut_sessions"

# 登录响应无 expires_in 时的固定 TTL（秒）
DEFAULT_SESSION_TTL_S = 3600.0


def default_session_dir() -> Path:
    """缺省会话目录：workspace/sut_sessions/（自动搬迁旧目录内容）。"""
    from agent_eval.config.paths import paths

    target = paths.default_workspace / "sut_sessions"
    if LEGACY_SESSION_DIR.is_dir() and not target.exists():
        target.mkdir(parents=True, exist_ok=True)
        import shutil

        for f in LEGACY_SESSION_DIR.glob("*.json"):
            shutil.move(str(f), target / f.name)
    return target


class SUTSession(BaseModel):
    """被测系统会话产物：token / 挂载方式 + 过期时间。"""

    sut_name: str = Field(description="被测系统名（SUTRegistry 索引键）")
    token: str | None = Field(default=None, description="会话凭证（token）")
    token_type: str = Field(
        default="Bearer",
        description='挂载形态: "Bearer" | "header:<HeaderName>" | "cookie"',
    )
    mount_header: str = Field(default="Authorization", description="Bearer 型挂载的请求头名")
    expires_at: float | None = Field(default=None, description="过期时间（epoch 秒）")
    created_at: float = Field(default_factory=time.time, description="创建时间（epoch 秒）")

    def is_expired(self, now: float | None = None) -> bool:
        """是否已过期（无过期时间视为未过期）。"""
        if self.expires_at is None:
            return False
        return (now if now is not None else time.time()) >= self.expires_at

    def mount_headers(self) -> dict[str, str]:
        """构建业务请求自动挂载的凭证头（cookie 型由共享 client 的 jar 承载）。"""
        if not self.token or self.token_type == "cookie":
            return {}
        if self.token_type.startswith("header:"):
            return {self.token_type.split(":", 1)[1]: self.token}
        return {self.mount_header: f"Bearer {self.token}"}


class SessionStore:
    """会话落盘存取：{base_dir}/{sut_name}.json（0600，过期自动清理）。"""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        if base_dir is None:
            env_dir = os.environ.get(SESSION_DIR_ENV, "").strip()
            base_dir = Path(env_dir).expanduser() if env_dir else default_session_dir()
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        # 会话目录等同凭证存储：收紧为仅当前用户可读写
        try:
            self.base_dir.chmod(0o700)
        except OSError:
            pass

    def _path(self, sut_name: str) -> Path:
        # 文件名只允许安全字符，防路径穿越
        # 只允许字母数字与 -_（排除 . 与 /，杜绝 ".." 形态的路径穿越）
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in sut_name)
        return self.base_dir / f"{safe}.json"

    def load(self, sut_name: str) -> SUTSession | None:
        """读取落盘会话；不存在或已过期（自动清理）返回 None。"""
        path = self._path(sut_name)
        if not path.exists():
            return None
        try:
            session = SUTSession.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if session.is_expired():
            path.unlink(missing_ok=True)
            return None
        return session

    def save(self, session: SUTSession) -> Path:
        """落盘会话（0600 权限），返回文件路径。"""
        path = self._path(session.sut_name)
        path.write_text(session.model_dump_json(indent=2), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return path

    def invalidate(self, sut_name: str) -> None:
        """删除落盘会话（401 失效 / 强制重登时）。"""
        self._path(sut_name).unlink(missing_ok=True)


def session_from_login_response(
    sut_name: str,
    payload: dict,
    token_path: str | None,
    token_type: str,
    mount_header: str,
    expires_in: float | None,
    *,
    ttl_s: float = DEFAULT_SESSION_TTL_S,
) -> SUTSession:
    """从登录响应构建 SUTSession（提取 token 与有效期）。"""
    from agent_eval.execution.utils import extract_by_path

    token = extract_by_path(payload, token_path) if token_path else None
    expires_at = time.time() + (expires_in if expires_in is not None else ttl_s)
    return SUTSession(
        sut_name=sut_name,
        token=str(token) if token is not None else None,
        token_type=token_type,
        mount_header=mount_header,
        expires_at=expires_at,
    )
