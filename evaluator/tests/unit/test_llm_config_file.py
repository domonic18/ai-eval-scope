"""LLM 配置文件与角色解析测试（arch/16 §6.2-四 CLI 形态）。

覆盖：llm.json 存取与 0600 权限、文件→平台兜底→报错的解析顺序、
agent 回退 text、指纹剔除密钥、models 命令交互（CliRunner）、
提供商 × 协议预置矩阵与协议归一（厂商键 ≠ 线路协议）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_eval.config.llm import LLMConfig, ProviderConfig
from agent_eval.config.llm_file import (
    PROTOCOLS,
    PROVIDER_DEFAULT_BASE_URLS,
    PROVIDER_LABELS,
    PROVIDER_MODEL_SUGGESTIONS,
    PROVIDERS,
    LLMFileConfig,
    RoleConfig,
    effective_protocol,
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


class TestProviderProtocolMatrix:
    """提供商 × 协议预置矩阵与协议归一（厂商键与线路协议正交）。"""

    def test_matrix_covers_every_vendor_protocol_pair(self) -> None:
        assert tuple(PROVIDER_LABELS) == PROVIDERS
        assert PROTOCOLS == ("anthropic", "openai")
        for vendor in PROVIDERS:
            for protocol in PROTOCOLS:
                url = PROVIDER_DEFAULT_BASE_URLS[(vendor, protocol)]
                assert url.startswith("https://"), f"{vendor}×{protocol} 预置端点须为 https"
        assert set(PROVIDER_MODEL_SUGGESTIONS) == {*PROVIDERS, "custom"}

    def test_effective_protocol_explicit_wins(self) -> None:
        assert effective_protocol("kimi", "anthropic") == "anthropic"
        assert effective_protocol("zhipu", "openai") == "openai"

    def test_effective_protocol_legacy_file_inference(self) -> None:
        """旧版文件（无 protocol 字段）按 provider 值推断：anthropic 之外均 OpenAI 兼容。"""
        assert effective_protocol("anthropic", None) == "anthropic"
        assert effective_protocol("openai", None) == "openai"
        assert effective_protocol("deepseek", None) == "openai"
        assert effective_protocol("custom", None) == "openai"
        # 非法 protocol 值同样落回推断（容忍手改文件）
        assert effective_protocol("kimi", "grpc") == "openai"


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

    def test_vendor_key_normalized_to_wire_protocol(self, _isolated_env: Path) -> None:
        """厂商键（kimi/deepseek）在解析层归一为线路协议分发键，工厂不感知厂商。"""
        save_llm_file(
            LLMFileConfig(
                roles={
                    "text": RoleConfig(
                        provider="kimi",
                        protocol="anthropic",
                        model="kimi-k3",
                        api_key="sk-x",
                        base_url="https://api.moonshot.cn/anthropic",
                    ),
                    "vision": RoleConfig(
                        provider="deepseek",  # 旧文件形态：无 protocol，按 provider 推断
                        model="deepseek-v4-pro",
                        api_key="sk-y",
                        base_url="https://api.deepseek.com/v1",
                    ),
                    "agent": None,
                }
            )
        )
        config = resolve_llm_config(platform=_StubPlatform(None))
        assert config.providers["text"].provider == "anthropic"  # 显式 protocol
        assert config.providers["vision"].provider == "openai"  # 旧文件推断

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
        # 提供商（默认1 deepseek）→ 协议（默认1 anthropic，预置端点免输）→ api-key
        # → text（默认y）→ 模型（默认 deepseek-v4-pro）→ vision（n）→ 立即测试（n）
        result = runner.invoke(models_app, ["set"], input="\n\nsk-test-1234567890\n\n\nn\nn\n")
        assert result.exit_code == 0, result.output
        cfg = load_llm_file()
        assert cfg is not None
        assert cfg.roles["text"] is not None
        assert cfg.roles["text"].provider == "deepseek"
        assert cfg.roles["text"].protocol == "anthropic"
        assert cfg.roles["text"].base_url == "https://api.deepseek.com/anthropic"
        assert cfg.roles["text"].api_key == "sk-test-1234567890"
        assert cfg.roles["text"].model == "deepseek-v4-pro"
        assert cfg.roles["vision"] is None
        assert cfg.roles["agent"] is None  # 未询问，且无既有配置可保留
        assert stat_mode(_isolated_env) == 0o600

        listing = runner.invoke(models_app, ["list"])
        assert listing.exit_code == 0, listing.output
        assert "sk-test-1234567890" not in listing.output  # 完整明文不回显（脱敏保留首尾 4 位）

    def test_set_custom_vendor_requires_base_url(self, _isolated_env: Path) -> None:
        """custom 厂商：无预置端点，必答 base_url；协议仍二选一。"""
        from typer.testing import CliRunner

        from agent_eval.cli.cmds.models import models_app

        runner = CliRunner()
        # 提供商5 custom → 协议2 OpenAI 兼容 → base_url → api-key → text y → 模型自输
        # → vision n → 立即测试 n
        _input = "5\n2\nhttps://gw.example.com/v1\nsk-custom-123456789\n\nmy-model\nn\nn\n"
        result = runner.invoke(models_app, ["set"], input=_input)
        assert result.exit_code == 0, result.output
        cfg = load_llm_file()
        assert cfg is not None
        rc = cfg.roles["text"]
        assert rc is not None
        assert rc.provider == "custom" and rc.protocol == "openai"
        assert rc.base_url == "https://gw.example.com/v1"
        assert rc.model == "my-model"

    def test_set_custom_rejects_base_url_without_scheme(self, _isolated_env: Path) -> None:
        from typer.testing import CliRunner

        from agent_eval.cli.cmds.models import models_app

        result = CliRunner().invoke(models_app, ["set"], input="5\n2\nnotaurl\n")
        assert result.exit_code == 1
        assert "http" in result.output

    def test_set_runs_connectivity_test_after_save(
        self, _isolated_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """保存后默认立即测试连通性（替身注入，禁联网）；测试不打断返回调用菜单。"""
        from typer.testing import CliRunner

        from agent_eval.cli.cmds import models as models_mod
        from agent_eval.cli.cmds.models import models_app

        calls: list[int] = []
        monkeypatch.setattr(
            models_mod, "_test_configured_roles", lambda: (calls.append(1), False)[1]
        )
        # 全默认 → vision n → 立即测试 y
        result = CliRunner().invoke(models_app, ["set"], input="\n\nsk-wire-123456789\n\n\nn\ny\n")
        assert result.exit_code == 0, result.output
        assert calls == [1]
        assert "连通性测试全部通过" in result.output

    def test_set_preserves_existing_agent_role(self, _isolated_env: Path) -> None:
        """回归：agent 角色不进向导，但既有配置（手改 llm.json / 专用 Agent 模型）原样保留。"""
        from typer.testing import CliRunner

        from agent_eval.cli.cmds.models import models_app

        save_llm_file(
            LLMFileConfig(
                roles={
                    "text": _role(),
                    "vision": None,
                    "agent": RoleConfig(
                        provider="kimi",
                        protocol="anthropic",
                        model="kimi-k3",
                        api_key="sk-agent",
                        base_url="https://api.moonshot.cn/anthropic",
                    ),
                }
            )
        )
        runner = CliRunner()
        # 提供商/协议/api-key/text/vision 全默认，vision 否决，立即测试否决
        result = runner.invoke(models_app, ["set"], input="\n\nsk-new-1234567890\n\n\nn\nn\n")
        assert result.exit_code == 0, result.output
        cfg = load_llm_file()
        assert cfg is not None
        assert cfg.roles["text"] is not None and cfg.roles["text"].api_key == "sk-new-1234567890"
        agent = cfg.roles["agent"]
        assert agent is not None and agent.model == "kimi-k3" and agent.api_key == "sk-agent"

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
