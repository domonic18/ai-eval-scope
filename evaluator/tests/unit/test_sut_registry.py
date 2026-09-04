"""SUTRegistry 与 sut_config v2 模型测试（arch/03 §4.0.3）。"""

from __future__ import annotations

import pytest

from agent_eval.core.exceptions import SUTChannelError
from agent_eval.execution.registry import (
    SUTRegistry,
    SUTSystemConfig,
    resolve_login_url,
    validate_sut_config_document,
)

AGENT_PROTOCOL_YAML = """
sut:
  name: courseware-agent
  channel: agent_protocol
  base_url: https://agent.example.com
  protocol_version: "0.1.6"
  exec_mode: wait
  auth:
    type: static_token
    credential_ref: COURSEWARE_AGENT
  output_paths:
    files_field: values.output_files
    text_field: values.content
  on_completion: delete
"""


def _write(tmp_path, name: str, content: str):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_load_agent_protocol_config(tmp_path) -> None:
    path = _write(tmp_path, "sut.yaml", AGENT_PROTOCOL_YAML)
    registry = SUTRegistry.load(path)
    sut = registry.default
    assert sut.name == "courseware-agent"
    assert sut.channel == "agent_protocol"
    assert sut.auth.type == "static_token"
    assert sut.auth.credential_ref == "COURSEWARE_AGENT"
    assert sut.output_paths.files_field == "values.output_files"
    assert sut.on_completion == "delete"


def test_load_dir_merges_multiple_systems(tmp_path) -> None:
    _write(tmp_path, "a.yaml", AGENT_PROTOCOL_YAML)
    _write(
        tmp_path,
        "b.yaml",
        """
sut:
  name: travel-agent
  channel: agent_protocol
  base_url: https://travel.example.com
""",
    )
    registry = SUTRegistry.load_dir(tmp_path)
    assert registry.names == ["courseware-agent", "travel-agent"]
    with pytest.raises(SUTChannelError, match="显式指定"):
        _ = registry.default
    assert registry.get("travel-agent").base_url == "https://travel.example.com"
    with pytest.raises(SUTChannelError, match="未注册"):
        registry.get("ghost")


def test_get_falls_back_to_file_stem_when_name_drifts(tmp_path) -> None:
    """stem 容错（实测两次复发：向导/CLI 按文件名列出并选择 SUT，Agent 生成包的
    sut.name 与文件名漂移——精确名未命中按 stem 兜底，机械容错不设门禁）。"""
    _write(
        tmp_path,
        "sasan-agent-security.yaml",  # 文件名 stem
        """
sut:
  name: sasan-agent-staging  # 注册名（与文件名漂移）
  channel: agent_protocol
  base_url: https://sut.example.com
""",
    )
    registry = SUTRegistry.load_dir(tmp_path)
    by_stem = registry.get("sasan-agent-security")  # 向导传的是 stem
    assert by_stem.name == "sasan-agent-staging"
    assert registry.get("sasan-agent-staging") is by_stem  # 注册名照常精确命中


def test_get_miss_reports_registered_names_and_file_stems(tmp_path) -> None:
    """双不命中：报错同时携带注册名与文件名两份清单（用户可对照选对标识）。"""
    _write(
        tmp_path,
        "some-file.yaml",
        """
sut:
  name: registered-name
  channel: agent_protocol
  base_url: https://sut.example.com
""",
    )
    registry = SUTRegistry.load_dir(tmp_path)
    with pytest.raises(SUTChannelError) as err:
        registry.get("ghost")
    assert err.value.details["available"] == ["registered-name"]
    assert err.value.details["file_names"] == ["some-file"]


def test_missing_sut_section_raises(tmp_path) -> None:
    path = _write(tmp_path, "bad.yaml", "other: 1\n")
    with pytest.raises(SUTChannelError, match="缺少顶层 'sut:'"):
        SUTRegistry.load(path)


def test_channel_validator() -> None:
    with pytest.raises(ValueError, match="channel"):
        SUTSystemConfig(name="x", channel="grpc", base_url="https://x")
    with pytest.raises(ValueError, match="exec_mode"):
        SUTSystemConfig(name="x", channel="agent_protocol", base_url="https://x", exec_mode="fast")
    with pytest.raises(ValueError, match="stream_mode"):
        SUTSystemConfig(
            name="x", channel="agent_protocol", base_url="https://x", stream_mode="proto"
        )


def test_auth_type_validator() -> None:
    with pytest.raises(ValueError, match="auth.type"):
        SUTSystemConfig.model_validate(
            {
                "name": "x",
                "channel": "agent_protocol",
                "base_url": "https://x",
                "auth": {"type": "oauth2"},
            }
        )


# ── ${VAR} / ${VAR:-默认值} 环境变量展开（arch/17 开源红线：内置包不硬编码内部域名）──

PLACEHOLDER_YAML = """
sut:
  name: sasan-agent
  channel: agent_protocol
  base_url: ${SASAN_AGENT_URL:-https://agent-server.example.com}
  timeout: 300
  auth:
    type: api_login
    credential_ref: SASAN
    login:
      method: POST
      path: ${SASAN_LOGIN_URL:-https://sasan-server.example.com/users/login}
      body_template: '{"phone": "{{ username }}"}'
"""


