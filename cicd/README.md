# CI/CD 流水线说明

## 概览

项目使用 Jenkins CI/CD，**单仓库多流水线**模式 —— 每个交付物一条独立 Jenkinsfile：

```
腾讯工蜂 PR Webhook (develop / main)
        │
        ├───► ┌──────────────────────────┐
        │     │  Jenkinsfile.eval        │  Eval Pipeline（Python 评估器）
        │     │  ├── 环境准备             │
        │     │  ├── 代码静态检查 (ruff)  │  ← 非阻塞
        │     │  ├── 类型检查 (mypy)      │  ← 非阻塞
        │     │  └── 单元测试 (pytest)    │  ← 阻塞（失败中断）
        │     └──────────────────────────┘
        │
        ├───► ┌──────────────────────────┐
        │     │  Jenkinsfile.executor    │  Executor Pipeline（Python → 镜像）
        │     │  ├── 环境准备             │
        │     │  ├── 静态检查 (ruff+mypy) │  ← 非阻塞
        │     │  ├── 单元测试 (pytest)    │  ← 阻塞（仅 tests/unit）
        │     │  └── 镜像构建推送 (→ CCR)  │  ← 前置失败则跳过
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

推送 tag (v*)  ──► ┌──────────────────────────┐
                   │  Jenkinsfile.pypi        │  PyPI 发布流水线（ai-eval-scope 包）
                   │  ├── 环境准备             │
                   │  ├── 质量门禁 (ruff+mypy+pytest)
                   │  ├── 构建 (uv build)      │  ← sdist + wheel
                   │  ├── 校验 (版本断言+冒烟) │  ← 阻塞（tag==__version__，双产物隔离装包）
                   │  └── 发布 (uv publish)    │  ← 仅 tag 触发；TEST_PYPI 可演练
                   └──────────────────────────┘
```

## 文件结构

