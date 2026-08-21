"""SUTRegistry 与 sut_config v2 模型测试（arch/03 §4.0.3）。"""

from __future__ import annotations

import pytest

from agent_eval.core.exceptions import SUTChannelError
from agent_eval.execution.registry import SUTRegistry, SUTSystemConfig

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