def test_env_ref_expands_from_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SASAN_AGENT_URL", "https://real.internal.example.com")
    monkeypatch.setenv("SASAN_LOGIN_URL", "https://login.internal.example.com/api")
    registry = SUTRegistry.load(_write(tmp_path, "sut.yaml", PLACEHOLDER_YAML))
    sut = registry.default
    assert sut.base_url == "https://real.internal.example.com"
    assert sut.auth.login.path == "https://login.internal.example.com/api"


def test_env_ref_falls_back_to_default_when_unset(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SASAN_AGENT_URL", raising=False)
    monkeypatch.delenv("SASAN_LOGIN_URL", raising=False)
    sut = SUTRegistry.load(_write(tmp_path, "sut.yaml", PLACEHOLDER_YAML)).default
    assert sut.base_url == "https://agent-server.example.com"
    # 无占位的字段不展开：Jinja2 模板变量 {{ }} 原样保留；非字符串字段不动
    assert sut.timeout == 300
    assert sut.auth.login.body_template == '{"phone": "{{ username }}"}'


def test_env_ref_undefined_without_default_raises(tmp_path, monkeypatch) -> None:
    # 裸 ${VAR}（无默认值）：未定义即报错，优于保留原文去请求占位端点
    monkeypatch.delenv("SASAN_AGENT_URL", raising=False)
    bare = PLACEHOLDER_YAML.replace(
        "${SASAN_AGENT_URL:-https://agent-server.example.com}", "${SASAN_AGENT_URL}"
    )
    with pytest.raises(SUTChannelError, match="SASAN_AGENT_URL"):
        SUTRegistry.load(_write(tmp_path, "sut.yaml", bare))


def test_builtin_chat_package_has_no_internal_domain(monkeypatch) -> None:
    """开源红线：内置包 sasan-agent 未配 env 时回退占位域名（内部 staging 域名不入包）。"""
    from agent_eval.packages.manager import PackageManager

    monkeypatch.delenv("SASAN_AGENT_URL", raising=False)
    monkeypatch.delenv("SASAN_LOGIN_URL", raising=False)
    monkeypatch.delenv("SASAN_AGENT_MODEL_ID", raising=False)
    pkg = PackageManager().resolve_ref("chat")
    registry = SUTRegistry.load_dir(pkg.root / "sut_configs")
    sut = registry.get("sasan-agent")
    assert sut.base_url == "https://agent-server.example.com"
    assert "bj33smarter" not in str(sut.model_dump())
    assert sut.configurable["modelId"] == "1"  # 展开结果为字符串


# ── resolve_login_url：URL 解析单源（执行器登录与落盘对账门禁共用） ──────────


def test_resolve_login_url_absolute_path_used_verbatim() -> None:
    assert (
        resolve_login_url("https://agent.example.com", "https://login.example.com/users/login")
        == "https://login.example.com/users/login"
    )


def test_resolve_login_url_relative_joins_sut_base_url() -> None:
    assert resolve_login_url("https://api.example.com/", "/users/login") == (
        "https://api.example.com/users/login"
    )


# ── validate_sut_config_document：未知键显式拒绝（静默丢弃 → 显式打回） ──────


def _minimal_sut() -> dict:
    return {
        "sut": {
            "name": "s",
            "channel": "agent_protocol",
            "base_url": "https://s.example.com",
        }
    }


def test_validate_document_accepts_minimal_config() -> None:
    assert validate_sut_config_document(_minimal_sut()) == []


def test_validate_document_rejects_invented_login_base_url() -> None:
    """实测教训：Agent 自造 login.base_url 被执行器静默丢弃，登录拼回页面域 404。"""
    doc = _minimal_sut()
    doc["sut"]["auth"] = {
        "type": "api_login",
        "credential_ref": "r",
        "login": {
            "method": "POST",
            "path": "/users/login",
            "base_url": "https://login.example.com",  # 发明的字段
            "body_template": '{"u": "{{ username }}"}',
        },
    }
    errors = validate_sut_config_document(doc)
    assert any("未知字段 'base_url'" in e and "完整 http(s):// URL" in e for e in errors)


def test_validate_document_reports_required_and_enum_errors() -> None:
    doc = {"sut": {"name": "s", "channel": "nope"}}
    errors = validate_sut_config_document(doc)
    assert any("channel" in e for e in errors)
    assert any("base_url" in e for e in errors)


def test_validate_document_missing_sut_section() -> None:
    assert validate_sut_config_document({"foo": 1}) == ["sut_config 缺少顶层 'sut:' 段"]


def test_validate_document_undefined_env_ref_reported() -> None:
    doc = _minimal_sut()
    doc["sut"]["base_url"] = "${UNDEFINED_VAR_X}"
    errors = validate_sut_config_document(doc)
    assert any("UNDEFINED_VAR_X" in e for e in errors)
