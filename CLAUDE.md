# Agent 能力评估系统（agent-eval-system）

基于 Agent-Driven 架构的评测框架，以课件生成为切入点，支持代码生成、RAG、对话等多类 Agent 评估。

## 项目结构

```
agent-eval-system/
├── evaluator/          # 评估器（Python，pip-installable，uv 管理）
├── web/                # 可观测平台（TypeScript，frontend + backend）
├── docs/               # 架构 / 需求 / 规范文档
├── cicd/               # 内部 CI（Jenkins + 腾讯工蜂）
├── scripts/            # 辅助脚本（db-apply.sh / db-apply-prod.sh 建库迁移、gen_rule_sets.py 等）
├── docker/ scripts/    # Dockerfile 与辅助脚本
├── Makefile            # 顶层任务入口（install / test / check / db-init / hooks ...）
└── docker-compose.yml  # 本地全栈（postgres + minio + web）
```

## 文档索引（按需阅读，勿全量加载）

- 整体架构：[`docs/arch/01整体架构设计.md`](docs/arch/01整体架构设计.md)
- CLI 使用教程：[`docs/guide/CLI使用教程.md`](docs/guide/CLI使用教程.md)（命令总览 / LLM Key 配置 / 课件与 Agent 评测实战）
- 评估引擎：[`docs/arch/04评估引擎设计.md`](docs/arch/04评估引擎设计.md)
- 数据管理与配置：[`docs/arch/06数据管理与配置规范.md`](docs/arch/06数据管理与配置规范.md)
- Web 可观测平台：[`docs/arch/09Web可观测平台架构设计.md`](docs/arch/09Web可观测平台架构设计.md)
- 第三方系统对接：[`docs/arch/12第三方系统对接方案.md`](docs/arch/12第三方系统对接方案.md)
- 评估指标与方法：[`docs/arch/07评估指标与方法.md`](docs/arch/07评估指标与方法.md)
- 数据集下载：[`docs/arch/10数据集下载设计.md`](docs/arch/10数据集下载设计.md)
- 配置管理：[`docs/arch/13配置管理设计.md`](docs/arch/13配置管理设计.md)
- 场景扩展：[`docs/arch/14场景扩展指南.md`](docs/arch/14场景扩展指南.md)（如何新增一个评估场景，含 entry_points 可插拔评估器）
- Python 包发布：[`docs/arch/17Python包发布方案.md`](docs/arch/17Python包发布方案.md)（改名 ai-eval-scope / Jenkins 发布流水线 / PyPI 准备清单）
- 编码规范索引：[`docs/standard/README.md`](docs/standard/README.md)
- 贡献指南（提交 / 分支 / PR）：[`CONTRIBUTING.md`](CONTRIBUTING.md)

## 通用准则

- **先读后改**：改动前阅读相关代码，优先复用现有工具（`ConfigLoader`、`Workspace`、`DatasetManager`），不臆造 API。
- **KISS / YAGNI / DRY**：文件保持在 300 行以内；不引入未使用的依赖。
- **测试先行**：新功能配单元测试；网络/IO 必须 mock（禁止联网测试）；用 `tmp_path` 隔离文件系统。
- **提交纪律**：提交前 `make check`；commit 遵循 Conventional Commits（见 [`CONTRIBUTING.md`](CONTRIBUTING.md)）。
- **安全红线**：密钥 / 凭证 / `.env` 严禁入库（已被 `.gitignore` 拦截，勿 `git add -f`）。
- **文档同步**：行为变更须同步对应 `CLAUDE.md` 或 `docs/`。

## 子项目专项规则

进入对应目录时自动加载该目录的 `CLAUDE.md`：

- [`evaluator/CLAUDE.md`](evaluator/CLAUDE.md) — Python 评估器开发规范（ruff / mypy / pytest / 异常与枚举约定）
- [`web/CLAUDE.md`](web/CLAUDE.md) — Web 可观测平台开发规范（TypeScript / eslint / prettier / vitest）

## 快速命令

```bash
make install      # 安装评估器依赖
make dev          # 安装开发依赖（含 ruff / pytest）
make hooks        # 安装 git hooks（pre-commit + commit-msg）
make check        # 一键质量门禁（ruff + pytest tests/unit——快门禁，仅单测目录）
make test         # 全量测试（pytest tests/，与 CI 同口径；合入/发布前必跑）
make docker-up    # 启动本地全栈（需先 cp .env.example .env）
```
