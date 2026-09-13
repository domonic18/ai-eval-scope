"""SUTRegistry 与 sut_config v2 模型测试（arch/03 §4.0.3）。"""

from __future__ import annotations

import pytest

from agent_eval.core.exceptions import SUTChannelError
from agent_eval.execution.registry import (
    PollConfig,
    RequestStepConfig,
    RequestTemplateConfig,
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


# ── generic_http 通道（v4.7 落地）：request_template / response_mapping ──────


GENERIC_HTTP_YAML = """
sut:
  name: plain-api
  channel: generic_http
  base_url: https://api.example.com
  request_template:
    method: POST
    path: /v1/chat
    headers:
      X-Trace: "{{ metadata.task_id }}"
    body:
      query: "{{ input }}"
  response_mapping:
    text: data.answer
    files: data.files
"""


def test_load_generic_http_config(tmp_path) -> None:
    path = _write(tmp_path, "sut.yaml", GENERIC_HTTP_YAML)
    sut = SUTRegistry.load(path).default
    assert sut.channel == "generic_http"
    assert sut.request_template is not None
    assert sut.request_template.method == "POST"
    assert sut.request_template.path == "/v1/chat"
    assert sut.request_template.body == {"query": "{{ input }}"}
    assert sut.response_mapping == {"text": "data.answer", "files": "data.files"}


def test_request_template_method_normalized_and_validated() -> None:
    assert RequestTemplateConfig(method="post", path="/x").method == "POST"
    with pytest.raises(ValueError, match="method"):
        RequestTemplateConfig(method="BREW", path="/x")


def test_validate_generic_http_requires_request_template() -> None:
    doc: dict = {"sut": {"name": "x", "channel": "generic_http", "base_url": "https://x"}}
    errors = validate_sut_config_document(doc)
    assert any("request_template" in e for e in errors)


def test_validate_generic_http_rejects_unknown_mapping_keys() -> None:
    doc: dict = {
        "sut": {
            "name": "x",
            "channel": "generic_http",
            "base_url": "https://x",
            "request_template": {"path": "/chat"},
            "response_mapping": {"answer": "a.b"},
        }
    }
    errors = validate_sut_config_document(doc)
    assert any("未知键 ['answer']" in e for e in errors)


def test_validate_generic_http_rejects_unknown_template_fields() -> None:
    doc: dict = {
        "sut": {
            "name": "x",
            "channel": "generic_http",
            "base_url": "https://x",
            "request_template": {"path": "/chat", "url": "https://other"},  # url 是发明的
        }
    }
    errors = validate_sut_config_document(doc)
    assert any("sut.request_template 含未知字段 'url'" in e for e in errors)


def test_validate_generic_http_accepts_full_config() -> None:
    import yaml

    doc = yaml.safe_load(GENERIC_HTTP_YAML)
    assert validate_sut_config_document(doc) == []


# ── steps 链式模板 + 模板变量审计（v4.8：jxb 事故——input 未消费/变量拼错落盘前打回）──


CHAIN_YAML = """
sut:
  name: chained-api
  channel: generic_http
  base_url: https://api.example.com
  request_template:
    steps:
      - name: create
        method: POST
        path: /chat/conversations
        body: {student_id: null}
      - name: send
        method: POST
        path: /chat/conversations/{{ create.data.id }}/messages
        body: {content: "{{ input }}"}
      - name: history
        method: GET
        path: /chat/conversations/{{ create.data.id }}
  response_mapping:
    text: data.messages.-1.content
"""


def test_load_generic_http_steps_chain(tmp_path) -> None:
    path = _write(tmp_path, "sut.yaml", CHAIN_YAML)
    rt = SUTRegistry.load(path).default.request_template
    assert rt is not None
    assert rt.method is None and rt.path is None  # steps 形态下单步字段为空
    assert [s.name for s in rt.steps] == ["create", "send", "history"]
    assert rt.steps[1].path == "/chat/conversations/{{ create.data.id }}/messages"
    assert rt.steps[1].body == {"content": "{{ input }}"}


def test_validate_generic_http_accepts_steps_chain() -> None:
    import yaml

    assert validate_sut_config_document(yaml.safe_load(CHAIN_YAML)) == []


def test_validate_generic_http_rejects_template_without_input() -> None:
    """事故根因的机械判定：模板不消费 {{ input }} = 指令从未发给被测系统。"""
    doc: dict = {
        "sut": {
            "name": "x",
            "channel": "generic_http",
            "base_url": "https://x",
            "request_template": {"method": "POST", "path": "/chat", "body": {"q": "固定词"}},
        }
    }
    errors = validate_sut_config_document(doc)
    assert any("未引用 {{ input }}" in e for e in errors)


def test_validate_generic_http_rejects_undefined_step_reference() -> None:
    doc: dict = {
        "sut": {
            "name": "x",
            "channel": "generic_http",
            "base_url": "https://x",
            "request_template": {
                "steps": [
                    {
                        "name": "send",
                        "method": "POST",
                        "path": "/c/{{ create.data.id }}/m",  # create 未定义（拼错/漏步）
                        "body": {"content": "{{ input }}"},
                    }
                ]
            },
        }
    }
    errors = validate_sut_config_document(doc)
    assert any("引用未定义变量 'create'" in e for e in errors)


def test_validate_generic_http_rejects_forward_step_reference() -> None:
    """后续步只能引用**前序**步骤——前向引用同样打回。"""
    doc: dict = {
        "sut": {
            "name": "x",
            "channel": "generic_http",
            "base_url": "https://x",
            "request_template": {
                "steps": [
                    {
                        "name": "first",
                        "method": "POST",
                        "path": "/p",
                        "body": {"q": "{{ second.data.id }}", "x": "{{ input }}"},
                    },
                    {"name": "second", "method": "GET", "path": "/q"},
                ]
            },
        }
    }
    errors = validate_sut_config_document(doc)
    assert any("引用未定义变量 'second'" in e for e in errors)


def test_validate_generic_http_rejects_steps_single_mix() -> None:
    doc: dict = {
        "sut": {
            "name": "x",
            "channel": "generic_http",
            "base_url": "https://x",
            "request_template": {
                "path": "/chat",
                "steps": [{"name": "a", "method": "GET", "path": "/x"}],
            },
        }
    }
    errors = validate_sut_config_document(doc)
    assert any("不可混用" in e for e in errors)


def test_validate_generic_http_rejects_duplicate_step_names() -> None:
    doc: dict = {
        "sut": {
            "name": "x",
            "channel": "generic_http",
            "base_url": "https://x",
            "request_template": {
                "steps": [
                    {"name": "a", "method": "GET", "path": "/x"},
                    {"name": "a", "method": "GET", "path": "/y"},
                ]
            },
        }
    }
    errors = validate_sut_config_document(doc)
    assert any("重复步骤名" in e for e in errors)


def test_validate_generic_http_rejects_reserved_step_name() -> None:
    doc: dict = {
        "sut": {
            "name": "x",
            "channel": "generic_http",
            "base_url": "https://x",
            "request_template": {"steps": [{"name": "input", "method": "GET", "path": "/x"}]},
        }
    }
    errors = validate_sut_config_document(doc)
    assert any("与模板根变量冲突" in e for e in errors)


def test_request_template_without_steps_or_path_rejected() -> None:
    with pytest.raises(ValueError, match="二选一"):
        RequestTemplateConfig()


# ── once 会话步 + poll 轮询步（plan/06 M1+M2）：形态校验与审计扩展 ────────────


def test_validate_generic_http_accepts_once_and_poll_chain() -> None:
    """once + poll 链通过审计：poll until 自引用本步响应合法（do-while 先发后判）。"""
    doc: dict = {
        "sut": {
            "name": "x",
            "channel": "generic_http",
            "base_url": "https://x",
            "request_template": {
                "steps": [
                    {
                        "name": "create",
                        "method": "POST",
                        "path": "/jobs",
                        "once": True,
                        "body": {"q": "{{ input }}"},
                    },
                    {
                        "name": "status",
                        "method": "GET",
                        "path": "/jobs/{{ create.data.id }}",
                        "poll": {
                            "until": "{{ status.data.state == 'succeeded' }}",
                            "interval_s": 3,
                            "timeout_s": 300,
                        },
                    },
                ]
            },
        }
    }
    assert validate_sut_config_document(doc) == []


def test_validate_step_rejects_once_and_poll_together() -> None:
    """once 与 poll 互斥（决策 5：只执行一次 vs 反复执行语义冲突）。"""
    with pytest.raises(ValueError, match="互斥"):
        RequestStepConfig(
            name="a",
            method="GET",
            path="/x",
            once=True,
            poll=PollConfig(until="{{ a.ok }}"),
        )


def test_validate_step_rejects_nonpositive_interval_and_timeout() -> None:
    with pytest.raises(ValueError):
        PollConfig(until="{{ a.ok }}", interval_s=0)
    with pytest.raises(ValueError):
        PollConfig(until="{{ a.ok }}", timeout_s=-1)


def test_validate_step_rejects_timeout_over_cap() -> None:
    """timeout_s 防呆上界 900（plan/06 §3.4）。"""
    with pytest.raises(ValueError):
        PollConfig(until="{{ a.ok }}", timeout_s=901)


def test_validate_generic_http_rejects_last_step_once() -> None:
    """末步不可为 once——续轮末步命中缓存即无响应可提取。"""
    doc: dict = {
        "sut": {
            "name": "x",
            "channel": "generic_http",
            "base_url": "https://x",
            "request_template": {
                "steps": [
                    {"name": "a", "method": "GET", "path": "/x", "body": {"q": "{{ input }}"}},
                    {"name": "b", "method": "GET", "path": "/y", "once": True},
                ]
            },
        }
    }
    errors = validate_sut_config_document(doc)
    assert any("末步" in e and "once" in e for e in errors)


def test_validate_generic_http_rejects_undefined_variable_in_until() -> None:
    """until 表达式参与变量审计：拼错步骤名落盘前打回。"""
    doc: dict = {
        "sut": {
            "name": "x",
            "channel": "generic_http",
            "base_url": "https://x",
            "request_template": {
                "steps": [
                    {
                        "name": "status",
                        "method": "GET",
                        "path": "/j",
                        "poll": {"until": "{{ stat.data.state == 'done' }}"},
                    }
                ]
            },
        }
    }
    errors = validate_sut_config_document(doc)
    assert any("引用未定义变量 'stat'" in e for e in errors)


def test_validate_generic_http_legacy_chain_without_new_fields_passes() -> None:
    """存量 v4.8 链（无 once/poll）零改动通过（NF-2 存量兼容）。"""
    import yaml

    assert validate_sut_config_document(yaml.safe_load(CHAIN_YAML)) == []
