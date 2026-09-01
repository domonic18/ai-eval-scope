"""LLM 配置文件与角色解析测试（arch/16 §6.2-四 CLI 形态）。

覆盖：llm.json 存取与 0600 权限、文件→平台兜底→报错的解析顺序、
agent 回退 text、指纹剔除密钥、models 命令交互（CliRunner）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_eval.config.llm import LLMConfig, ProviderConfig
from agent_eval.config.llm_file import (
    LLMFileConfig,
    RoleConfig,
    llm_file_path,
    load_llm_file,
    save_llm_file,
)
from agent_eval.config.llm_resolution import (
    LLMPlatform,
    llm_signature,
    resolve_llm_config,
)
from agent_eval.core.exceptions import ConfigError


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """隔离环境：配置文件与平台变量都指向 tmp。"""
    cfg_path = tmp_path / "llm.json"
    monkeypatch.setenv("AGENT_EVAL_LLM_CONFIG", str(cfg_path))
    monkeypatch.delenv("AGENT_EVAL_HOST", raising=False)
    monkeypatch.delenv("AGENT_EVAL_API_KEY", raising=False)
    return cfg_path


def _role(model: str = "m-1", api_key: str = "sk-x") -> RoleConfig:
    return RoleConfig(
        provider="anthropic", model=model, api_key=api_key, base_url="https://x", max_tokens=8192
    )


class TestLLMFile:
    def test_save_load_roundtrip_with_0600(self, _isolated_env: Path) -> None:
        path = save_llm_file(LLMFileConfig(roles={"text": _role(), "vision": None, "agent": None}))
        assert path == llm_file_path()
        assert stat_mode(path) == 0o600
        loaded = load_llm_file()
        assert loaded is not None
        assert loaded.roles["text"] is not None and loaded.roles["text"].model == "m-1"
        assert loaded.roles["vision"] is None

    def test_load_missing_returns_none(self, _isolated_env: Path) -> None:
        assert load_llm_file() is None

    def test_corrupt_file_raises(self, _isolated_env: Path) -> None:
        _isolated_env.write_text("{ not json", encoding="utf-8")
        with pytest.raises(ConfigError, match="损坏"):
            load_llm_file()

    def test_unknown_role_rejected(self, _isolated_env: Path) -> None:
        import json

        _isolated_env.write_text(
            json.dumps({"version": 1, "default_role": "text", "roles": {"other": None}}),
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="未知角色"):
            load_llm_file()


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


class _StubPlatform:
    """平台拉取桩（禁联网）。"""

    def __init__(self, roles: dict | None) -> None:
        self._roles = roles

    def fetch(self) -> dict | None:
        return self._roles


class TestResolve:
    def test_file_first_and_agent_fallback(self, _isolated_env: Path) -> None:
        save_llm_file(
            LLMFileConfig(roles={"text": _role("t-1"), "vision": _role("v-1"), "agent": None})
        )
        config = resolve_llm_config(platform=_StubPlatform({"text": {"model": "p"}}))
        assert set(config.providers) == {"text", "vision", "agent"}
        assert config.default == "text"
        assert config.providers["text"].model == "t-1"
        assert config.providers["agent"].model == "t-1"  # agent 回退 text

    def test_platform_fallback_when_no_file(self, _isolated_env: Path) -> None:
        roles = {
            "text": {
                "provider": "anthropic",
                "model": "p-1",
                "api_key": "sk-p",
                "base_url": "https://p",
                "max_tokens": 1024,
            }
        }
        config = resolve_llm_config(platform=_StubPlatform(roles))
        assert config.providers["text"].model == "p-1"
        assert config.providers["text"].api_key == "sk-p"
        assert config.providers["agent"].model == "p-1"

    def test_unavailable_raises_with_guidance(self, _isolated_env: Path) -> None:
        with pytest.raises(ConfigError, match="models set"):
            resolve_llm_config(platform=_StubPlatform(None))

    def test_signature_excludes_api_key(self) -> None:
        def _cfg(api_key: str, model: str = "m") -> LLMConfig:
            return LLMConfig(
                default="text",
                providers={
                    "text": ProviderConfig(
                        provider="anthropic", model=model, api_key=api_key, base_url="https://x"
                    )
                },
            )

        assert llm_signature(_cfg("sk-1")) == llm_signature(_cfg("sk-2"))  # 密钥不影响指纹
        assert llm_signature(_cfg("sk-1")) != llm_signature(
            _cfg("sk-1", model="m2")
        )  # 模型变化失效

    def test_platform_from_env_gating(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert LLMPlatform.from_env({}) is None
        assert LLMPlatform.from_env({"AGENT_EVAL_HOST": "http://x"}) is None
        assert (
            LLMPlatform.from_env({"AGENT_EVAL_HOST": "http://x", "AGENT_EVAL_API_KEY": "k"})
            is not None
        )


class TestModelsCommand:
    def test_login_writes_0600_file_and_list_masks_key(self, _isolated_env: Path) -> None:
        from typer.testing import CliRunner

        from agent_eval.cli.cmds.models import models_app

        runner = CliRunner()
        # 提供商（默认1 anthropic）→ base_url（默认）→ api-key → text（默认y）→ 模型（默认）
        # → vision（n）→ agent（n）
        result = runner.invoke(models_app, ["set"], input="\n\nsk-test-1234567890\n\n\nn\nn\n")
        assert result.exit_code == 0, result.output
        cfg = load_llm_file()
        assert cfg is not None
        assert cfg.roles["text"] is not None
        assert cfg.roles["text"].api_key == "sk-test-1234567890"
        assert cfg.roles["text"].model == "moonshot-v1-128k"
        assert cfg.roles["vision"] is None
        assert stat_mode(_isolated_env) == 0o600

        listing = runner.invoke(models_app, ["list"])
        assert listing.exit_code == 0, listing.output
        assert "sk-test-1234567890" not in listing.output  # 完整明文不回显（脱敏保留首尾 4 位）

    def test_list_without_config_exits_1(self, _isolated_env: Path) -> None:
        from typer.testing import CliRunner

        from agent_eval.cli.cmds.models import models_app

        result = CliRunner().invoke(models_app, ["list"])
        assert result.exit_code == 1
        assert "models set" in result.output

    def test_logout_removes_file(self, _isolated_env: Path) -> None:
        from typer.testing import CliRunner

        from agent_eval.cli.cmds.models import models_app

        save_llm_file(LLMFileConfig(roles={"text": _role()}))
        result = CliRunner().invoke(models_app, ["clear"], input="y\n")
        assert result.exit_code == 0, result.output
        assert not _isolated_env.exists()
