# 评估器开发规范（Python）

本目录是自包含、pip-installable 的评估器（`agent-eval` CLI），对称于 `web/` 可观测平台。

## 环境

- Python 3.11+，依赖用 `uv` 管理（`uv.lock`）
- 安装：`uv sync --extra dev`
- CLI：`uv run agent-eval --help`

## 代码风格（强制）

- **ruff**：`line-length=100`，`select = ["E","F","I","N","W","UP"]`（见 `pyproject.toml [tool.ruff]`）。提交前 `uv run ruff format && uv run ruff check --fix`。
- **类型提示必需**：函数参数与返回值标注；文件首行 `from __future__ import annotations`；优先 `X | Y` 而非 `Optional[X]`。
- **命名**：类 `UpperCamelCase`；函数/变量 `snake_case`；常量 `UPPER_SNAKE`；枚举成员 `UPPER_SNAKE`、值为 `kebab-case` 或 `snake_case`。
- **数据模型**：需要序列化用 Pydantic v2 `BaseModel`（带 `save()/load()`）；纯内存结构用 `@dataclass`。
- **枚举**：定义在 `core/types.py`，统一 `(str, Enum)` 基类 + 中文 docstring。
- **异常**：继承 `AgentEvalError`（`core/exceptions.py`），按模块分组（`XxxError` / `XxxNotFoundError` / `XxxValidationError`），带额外字段的子类在 `__init__` 设同名属性。

## 测试（强制）

- 每个模块对应 `tests/unit/test_*.py`；黄金样本在 `tests/fixtures/golden/`。
- **禁止联网测试**：第三方库（huggingface_hub / modelscope / langfuse 等）用 `monkeypatch` / `MagicMock` mock；真实下载验证放 `tests/integration/` 且默认 skip。
- 文件系统用 `tmp_path` fixture 隔离。
- 断言用 `assert` / `pytest.raises(XxxError)`；测试命名 `test_<行为>[_<条件>]`。
- CLI 测试用 `typer.testing.CliRunner` + `monkeypatch` mock 内部函数。
- 可选依赖在 `tests/conftest.py` 顶部 `sys.modules.setdefault(...)` mock（仿 langfuse 范式）。

## 目录约定

- `agent_eval/` 自包含、pip-installable；随包资源在 `agent_eval/assets/`（经 `PACKAGE_ROOT` 定位，不硬编码绝对路径）。
- 运行产物落 `workspace/`，按 `WORKSPACE_DIR`（或 `CWD/workspace`）定位。
- 可选第三方依赖（huggingface_hub / modelscope / playwright）放 `[project.optional-dependencies]`，代码内**惰性导入** + 友好错误提示（仿 `observability/render.py` 的 Playwright 范式）。

## 质量检查（提交前）

```bash
uv run ruff check agent_eval tests
uv run ruff format --check agent_eval tests
uv run pytest tests/unit -q
```

详见根 [`CLAUDE.md`](../CLAUDE.md) 与 [规范索引](../docs/standard/README.md)。
