# 评估器开发规范（Python）

本目录是自包含、pip-installable 的评估器（`agent-eval` CLI），对称于 `web/` 可观测平台。

## 环境

- Python 3.11+，依赖用 `uv` 管理（`uv.lock`）。
- 安装：`uv sync --group dev`（开发，PEP 735 依赖组——dev 工具链不入发布元数据）；`uv sync --extra llm`（LLM Judge 依赖，可选）；`uv sync --extra agent`（ExecutionAgent DeepAgents 底座，可选，见 arch/03 v4.6）。
- CLI：`uv run agent-eval --help`。所有 `uv run` / `agent-eval` 命令从 `evaluator/` 执行，或用根 `make` 目标自动切换。

## 配置

- 环境变量从仓库根 `.env` 读取（`load_dotenv()` 自动向上查找）。
- LLM 配置走双形态（arch/06 §4.6）：`agent-eval models set` 交互配置 → `~/.agent_eval/llm.json`（0600）；云端经 `AGENT_EVAL_HOST/API_KEY` 拉 `/api/public/llm-config`。固定三角色 text/vision/agent（`config/llm_resolution.py` 解析）。

## 代码风格（强制）

- **ruff**：`line-length=100`，`select = ["E","F","I","N","W","UP"]`（见 `pyproject.toml [tool.ruff]`）。提交前 `uv run ruff format && uv run ruff check --fix`。
- **类型提示必需**：函数参数与返回值标注；文件首行 `from __future__ import annotations`；优先 `X | Y` 而非 `Optional[X]`。
- **命名**：类 `UpperCamelCase`；函数/变量 `snake_case`；常量 `UPPER_SNAKE`；枚举成员 `UPPER_SNAKE`、值为 `kebab-case` 或 `snake_case`。
- **数据模型**：需要序列化用 Pydantic v2 `BaseModel`（带 `save()/load()`）；纯内存结构用 `@dataclass`。
- **枚举**：定义在 `core/types.py`，统一 `(str, Enum)` 基类 + 中文 docstring。
- **异常**：继承 `AgentEvalError`（`core/exceptions.py`），按模块分组（`XxxError` / `XxxNotFoundError` / `XxxValidationError`），带额外字段的子类在 `__init__` 设同名属性。

## 目录约定

- `agent_eval/` 自包含、pip-installable；随包资源在 `agent_eval/assets/`（经 `PACKAGE_ROOT` 定位，不硬编码绝对路径）。
- 运行产物落 `workspace/`，按 `WORKSPACE_DIR`（或 `CWD/workspace`）定位。
- 可选第三方依赖（huggingface_hub / modelscope / playwright）放 `[project.optional-dependencies]`，代码内**惰性导入** + 友好错误提示（仿 `observability/render.py` 的 Playwright 范式）。

## 测试（强制）

- 每个模块对应 `tests/unit/test_*.py`；黄金样本在 `tests/fixtures/golden/`。
- **禁止联网测试**：第三方库（huggingface_hub / modelscope / langfuse 等）用 `monkeypatch` / `MagicMock` mock；真实下载验证放 `tests/integration/` 且默认 skip。
- 文件系统用 `tmp_path` fixture 隔离。
- 断言用 `assert` / `pytest.raises(XxxError)`；测试命名 `test_<行为>[_<条件>]`。
- CLI 测试用 `typer.testing.CliRunner` + `monkeypatch` mock 内部函数。
- 可选依赖在 `tests/conftest.py` 顶部 `sys.modules.setdefault(...)` mock（仿 langfuse 范式）。
- **删符号同步清测试**：删除/重命名公共符号（含 `__init__` 重导出）时，同步 `grep -rn "<符号>" tests/` 清理**全目录**引用——`make check` 只收集 `tests/unit`，`tests/config`、`tests/evaluation` 等其余目录仅全量收集（曾因漏删 `resolve_api_key` 测试 import 导致发布流水线红，2026-09）。

## 质量检查（提交前）

```bash
uv run ruff check agent_eval tests
uv run ruff format --check agent_eval tests
uv run pytest tests/unit -q
```

> 上述为快门禁（仅 `tests/unit`）。功能分支**合入前 / 发布前**跑全量 `make test`（`pytest tests/`，与 Jenkins 质量门禁同口径，含 e2e/golden 慢测试）。

## 版本发布（PyPI，distribution 名 ai-eval-scope）

- **版本单源**：`uv run cz bump --dry-run --increment PATCH --yes` 先核对，去掉 `--dry-run` 实跑——一次改 `pyproject.toml` + `agent_eval/__init__.py::__version__` + CHANGELOG 并打 annotated tag。**禁止手改版本号**。
- **发布**：`git push --tags` 后 Jenkins Job `sasan-evalscope-pypi` → Build with Parameters（`TAG=vX.Y.Z`；`TEST_PYPI=true` 先演练 test.pypi.org，验收通过后 `false` 转正式）。流水线自带质量门禁、tag==`__version__` 断言、wheel/sdist 隔离冒烟。
- **纪律**：PyPI 同版本号**不可重传**——发布失败修复后必须 bump 新版本；正式发布前必先 TestPyPI 演练。
- 详见 [`cicd/README.md`](../cicd/README.md)（阶段表/凭证/本地验证）与 [arch/17](../docs/arch/17Python包发布方案.md)（方案与决策）。

详见根 [`CLAUDE.md`](../CLAUDE.md) 与 [规范索引](../docs/standard/README.md)。
