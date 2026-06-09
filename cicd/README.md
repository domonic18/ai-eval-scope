# CI/CD 流水线说明

## 概览

项目使用 Jenkins CI/CD 流水线，**单体仓库单流水线**模式：

```
腾讯工蜂 PR Webhook (develop/master)
        │
        ▼
┌──────────────────────────┐
│  Jenkinsfile.eval        │  Eval Pipeline
│  ├── 环境准备             │
│  ├── 代码静态检查 (ruff)  │  ← 非阻塞
│  ├── 类型检查 (mypy)      │  ← 非阻塞
│  └── 单元测试 (pytest)    │  ← 阻塞（失败中断）
└──────────────────────────┘
```

## 文件结构

```
cicd/
├── Jenkinsfile.eval.groovy       # 构建流水线（静态检查 + 单元测试）
├── README.md                     # 本文件
└── scripts/
    └── setup-python.sh           # Python3 + uv 幂等安装脚本
```

## 流水线详情

| 阶段 | 工具 | 阻塞策略 | 说明 |
|------|------|----------|------|
| 环境准备 | setup-python.sh | — | 安装 Python3 + uv |
| 代码静态检查 | ruff | 非阻塞 | 输出 JUnit XML 报告 |
| 类型检查 | mypy | 非阻塞 | 输出 JUnit XML 报告 |
| 单元测试 | pytest | **阻塞** | JUnit XML + HTML 覆盖率报告 |

**阻塞策略说明**：
- 非阻塞：检查发现问题将构建标记为 `UNSTABLE`，但不中断后续阶段
- 阻塞：测试失败则构建标记为 `FAILURE`，立即中断

## Jenkins Job 配置

1. 创建 **Multibranch Pipeline** Job
2. Script Path 设为 `cicd/Jenkinsfile.eval.groovy`
3. 配置 Webhook 触发（develop / master / release 分支）

### 凭据配置

| 凭据 ID | 类型 | 说明 |
|---------|------|------|
| `git-code-tencent-credentials` | Username with password | 腾讯工蜂 Git 凭据 |

## 本地验证

提交前可在本地模拟流水线阶段：

```bash
# 1. 静态检查（对应 Stage 2）
uv run ruff check agent_eval/ tests/

# 2. 类型检查（对应 Stage 2）
uv run mypy agent_eval/ --ignore-missing-imports

# 3. 单元测试（对应 Stage 3）
uv run pytest tests/ -v --tb=short --cov=agent_eval --cov-report=term-missing
```
