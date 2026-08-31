"""SUT 凭证文件（`~/.agent_eval/sut_credentials.json`）— 本机密钥区（arch/06 §4.7）。

`agent-eval secrets set <ref>.<field>` 交互录入；**0600 权限**（与 llm.json
同目录同惯例）。通用 KV 结构：``{"<ref>": {"<field>": "<value>"}}``——字段名
自由，不绑定 username/password 特定形态（static_token 型同样适用）。
路径可经 ``AGENT_EVAL_SUT_CREDENTIALS`` 覆盖（测试/多环境隔离）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from agent_eval.core.exceptions import SUTAuthError


def secrets_file_path() -> Path:
    """凭证文件路径：``AGENT_EVAL_SUT_CREDENTIALS`` 覆盖 > ``~/.agent_eval/sut_credentials.json``。"""
    override = os.environ.get("AGENT_EVAL_SUT_CREDENTIALS", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".agent_eval" / "sut_credentials.json"


def load_secrets_file(path: Path | None = None) -> dict[str, dict[str, str]]:
    """加载凭证文件；文件不存在返回空 dict。

    Raises:
        SUTAuthError: 文件损坏（非法 JSON / 结构不符）。
    """
    p = path or secrets_file_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise SUTAuthError(f"凭证文件损坏: {p}（{e}）", details={"path": str(p)}) from e
    if not isinstance(data, dict):
        raise SUTAuthError(f"凭证文件结构无效（需 ref→field→value）: {p}", details={"path": str(p)})
    out: dict[str, dict[str, str]] = {}
    for ref, fields in data.items():
        if isinstance(fields, dict):
            out[str(ref)] = {str(k): str(v) for k, v in fields.items() if isinstance(v, str)}
    return out


def save_secrets_file(secrets: dict[str, dict[str, str]], path: Path | None = None) -> Path:
    """写入凭证文件并收紧权限至 0600（父目录按需创建；空字典写入空对象）。"""
    p = path or secrets_file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(secrets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(p, 0o600)
    return p


__all__ = ["load_secrets_file", "save_secrets_file", "secrets_file_path"]
