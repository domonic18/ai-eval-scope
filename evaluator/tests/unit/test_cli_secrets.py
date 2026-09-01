"""ensure_sut_credentials 单测 — 执行前缺失自动补录（req/04 §3.5；06 §4.7 通用 KV）。

动作落 ``cli/_common.py``（跨组共享：execute/suite 复用）；补录交互经
monkeypatch 替换 prompts 原语（隐藏输入 TTY 路径无法管道验证，同
test_cli_auth 范式）；密钥区路径由 conftest autouse 钉到 tmp。
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_eval.cli._common import ensure_sut_credentials
from agent_eval.core.exceptions import SUTAuthError
from agent_eval.execution.auth.secrets_store import load_secrets_file, save_secrets_file
from agent_eval.execution.registry import AuthConfig, AuthLoginConfig, SUTSystemConfig

_LOGIN = AuthLoginConfig(
    method="POST",
    path="/api/login",
    body_template='{"u": "{{ username }}", "p": "{{ password }}"}',
)


def _sut(ref: str | None = "SASAN") -> SUTSystemConfig:
    return SUTSystemConfig(
        name="chat-sut",
        channel="agent_protocol",
        base_url="https://sut.example.com",
        auth=AuthConfig(type="api_login", credential_ref=ref, login=_LOGIN),
    )


def _patch_prompts(
    monkeypatch: pytest.MonkeyPatch,
    *,
    confirm_value: bool,
    answers: dict[str, str],
) -> list[str]:
    """替换向导原语（_fill 函数内延迟 import，patch 模块属性即生效）。

    confirm 固定返回；ask 按字段名应答 answers（缺字段即失败，防意外提示；
    字段提示顺序按字母序，与测试书写顺序无关）。返回 calls 记录交互轨迹。
    """
    calls: list[str] = []
    remaining = dict(answers)

    def fake_confirm(label: str, **_: Any) -> bool:
        calls.append("confirm")
        return confirm_value

    def fake_ask(label: str, **_: Any) -> str:
        calls.append(f"ask:{label}")
        field = label.rsplit(".", 1)[-1]
        if field not in remaining:
            pytest.fail(f"意外的输入请求: {label}")
        return remaining.pop(field)

    monkeypatch.setattr("agent_eval.cli.console.prompts.confirm", fake_confirm)
    monkeypatch.setattr("agent_eval.cli.console.prompts.ask", fake_ask)
    return calls


def test_fill_saves_missing_fields_then_recheck_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_prompts(
        monkeypatch, confirm_value=True, answers={"username": "user1", "password": "pw1"}
    )

    ensure_sut_credentials(_sut())  # 补录后复检通过，不抛

    assert load_secrets_file()["SASAN"] == {"username": "user1", "password": "pw1"}
    assert calls[0] == "confirm"
    assert set(calls[1:]) == {"ask:SASAN.username", "ask:SASAN.password"}


def test_fill_merges_into_existing_ref_without_clobber(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_secrets_file({"SASAN": {"username": "kept"}, "OTHER": {"token": "t"}})
    _patch_prompts(monkeypatch, confirm_value=True, answers={"password": "pw1"})
    # username 已录不算缺 → 只补 password，已录值与其它 ref 不动
    ensure_sut_credentials(_sut())
    assert load_secrets_file() == {
        "SASAN": {"username": "kept", "password": "pw1"},
        "OTHER": {"token": "t"},
    }


def test_declined_confirm_falls_back_to_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompts(monkeypatch, confirm_value=False, answers={})
    with pytest.raises(SUTAuthError, match="secrets set SASAN."):
        ensure_sut_credentials(_sut())
    assert not load_secrets_file()  # 未落盘


def test_empty_input_cancels_whole_fill_no_partial_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_prompts(monkeypatch, confirm_value=True, answers={"username": "user1", "password": ""})
    with pytest.raises(SUTAuthError, match="凭证未配置"):
        ensure_sut_credentials(_sut())
    assert not load_secrets_file()  # password 空输入 → 整体取消，不留半截状态


def test_no_input_env_keeps_original_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_EVAL_NO_INPUT", "1")

    def _boom(*_: Any, **__: Any) -> None:
        pytest.fail("--no-input 下不得进入交互补录")

    monkeypatch.setattr("agent_eval.cli.console.prompts.confirm", _boom)
    monkeypatch.setattr("agent_eval.cli.console.prompts.ask", _boom)
    with pytest.raises(SUTAuthError, match="secrets set"):  # SUTAuthError 而非 exit 2
        ensure_sut_credentials(_sut())


def test_complete_credentials_noop_without_prompting(monkeypatch: pytest.MonkeyPatch) -> None:
    save_secrets_file({"sasan": {"username": "u", "password": "p"}})  # ref 大小写不敏感
    _patch_prompts(monkeypatch, confirm_value=True, answers={})
    ensure_sut_credentials(_sut())  # 不抛、不提示


def test_missing_ref_config_error_bypasses_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    # ref 缺失属 sut_config 配置错误：补录无从下手，仍 fail fast 报告
    _patch_prompts(monkeypatch, confirm_value=True, answers={})
    with pytest.raises(SUTAuthError, match="credential_ref"):
        ensure_sut_credentials(_sut(ref=None))
