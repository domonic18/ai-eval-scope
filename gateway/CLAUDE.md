# eval-gateway 开发规范（Python）

第三方系统对接的评估接入服务（代号 `eval-gateway`）：第三方（如课件制作平台）以 HMAC API Key 鉴权提交待评估内容（HTML/Markdown，单页或单元），服务异步调用评估器 `eval_packages()` 评估、经 `observability` 回传结果到 Web 平台，并提供任务状态查询。

> 设计基线：[12 第三方系统对接方案](../docs/arch/12第三方系统对接方案.md)。复用评估器 SDK（[04 评估引擎设计](../docs/arch/04评估引擎设计.md)）与 Web 摄取/HMAC 鉴权（[09 Web 可观测平台架构设计](../docs/arch/09Web可观测平台架构设计.md) §6.3/§7）。

## 环境

- Python 3.11+，依赖用 `uv` 管理。
- 安装：`uv sync --extra dev`（开发）。
- 服务：`uv run eval-gateway`（或 `uv run uvicorn eval_gateway.main:app --port 9102`）。所有命令从 `gateway/` 执行，或用根 `make gateway-*` 目标。
- 依赖评估器：`pyproject.toml` 以 path 依赖复用 `../evaluator`（`agent-eval`），可直接 `from agent_eval... import`。

## 配置（环境变量，从仓库根 `.env` 读取）

复用 Web 的变量：
- `PLATFORM_DATABASE_URL` — 共享 PG（`gateway.jobs` 表建在独立 schema `gateway`，**由 `make db-init` 创建、gateway 代码不建库**；gateway 只读 web `public.api_keys` 做验签）。
- `PLATFORM_KEY_ENCRYPTION_KEY` — AES-256-GCM 解密 `api_keys.secret_encrypted`（key = SHA256(此值)）。

gateway 自身（`EVALGATEWAY_*`）：`EVALGATEWAY_PORT`(默认 9000，SCF 要求)、`EVALGATEWAY_WORKER_CONCURRENCY`(默认 2)、`EVALGATEWAY_MAX_UPLOAD_MB`(默认 50)、`EVALGATEWAY_WEB_BASE_URL`、`EVALGATEWAY_UPLOAD_DIR`。

评估器回传透传（`AGENT_EVAL_*`，见 `evaluator/agent_eval/observability/config.py`）。

## 代码风格（强制）

- **ruff**：`line-length=100`，`select = ["E","F","I","N","W","UP"]`。提交前 `uv run ruff format && uv run ruff check --fix`。
- **类型提示必需**：参数与返回值标注；文件首行 `from __future__ import annotations`；优先 `X | Y`。
- **命名**：类 `UpperCamelCase`；函数/变量 `snake_case`；常量 `UPPER_SNAKE`；枚举成员 `UPPER_SNAKE`、值 `kebab-case`/`snake_case`。
- **数据模型**：序列化用 Pydantic v2；DB 映射用 SQLAlchemy 2.x declarative；纯内存用 `@dataclass`。
- **枚举**：定义在 `core/types.py`，统一 `(str, Enum)` + 中文 docstring。
- **异常**：继承 `GatewayError`（`core/exceptions.py`，带 `message` + `details`），按模块分组。
- **日志**：`structlog`（`core/logging.py`），`get_logger(__name__)`。

## 目录约定

- 自包含 pip-installable；运行产物落 `workspace/gateway/`（上传临时物化目录、worker 输出）。
- 复用评估器资源（规则集等）经 `agent_eval.config.paths` 定位，不硬编码路径。

## 测试（强制）

- 每模块对应 `tests/unit/test_*.py`。
- **禁止联网**：`agent_eval.orchestrator.eval_packages`、`ResultSink.flush`、（必要时）`PackageBuilder` 用 `monkeypatch`/`AsyncMock` mock；文件系统用 `tmp_path` 隔离。
- API 测试用 `httpx.AsyncClient` + `pytest-asyncio`。
- 断言用 `assert` / `pytest.raises(GatewayError)`；命名 `test_<行为>[_<条件>]`。

## 质量检查（提交前）

```bash
uv run ruff check eval_gateway tests
uv run ruff format --check eval_gateway tests
uv run mypy eval_gateway --ignore-missing-imports
uv run pytest tests/unit -q
```

详见根 [`CLAUDE.md`](../CLAUDE.md) 与 [规范索引](../docs/standard/README.md)。
