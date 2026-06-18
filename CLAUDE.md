# CLAUDE.md — 项目开发指南

## 项目概览

Agent 能力评估系统（agent-eval-system），基于 Agent-Driven 架构的评测框架。以课件生成为切入点，支持代码生成、RAG、对话等多类 Agent 评估。

- **当前阶段**：Sprint 1 已完成（项目骨架与数据模型），进入 Sprint 2（评估引擎 Rule-based）
- **Python 版本**：3.11+
- **包管理**：使用 `uv` 进行虚拟环境和依赖管理

## 技术栈

| 用途 | 工具 |
|------|------|
| CLI | typer |
| 数据模型 | pydantic v2 |
| 配置 | YAML + JSON Schema 校验 |
| 模板 | jinja2 |
| 日志 | structlog |
| 测试 | pytest + pytest-cov |
| 包管理 | uv |

## 开发命令

评估器代码在 `evaluator/` 子目录（自包含，对称于 `web/` 可观测平台）。

```bash
# 安装（使用 uv）
cd evaluator && uv sync --extra dev

# 运行测试
cd evaluator && uv run pytest tests/ -v

# 测试覆盖率
cd evaluator && uv run pytest tests/ -v --cov=agent_eval --cov-report=term-missing

# CLI
cd evaluator && uv run agent-eval --help

# 代码格式化
cd evaluator && uv run ruff format agent_eval/ tests/
cd evaluator && uv run ruff check --fix agent_eval/ tests/

# 或用 Makefile（自动 cd evaluator）
make install  # = cd evaluator && uv sync --extra dev
make test     # = cd evaluator && uv run pytest tests/ -v
```

## 项目结构

```
agent-eval-system/
├── evaluator/               # 评估器（Python，自包含，pip-installable）
│   ├── agent_eval/          # Python 包（import 不变：from agent_eval import ...）
│   │   ├── core/            # 枚举、异常、日志
│   │   ├── agent/           # Agent 模块（Sprint 8 骨架）
│   │   ├── orchestrator/    # 编排调度层
│   │   ├── evaluation/      # 评估引擎 + 评估器
│   │   ├── llm/             # LLM Provider 抽象层
│   │   ├── observability/   # ResultSink（评估结果推送平台，Sprint 7e）
│   │   ├── reporting/       # 报告生成
│   │   ├── storage/         # Workspace、数据包
│   │   ├── config/          # 配置加载（paths.py 用 PACKAGE_ROOT，pip-installable）
│   │   └── assets/          # 随包资源（prompts/schemas/rules/configs）
│   ├── tests/               # 测试
│   ├── cli.py  pyproject.toml  uv.lock
│   └── README.md
├── web/                     # 可观测平台（TypeScript，后端 + 前端）
├── docker/                  # Dockerfile
├── docs/ scripts/ cicd/
├── workspace/               # 运行产物（gitignored；WORKSPACE_DIR 可配）
├── docker-compose.yml  Dockerfile  .env  Makefile
└── CLAUDE.md  README.md
```

> **设计原则**：评估器 `evaluator/` 自包含、pip-installable。assets 在包内（`agent_eval/assets/`，随 wheel 发布）；workspace 按 `WORKSPACE_DIR` 环境变量或 `CWD/workspace` 定位（不硬编码项目路径）。

## 架构文档

所有架构设计文档在 `docs/arch/` 目录下：

| 文档 | 内容 |
|------|------|
| 01整体架构设计.md | 总览、目录结构、技术选型 |
| 02编排调度层设计.md | Orchestrator、PipelineEngine、EvaluationAgent |
| 03执行引擎设计.md | ExecutionAgent、SUT Tools (MCP)、AgentConfig |
| 04评估引擎设计.md | EvaluatorRegistry、17 项评估器、评分聚合 |
| 05LLM模块设计.md | Provider 抽象层、LLM Judge |
| 06数据包规范.md | ExecutionPackage、EvaluationResult |
| 07配置规范.md | pipeline.yaml、rule_set.yaml、eval_plan.md |
| 08Web可视化层设计.md | ⚠️ 已废弃：Sprint 7a 本地 workspace 查看 MVP（前端+遗留后端路由已移除），被 09 取代 |
| 09Web可观测平台架构设计.md | 多租户可观测平台（PostgreSQL+对象存储、Ingestion API、API Key/HMAC、ResultSink 对接），Sprint 7b–7g |

迭代开发计划：`docs/plan/01迭代开发计划.md`

## 编码约定

- **数据模型**：Pydantic v2 BaseModel 用于需要序列化的模型；dataclass 用于纯内存结构（如评估结果中间态）
- **异常体系**：所有自定义异常继承 `AgentEvalError`，按模块分子类
- **枚举**：定义在 `agent_eval/core/types.py`，统一使用 `str, Enum` 基类
- **配置加载**：通过 `ConfigLoader` 统一加载 YAML，支持 JSON Schema 校验
- **评估结果**：`ConstraintResult` / `StageResult` / `SampleResult` 使用 dataclass + `to_dict()`/`from_dict()` 序列化
- **执行包**：`ExecutionPackage` 使用 Pydantic BaseModel + `save()`/`load()` 文件读写
- **测试**：每个模块对应 `evaluator/tests/unit/test_*.py`，黄金样本在 `evaluator/tests/fixtures/golden/`
- **agent/ 目录下的文件**：当前为骨架（`raise NotImplementedError`），Sprint 8 逐步实现
