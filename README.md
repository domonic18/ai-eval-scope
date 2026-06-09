# agent-eval

Agent 能力评估系统 — 基于 Agent-Driven 架构的评测框架。

以课件生成为切入点，架构上支持代码生成、RAG、对话等多类 Agent 评估。采用**评估先行、执行后补**的策略，当前阶段已完成评估链路骨架。

## 快速开始

### 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)（Python 包管理工具）

### 安装

```bash
# 克隆项目
git clone <repo-url> && cd agent-eval-system

# 使用 uv 创建虚拟环境并安装依赖
uv sync

# 安装开发依赖
uv sync --extra dev

# 安装 LLM 相关依赖（Sprint 3+ 需要）
uv sync --extra llm
```

### 常用命令

```bash
# CLI 使用
uv run agent-eval --help
uv run agent-eval version

# 运行测试
uv run pytest tests/ -v

# 测试覆盖率报告
uv run pytest tests/ -v --cov=agent_eval --cov-report=term-missing

# 代码格式化与检查
uv run ruff format agent_eval/ tests/
uv run ruff check --fix agent_eval/ tests/

# 也可以通过 Makefile（需先激活虚拟环境）
source .venv/bin/activate
make test        # 运行测试
make test-cov    # 覆盖率报告
make lint        # 代码检查
make format      # 格式化
```

## CLI 命令

```bash
# 评估（当前主要使用模式）
uv run agent-eval eval --package-dir <路径> --rule-set <路径> [--eval-mode pipeline]

# 执行被测 Agent（Sprint 8 实现）
uv run agent-eval run --task-set <路径> --sut-config <路径>

# 完整流水线（Sprint 9 实现）
uv run agent-eval pipeline --task-set <路径> --sut-config <路径> --rule-set <路径>

# Web Portal（Sprint 7a 实现）
uv run agent-eval serve --port 3000
```

## Python SDK

```python
from sdk import ConfigLoader, PackageBuilder, Workspace, Task

# 加载配置
rule_set = ConfigLoader.load_rule_set("assets/rules/courseware/rule_set.yaml")
task_set = ConfigLoader.load_task_set("assets/tasks/courseware/task_set.yaml")

# 打包执行产出物
builder = PackageBuilder()
task = Task(id="t001", input={"subject": "math", "grade": 7, "topic": "方程"})
builder.build_inline(
    task=task,
    output_files=["output/index.md"],
    package_dir=Path("workspace/runs/run_001/packages/t001"),
)
```

## 项目结构

```
agent-eval-system/
├── agent_eval/              # 源码包
│   ├── core/                #   枚举、异常、日志
│   ├── agent/               #   Agent 模块（ExecutionAgent / EvaluationAgent / SUT Tools）
│   ├── orchestrator/        #   编排调度层
│   ├── execution/           #   执行侧数据模型（Task / TaskSet / AgentConfig）
│   ├── evaluation/          #   评估引擎 + 评估侧数据模型
│   │   └── evaluators/      #     评估器实现 + plugins/
│   ├── rules/               #   规则管理（RuleSet / Rule）
│   ├── llm/                 #   LLM Provider 抽象层
│   ├── reporting/           #   报告生成
│   ├── storage/             #   数据包 / Workspace / Collector / Builder
│   └── config/              #   配置加载（YAML + JSON Schema）
├── assets/                  # 配置资产
│   ├── schemas/             #   JSON Schema
│   ├── rules/               #   规则集
│   ├── tasks/               #   任务集
│   ├── prompts/             #   Prompt 模板
│   ├── plans/               #   Markdown 评测计划
│   └── knowledge/           #   知识库
├── workspace/               # 运行时工作空间（gitignored）
├── tests/                   # 测试体系
│   ├── unit/                #   单元测试
│   ├── integration/         #   集成测试
│   ├── evaluators/          #   评估器专项测试
│   ├── e2e/                 #   端到端测试
│   ├── golden/              #   黄金样本回归
│   └── fixtures/            #   样本数据
├── docs/                    # 文档
│   ├── arch/                #   架构设计文档
│   ├── plan/                #   迭代开发计划
│   └── reference/           #   参考资料
├── cli.py                   # CLI 入口
├── sdk.py                   # SDK 入口
├── pyproject.toml           # 项目配置
└── Makefile                 # 常用命令
```

## 文档

| 文档 | 说明 |
|------|------|
| [CLAUDE.md](./CLAUDE.md) | 开发指南与编码约定 |
| [docs/arch/](./docs/arch/) | 架构设计文档（8 篇） |
| [docs/plan/01迭代开发计划.md](./docs/plan/01迭代开发计划.md) | 9 个 Sprint 迭代计划 |

## 当前进度

- [x] **Sprint 1**：项目骨架与数据模型
- [ ] **Sprint 2**：评估引擎（Rule-based）
- [ ] **Sprint 3**：LLM 模块
- [ ] **Sprint 4**：评估引擎（LLM Judge）
- [ ] **Sprint 5**：编排调度与报告

## License

MIT
