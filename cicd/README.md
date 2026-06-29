# CI/CD 流水线说明

## 概览

项目使用 Jenkins CI/CD，**单仓库多流水线**模式 —— 每个交付物一条独立 Jenkinsfile：

```
腾讯工蜂 PR Webhook (develop / master)
        │
        ├───► ┌──────────────────────────┐
        │     │  Jenkinsfile.eval        │  Eval Pipeline（Python 评估器）
        │     │  ├── 环境准备             │
        │     │  ├── 代码静态检查 (ruff)  │  ← 非阻塞
        │     │  ├── 类型检查 (mypy)      │  ← 非阻塞
        │     │  └── 单元测试 (pytest)    │  ← 阻塞（失败中断）
        │     └──────────────────────────┘
        │
        └───► ┌──────────────────────────┐
              │  Jenkinsfile.web         │  Web Pipeline（前端 + 后端 → 镜像）
              │  ├── 环境准备             │
              │  ├── 前端静态检查 (eslint) │  ← 非阻塞
              │  ├── 前端构建 (vite build) │  ← 阻塞
              │  ├── 后端静态检查 (eslint) │  ← 非阻塞
              │  ├── 后端类型检查 (tsc)    │  ← 阻塞
              │  ├── 后端单测 (vitest)     │  ← 阻塞（仅纯单测，排除集成）
              │  └── 镜像构建推送 (→ CCR)  │  ← 前置失败则跳过
              └──────────────────────────┘
```

## 文件结构

```
cicd/
├── Jenkinsfile.eval.groovy       # Eval 流水线（静态检查 + 单元测试）
├── Jenkinsfile.web.groovy        # Web 流水线（静态检查 + 单测 + 镜像构建推送）
├── README.md                     # 本文件
└── scripts/
    ├── setup-python.sh           # Python3 + uv 幂等安装（eval 用）
    ├── setup-nodejs.sh           # Node.js 20.11.0 幂等安装（web 用）
    └── docker-build.groovy       # Docker 镜像构建 + 推送腾讯云 CCR 共享库（web 用）
```

## 阻塞策略

- **非阻塞**：检查发现问题将构建标记为 `UNSTABLE`，但不中断后续阶段（lint 类）。
- **阻塞**：失败则构建标记为 `FAILURE`，立即中断；Docker 阶段 `when currentResult != FAILURE` 会自动跳过。

## Eval 流水线详情

| 阶段 | 工具 | 阻塞策略 | 说明 |
|------|------|----------|------|
| 环境准备 | setup-python.sh | — | 安装 Python3 + uv |
| 代码静态检查 | ruff | 非阻塞 | 输出 JUnit XML 报告 |
| 类型检查 | mypy | 非阻塞 | 输出 JUnit XML 报告 |
| 单元测试 | pytest | **阻塞** | JUnit XML + HTML 覆盖率报告 |

## Web 流水线详情

| 阶段 | 工具 | 阻塞策略 | 说明 |
|------|------|----------|------|
| 环境准备 | setup-nodejs.sh | — | 安装 Node.js 20.11.0 + 腾讯云 npm 镜像 |
| 前端静态检查 | eslint (`web/frontend`) | 非阻塞 | `npm run lint` |
| 前端构建验证 | tsc -b + vite build | **阻塞** | `npm run build`（含类型检查） |
| 后端静态检查 | eslint (`web/backend`) | 非阻塞 | `npm run lint` |
| 后端类型检查 | tsc --noEmit | **阻塞** | `npm run typecheck` |
| 后端单元测试 | vitest | **阻塞** | `npm run test:unit`（排除 `*.integration.test.ts`，输出 JUnit XML） |
| 镜像构建推送 | docker | **阻塞** | `docker/web/Dockerfile`，context=仓库根 |

**后端单测策略**：`web/backend` 的集成测试（依赖真实 postgres+minio）以 `*.integration.test.ts` 命名，CI 不执行；仅跑纯单测（`test:unit`）并阻塞。集成测试本地用 `npm run test:integration`（需先 `make docker-up`）。

### 镜像与腾讯云 CCR 约定

| 项 | 值 |
|----|----|
| Registry | `ccr.ccs.tencentyun.com`（腾讯云容器服务个人版 CCR） |
| Namespace | `sasan` |
| 镜像名 | `agent-eval-web` → 全名 `ccr.ccs.tencentyun.com/sasan/agent-eval-web` |
| Tag | `${branch}-${shortHash}-${BUILD_NUMBER}`（如 `main-a1b2c3d-42`） |
| `:latest` | 仅 `main` 分支额外推送 |
| 推送重试 | 3 次，失败间隔 5s（见 `scripts/docker-build.groovy`） |

## Jenkins Job 配置

每个 Jenkinsfile 对应一个 **Multibranch Pipeline** Job：

| Job | Script Path | 触发分支 |
|-----|-------------|----------|
| Eval | `cicd/Jenkinsfile.eval.groovy` | develop / master / release |
| Web | `cicd/Jenkinsfile.web.groovy` | develop / master（main 推 `:latest`） |

配置 Webhook 触发（腾讯工蜂 PR/push）。

### 凭据配置

| 凭据 ID | 类型 | 说明 |
|---------|------|------|
| `git-code-tencent-credentials` | Username with password | 腾讯工蜂 Git 凭据（拉代码） |
| `tencent-registry-credentials` | Username with password | 腾讯云 CCR 账号（`docker.withRegistry` 推送镜像，被 `scripts/docker-build.groovy` 使用） |

> `tencent-registry-credentials` 需在 Jenkins 凭据库新建（用户名/密码 = 腾讯云 CCR 登录账号）；CCR 控制台需确保 `sasan/agent-eval-web` 仓库存在或开启自动创建。

## 本地验证

提交前可在本地模拟流水线阶段：

```bash
# ── Eval（对应 Jenkinsfile.eval）──
cd evaluator
uv run ruff check agent_eval/ tests/
uv run mypy agent_eval/ --ignore-missing-imports
uv run pytest tests/ -v --tb=short --cov=agent_eval --cov-report=term-missing

# ── Web 后端（对应 Jenkinsfile.web stage 4-6）──
cd web/backend
npm run lint                    # 非阻塞静态检查
npm run typecheck               # 阻塞类型检查
npm run test:unit               # 阻塞纯单测（排除集成测试）

# ── Web 前端（对应 stage 2-3）──
cd web/frontend
npm run lint
npm run build                   # tsc -b && vite build

# ── 镜像构建（对应 stage 7，仓库根执行）──
docker build -f docker/web/Dockerfile -t agent-eval-web:local .
```
