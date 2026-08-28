# eval-executor

评估执行器镜像 —— SCF **事件函数（Job 镜像 + 异步执行）**，承担评测的
长时执行（摆脱 Web 函数 900s 限制，最长 24h）。

> 设计基线：[docs/arch/09Web可观测平台架构设计.md §7.7](../docs/arch/09Web可观测平台架构设计.md) 与 [docs/arch/12第三方系统对接方案.md](../docs/arch/12第三方系统对接方案.md)

## 职责

- 接收 SCF 事件（`SCF_CUSTOM_CONTAINER_EVENT`），执行单个 `eval_jobs` 任务；
- 经 Web 签发的 presigned GET URL 下载输入（**不持对象存储凭据**）；
- 调评估器 `eval_packages()` 评估；
- 以提交者身份经 `ResultSink` 回传结果到 Web `/api/public/ingest`；
- 更新 `public.eval_jobs` 状态机。

## 环境

- Python 3.11+，依赖用 `uv` 管理。
- 安装：`uv sync --extra dev`（开发）。
- 入口：`uv run eval-executor`，或 `python -m eval_executor.executor.entrypoint`。
- 复用评估器：`pyproject.toml` 以 path 依赖复用 `../evaluator`（`agent-eval`）。

## 触发模式

| 模式 | 触发 | 说明 |
|------|------|------|
| SCF | `SCF_CUSTOM_CONTAINER_EVENT` | 生产：腾讯云 SCF 事件函数，每次 Invoke 执行一个 job |
| 本地调试 | `EVALEXECUTOR_JOB_JSON` | 注入单个事件 JSON，无需真实 SCF |
| worker | `EVALEXECUTOR_WORKER_ENABLED=true` | 本地开发：轮询 `eval_jobs`（docker-compose 用） |

## 配置（环境变量，从仓库根 `.env` 读取）

复用 Web 的 `PLATFORM_DATABASE_URL`、`PLATFORM_KEY_ENCRYPTION_KEY`。

executor 自身（`EVALEXECUTOR_*`）：`EVALEXECUTOR_WORKER_ENABLED`、
`EVALEXECUTOR_WORKER_CONCURRENCY`、`EVALEXECUTOR_WEB_BASE_URL`、`EVALEXECUTOR_WORKSPACE`、
`EVALEXECUTOR_POLL_INTERVAL_SEC`、`EVALEXECUTOR_HTTP_TIMEOUT_SEC`。

评估器回传透传（`AGENT_EVAL_*`）；镜像须 `AGENT_EVAL_UPLOAD=true`（见 Dockerfile）。

## 代码风格 / 测试 / 质量检查

同评估器规范（ruff / mypy / pytest，line-length=100，禁止联网测试）。详见根
[`CLAUDE.md`](../CLAUDE.md) 与 [规范索引](../docs/standard/README.md)。
