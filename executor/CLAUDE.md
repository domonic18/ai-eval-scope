# 执行器开发规范（Python）

本目录是评估执行器（`eval-executor`）：SCF 事件函数镜像 + 本地 worker 轮询，认领 `eval_jobs` → presigned 下载输入 → 调评估器 `eval_packages()` → 以提交者身份经 ResultSink 回传 Web `/api/public/ingest` → 更新任务状态。承担评测长时执行（摆脱 Web 函数 900s 限制，最长 24h），以 path 依赖复用 `../evaluator`，不复制评估逻辑。

> 设计基线：[09 Web 可观测平台架构设计 §7.7](../docs/arch/09Web可观测平台架构设计.md)、[12 第三方系统对接方案](../docs/arch/12第三方系统对接方案.md)

## 目录结构

```
executor/
├── eval_executor/
│   ├── executor/       entrypoint（入口）/ runner（单 job 执行）/ builder（评估器装配）
│   ├── queue/          jobs — eval_jobs 认领与状态更新
│   ├── models/         db — SQLAlchemy async（复用 Web 治理的 public.* 表，禁止建表）
│   ├── auth/           crypto / repo — 提交者 API Key 解密与回传身份
│   ├── storage/        input_loader（presigned URL 下载输入包）/ session
│   ├── worker/         loop — 轮询模式（docker-compose 本地栈）
│   ├── config/         settings — pydantic-settings（EVALEXECUTOR_*）
│   ├── core/           exceptions / types / logging（structlog）
│   └── rules/          registry — 规则集解析
└── tests/unit/         每模块对应 test_*.py
```

## 环境

- Python 3.11+，依赖用 `uv` 管理（`uv.lock`）。
- 安装：`uv sync --extra dev`（开发）。
- 入口：`uv run eval-executor`，或 `python -m eval_executor.executor.entrypoint`。
- 复用评估器：`pyproject.toml` 以 path 依赖引入 `../evaluator`（`agent-eval[llm]`，uv editable）——评估逻辑改动直接在 evaluator 做。

## 触发模式

| 模式 | 触发 | 说明 |
|------|------|------|
| SCF | `SCF_CUSTOM_CONTAINER_EVENT` | 生产：腾讯云 SCF 事件函数，每次 Invoke 执行一个 job |
| 本地调试 | `EVALEXECUTOR_JOB_JSON` | 注入单个事件 JSON，无需真实 SCF |
| worker | `EVALEXECUTOR_WORKER_ENABLED=true` | 本地开发：轮询 `eval_jobs`（docker-compose 用） |

## 配置

- 环境变量从仓库根 `.env` 读取；复用 Web 的 `PLATFORM_DATABASE_URL`、`PLATFORM_KEY_ENCRYPTION_KEY`。
- executor 自身（`EVALEXECUTOR_*`）：`WORKER_ENABLED` / `WORKER_CONCURRENCY` / `WEB_BASE_URL` / `WORKSPACE` / `POLL_INTERVAL_SEC` / `HTTP_TIMEOUT_SEC`。
- 评估器回传透传 `AGENT_EVAL_*`；镜像须 `AGENT_EVAL_UPLOAD=true`（见 Dockerfile）。

## 代码风格（强制）

同评估器规范（[`evaluator/CLAUDE.md`](../evaluator/CLAUDE.md)）：ruff line-length=100、类型提示必需、`X | Y` 联合、异常继承本包 `core/exceptions.py` 基类。

## 测试（强制）

- 每模块对应 `tests/unit/test_*.py`（entrypoint / runner / builder / jobs / worker loop / input_loader / crypto）。
- **禁止联网测试**：DB、Web 回传、对象存储下载一律 mock；文件系统用 `tmp_path` 隔离。
- 事件处理走 `EVALEXECUTOR_JOB_JSON` 注入路径断言。

## 质量检查（提交前）

```bash
uv run ruff check eval_executor tests
uv run ruff format --check eval_executor tests
uv run pytest tests/unit -q
```

详见根 [`CLAUDE.md`](../CLAUDE.md) 与 [规范索引](../docs/standard/README.md)。