```
cicd/
├── Jenkinsfile.eval.groovy       # Eval 流水线（静态检查 + 单元测试）
├── Jenkinsfile.executor.groovy   # Executor 流水线（静态检查 + 单测 + 镜像构建推送）
├── Jenkinsfile.web.groovy        # Web 流水线（静态检查 + 单测 + 镜像构建推送）
├── Jenkinsfile.pypi.groovy       # PyPI 发布流水线（质量门禁 + 构建 + 校验 + 发布）
├── README.md                     # 本文件
└── scripts/
    ├── setup-python.sh           # Python3 + uv 幂等安装（eval / executor 用）
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

## Executor 流水线详情

| 阶段 | 工具 | 阻塞策略 | 说明 |
|------|------|----------|------|
| 环境准备 | setup-python.sh | — | 安装 Python3 + uv（与 eval 共用） |
| 代码静态检查 | ruff + mypy (`executor/`) | 非阻塞 | `ruff check eval_executor tests` + `mypy eval_executor --ignore-missing-imports`，JUnit XML |
| 单元测试 | pytest (`executor/`) | **阻塞** | `pytest tests/unit`（纯单测，JUnit XML） |
| 镜像构建推送 | docker | **阻塞** | `docker/executor/Dockerfile`，context=仓库根 |

**Executor 单测策略**：CI 仅跑 `executor/tests/unit`（阻塞）；集成测试（marker `integration`，依赖真实 PG）不在 CI 执行。单测 conftest 已 mock PG/langfuse/worker loop，离线可跑。Python 阶段在 `dir("executor")` 内执行（pyproject 以 path 依赖复用 `../evaluator`）。

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

## PyPI 发布流水线详情（`Jenkinsfile.pypi.groovy`）

评估器 `evaluator/` 以 **ai-eval-scope** 包名发布到 PyPI。与 eval 流水线的分工：**eval 守每次提交的质量，本流水线守 tag 制品**——前者 PR/push 触发，后者仅 tag（`v*`）触发发布。

| 阶段 | 工具 | 阻塞策略 | 说明 |
|------|------|----------|------|
| 环境准备 | setup-python.sh | — | 安装 Python3 + uv；带 tag 时先 `git fetch + checkout` 切到 tag 指向的提交（构建物 == tag 内容） |
| 质量门禁 | ruff + mypy + pytest | ruff/mypy 非阻塞；pytest **阻塞** | 与 eval 流水线同款命令（`dir('evaluator')` 内执行） |
| 构建 | uv build | **阻塞** | 产出 `dist/` 下 sdist + wheel 双产物 |
| 校验 | 版本断言 + 隔离冒烟 | **阻塞** | tag == 包 `__version__`（防错发兜底）；wheel 与 sdist 各自 `uv run --isolated --no-project --refresh --with dist/*` 装包执行 `agent-eval --version` |
| 发布 | uv publish | **阻塞** | 仅 `RELEASE_TAG` 匹配 `v*` 时执行；`TEST_PYPI=true` 走 TestPyPI 凭证 + `--publish-url https://test.pypi.org/legacy/`，`false` 走 PyPI 凭证直传——**双凭证隔离**，杜绝拿错 token |

发布纪律：

- **无 tag 触发（手动空跑）= 构建演练**：质量门禁 + 构建 + 校验全走，发布段跳过。
- **PyPI 同版本号不可重传**：发布失败修复合后必须 `cz bump` 升版本（不可覆盖上传；重大问题只能 yank）。因此正式发布前先用 `TEST_PYPI=true` 演练一次全流程。
- **版本单源**：`cz bump` 同时更新 pyproject `version` 与 `agent_eval/__init__.py::__version__` 并打 annotated tag（`[tool.commitizen] version_provider = "pep621"` + `version_files`）；发布段只认 tag，推送 tag 前先本地 `uv run cz bump --dry-run` 核对。

## 镜像与腾讯云 CCR 约定

Web 与 Executor 镜像共用同一套 CCR 约定（由 `scripts/docker-build.groovy` 统一实现）：

| 项 | 值 |
|----|----|
| Registry | `ccr.ccs.tencentyun.com`（腾讯云容器服务个人版 CCR） |
| Namespace | `sasan` |
| 镜像名 | `agent-eval-web` / `agent-eval-executor` → 全名 `ccr.ccs.tencentyun.com/sasan/<镜像名>` |
| Tag | `${branch}-${shortHash}-${BUILD_NUMBER}`（如 `main-a1b2c3d-42`） |
| `:latest` | 仅 `main` 分支额外推送（executor 流水线通常不推 latest，以明确 tag 为准） |
| 推送重试 | 3 次，失败间隔 5s（见 `scripts/docker-build.groovy`） |

## Jenkins Job 配置

每个 Jenkinsfile 对应一个 **Multibranch Pipeline** Job：

| Job | Script Path | 触发分支 |
|-----|-------------|----------|
| Eval | `cicd/Jenkinsfile.eval.groovy` | develop / master / release |
| Executor | `cicd/Jenkinsfile.executor.groovy` | develop / main |
| Web | `cicd/Jenkinsfile.web.groovy` | develop / master（main 推 `:latest`） |
| PyPI 发布 | `cicd/Jenkinsfile.pypi.groovy` | tag `v*`（普通 Pipeline Job，非 Multibranch；手动带参 `TAG` 亦可） |

配置 Webhook 触发（腾讯工蜂 PR/push）；PyPI 发布 Job 额外配 tag 推送触发（或手动带 `TAG` 参数）。

### 凭据配置

| 凭据 ID | 类型 | 说明 |
|---------|------|------|
| `git-code-tencent-credentials` | Username with password | 腾讯工蜂 Git 凭据（拉代码） |
| `tencent-registry-credentials` | Username with password | 腾讯云 CCR 账号（`docker.withRegistry` 推送镜像，被 `scripts/docker-build.groovy` 使用） |
| `pypi-upload-token` | Secret text | PyPI（pypi.org）**project-scoped** API token（`pypi-` 开头，只显示一次，即入即存）；`TEST_PYPI=false` 时注入 `UV_PUBLISH_TOKEN` 供 `uv publish` |
| `test-pypi-upload-token` | Secret text | TestPyPI（test.pypi.org）API token（与主站账号不通用，单独注册）；`TEST_PYPI=true` 演练时使用 |

> `tencent-registry-credentials` 需在 Jenkins 凭据库新建（用户名/密码 = 腾讯云 CCR 登录账号）；CCR 控制台需确保 `sasan/agent-eval-web`、`sasan/agent-eval-executor` 仓库存在或开启自动创建。

## 本地验证

提交前可在本地模拟流水线阶段：

```bash
# ── Eval（对应 Jenkinsfile.eval）──
cd evaluator
uv run ruff check agent_eval/ tests/
uv run mypy agent_eval/ --ignore-missing-imports
uv run pytest tests/ -v --tb=short --cov=agent_eval --cov-report=term-missing

# ── Executor（对应 Jenkinsfile.executor）──
cd executor
uv run ruff check eval_executor tests
uv run mypy eval_executor --ignore-missing-imports
uv run pytest tests/unit -q
cd ..

# ── Web 后端（对应 Jenkinsfile.web stage 4-6）──
cd web/backend
npm run lint                    # 非阻塞静态检查
npm run typecheck               # 阻塞类型检查
npm run test:unit               # 阻塞纯单测（排除集成测试）

# ── Web 前端（对应 stage 2-3）──
cd web/frontend
npm run lint
npm run build                   # tsc -b && vite build

# ── 镜像构建（仓库根执行）──
docker build -f docker/web/Dockerfile -t agent-eval-web:local .
docker build -f docker/executor/Dockerfile -t agent-eval-executor:local .

# ── PyPI 发布（对应 Jenkinsfile.pypi）──
cd evaluator
uv run cz bump --dry-run --increment PATCH --yes   # 核对版本将变更为多少
uv build                                            # dist/ 下 sdist + wheel
uv run --isolated --no-project --refresh --with dist/*.whl agent-eval --version    # wheel 冒烟
uv run --isolated --no-project --refresh --with dist/*.tar.gz agent-eval --version # sdist 冒烟
# （--refresh 防 uv 缓存同版本旧包假通过；重演练同版本时务必带上）
# 发布（演练先加 --publish-url https://test.pypi.org/legacy/，token 走 UV_PUBLISH_TOKEN）
uv publish
```
