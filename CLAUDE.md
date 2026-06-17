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

```bash
# 安装（使用 uv）
uv sync --extra dev

# 运行测试
uv run pytest tests/ -v

# 测试覆盖率
uv run pytest tests/ -v --cov=agent_eval --cov-report=term-missing

# CLI
uv run agent-eval --help

# 代码格式化
uv run ruff format agent_eval/ tests/
uv run ruff check --fix agent_eval/ tests/
```

## 项目结构

```
agent_eval/
├── core/            # 枚举、异常、日志
├── agent/           # Agent 模块（ExecutionAgent、EvaluationAgent、SUT Tools）
│   ├── execution_agent.py    # Sprint 8 实现
│   ├── evaluation_agent.py   # 后续迭代
│   ├── sut_tools.py          # Sprint 8 实现
│   ├── eval_tools.py         # 后续迭代
│   ├── plan_parser.py        # 后续迭代
│   └── hooks.py              # Sprint 8 实现
├── orchestrator/    # 编排调度层
├── execution/       # 执行侧数据模型（Task, TaskSet, AgentConfig）
├── evaluation/      # 评估引擎 + 评估侧数据模型
│   └── evaluators/  # 评估器实现 + plugins/
├── rules/           # 规则管理（RuleSet, Rule）
├── llm/             # LLM Provider 抽象层
├── reporting/       # 报告生成
├── storage/         # 数据包、Workspace、Collector、Builder
└── config/          # 配置加载（YAML + JSON Schema）
```

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
- **测试**：每个模块对应 `tests/unit/test_*.py`，黄金样本在 `tests/fixtures/golden/`
- **agent/ 目录下的文件**：当前为骨架（`raise NotImplementedError`），Sprint 8 逐步实现
