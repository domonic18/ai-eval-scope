"""secrets 命令与凭证文件源测试（arch/16 §2.2 本机密钥区）。

覆盖：文件存取 0600、CredentialStore env→文件双通道、CLI 交互（CliRunner）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_eval.core.exceptions import SUTAuthError
from agent_eval.execution.auth.credentials import CredentialStore
from agent_eval.execution.auth.secrets_store import (
    load_secrets_file,
    save_secrets_file,
    secrets_file_path,
)


@pytest.fixture(autouse=True)
def _isolated_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "sut_credentials.json"
    monkeypatch.setenv("AGENT_EVAL_SUT_CREDENTIALS", str(path))
    return path


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


class TestSecretsFile:
    def test_save_load_roundtrip_with_0600(self, _isolated_secrets: Path) -> None:
        path = save_secrets_file({"sasan": {"username": "u", "password": "p"}})
        assert path == secrets_file_path()
        assert stat_mode(path) == 0o600
        assert load_secrets_file() == {"sasan": {"username": "u", "password": "p"}}

    def test_load_missing_returns_empty(self, _isolated_secrets: Path) -> None:
        assert load_secrets_file() == {}

    def test_corrupt_file_raises_with_reset_hint(self, _isolated_secrets: Path) -> None:
        _isolated_secrets.write_text("{ not json", encoding="utf-8")
        with pytest.raises(SUTAuthError, match="凭证文件损坏"):
            load_secrets_file()


class TestCredentialStoreDualChannel:
    def test_env_takes_priority_over_file(self, _isolated_secrets: Path) -> None:
        save_secrets_file({"sasan": {"username": "from-file"}})
        store = CredentialStore(env={"AGENT_EVAL_SUT__SASAN__USERNAME": "from-env"})
        assert store.get("sasan", "username") == "from-env"

    def test_file_fallback_when_env_missing(self, _isolated_secrets: Path) -> None:
        save_secrets_file({"sasan": {"username": "u1", "token": "t1"}})
        store = CredentialStore(env={})
        assert store.get("sasan", "USERNAME") == "u1"  # 字段大小写不敏感
        assert store.get("sasan", "token") == "t1"
        assert store.get("sasan", "password") is None

    def test_require_missing_guides_to_secrets_set(self, _isolated_secrets: Path) -> None:
        store = CredentialStore(env={})
        with pytest.raises(SUTAuthError, match=r"secrets set sasan\.password"):
            store.require("sasan", "password")


class TestSecretsCommand:
    def test_set_list_delete_roundtrip(self, _isolated_secrets: Path) -> None:
        from typer.testing import CliRunner

        from agent_eval.cli.cmds.secrets import secrets_app

        runner = CliRunner()
        result = runner.invoke(secrets_app, ["set", "sasan.username"], input="138xxx\n")
        assert result.exit_code == 0, result.output
        runner.invoke(secrets_app, ["set", "sasan.password"], input="330330\n")
        assert load_secrets_file() == {"sasan": {"username": "138xxx", "password": "330330"}}
        assert stat_mode(_isolated_secrets) == 0o600

        listing = runner.invoke(secrets_app, ["list"])
        assert listing.exit_code == 0, listing.output
        assert "sasan" in listing.output and "username" in listing.output
        assert "138xxx" not in listing.output  # 值不回显

        deleted = runner.invoke(secrets_app, ["delete", "sasan.password", "--force"])
        assert deleted.exit_code == 0, deleted.output
        assert load_secrets_file() == {"sasan": {"username": "138xxx"}}

        # 删空 ref 后整条移除
        runner.invoke(secrets_app, ["delete", "sasan.username", "--force"])
        assert load_secrets_file() == {}

    def test_set_empty_value_cancels(self, _isolated_secrets: Path) -> None:
        from typer.testing import CliRunner

        from agent_eval.cli.cmds.secrets import secrets_app

        result = CliRunner().invoke(secrets_app, ["set", "sasan.token"], input="\n")
        assert result.exit_code == 1
        assert not _isolated_secrets.exists()

    def test_bad_key_format_rejected(self, _isolated_secrets: Path) -> None:
        from typer.testing import CliRunner

        from agent_eval.cli.cmds.secrets import secrets_app

        result = CliRunner().invoke(secrets_app, ["set", "no-dot"], input="x\n")
        assert result.exit_code == 1
        assert "ref>.<field" in result.output
