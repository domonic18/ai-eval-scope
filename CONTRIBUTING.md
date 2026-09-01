# 贡献指南

感谢你对 agent-eval-system 的关注！无论是提交 Bug、建议功能，还是贡献代码，都非常欢迎。

## 开源贡献流程（Fork → 开发 → PR）

外部贡献者通过 Fork 工作流提交代码。以下是完整步骤：

### 1. Fork 仓库

在 GitHub 上打开 [domonic18/ai-eval-scope](https://github.com/domonic18/ai-eval-scope)，点击右上角 **Fork** 按钮，将仓库复制到你的 GitHub 账号下。

### 2. Clone 你的 Fork + 配置上游

```bash
# 克隆你 Fork 的仓库（替换 <你的用户名>）
git clone https://github.com/<你的用户名>/ai-eval-scope.git
cd ai-eval-scope

# 添加上游仓库（用于同步最新代码）
git remote add upstream https://github.com/domonic18/ai-eval-scope.git
git fetch upstream
```

### 3. 安装开发环境

```bash
# Python 评估器（uv 管理）
cd evaluator
uv sync --group dev          # 基础 + 开发依赖
uv sync --extra llm          # LLM Judge 依赖（可选）
uv sync --extra vision       # 视觉评估依赖（可选）
cd ..

# 安装 git hooks（pre-commit + commit-msg）
make hooks

# Web 可观测平台（可选，改 web/ 时需要）
cd web/frontend && npm install && cd ../../web/backend && npm install
```

> 前置：Python 3.11+、[uv](https://docs.astral.sh/uv/)、Node 18+（改 `web/` 时）

### 4. 创建功能分支

```bash
# 始终基于最新的 develop 创建分支
git checkout -b feat/your-feature upstream/develop
```

分支命名：`<type>/<简述>`，如 `feat/rag-scenario`、`fix/upload-crash`、`docs/arch-update`。一个分支聚焦一个改动。

### 5. 开发与测试

```bash
# Python 代码检查（提交前必须通过）
make check                   # ruff + pytest
uv run ruff check agent_eval tests   # 单独 ruff
uv run pytest tests/ -q              # 单独 pytest

# Web 代码检查（改 web/ 时）
cd web/backend && npm run typecheck && npm run test:unit && npm run lint
cd web/frontend && npm run lint && npm run build
```

### 6. 提交代码

遵循 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```bash
git add <files>
git commit -m "feat(xxx): 简述你的改动"
```

**type 列表**：`feat`（新功能）/ `fix`（修复）/ `docs`（文档）/ `refactor`（重构）/ `test`（测试）/ `perf`（性能）/ `chore`（杂项）

### 7. 同步上游最新代码（如果上游有更新）

```bash
git fetch upstream
git rebase upstream/develop    # 或 merge
# 解决冲突（如有）后继续
```

### 8. 推送到你的 Fork + 创建 Pull Request

```bash
git push origin feat/your-feature
```

然后在 GitHub 上打开你的 Fork，点击 **Compare & pull request**：
- **Base repository**: `domonic18/ai-eval-scope`
- **Base branch**: `develop`
- **Head repository**: `<你的用户名>/ai-eval-scope`
- **Compare branch**: `feat/your-feature`

填写 PR 描述（动机、改动内容、测试方式），提交。

### 9. 等待 CI + 评审

- GitHub Actions CI 会自动运行（ruff / pytest / lint / build / typecheck）
- CI 全绿后等待 Reviewer 评审
- 根据 Review 意见修改后，push 到同一分支（PR 自动更新）
- 合并后你的贡献将出现在项目贡献者列表中

---

## 内部贡献（直接推送权限）

有仓库写权限的贡献者可以跳过 Fork，直接从 `develop` 切分支：

```bash
git clone https://github.com/domonic18/ai-eval-scope.git
cd ai-eval-scope
git checkout -b feat/your-feature origin/develop
# 开发 → make check → push → 向 develop 发起 Pull Request
```

> `develop` 是受保护分支，禁止直接 push，必须走 PR。

---

## 版本发布（维护者，PyPI）

评估器以 **`ai-eval-scope`** 包名发布到 PyPI（import 名 `agent_eval`、CLI 名 `agent-eval` 不变），经 Jenkins 发布流水线 `sasan-evalscope-pypi` 走完质量门禁 → 构建 → 校验 → 发布：

```bash
# ① 起版：版本单源由 commitizen 维护（一次改 pyproject + __init__.py + CHANGELOG + 打 tag）
cd evaluator
uv run cz bump --dry-run --increment PATCH --yes   # 先核对将变成什么版本
uv run cz bump --increment PATCH --yes             # 实跑
git push origin <发布分支> --tags
```

```text
② Jenkins sasan-evalscope-pypi → Build with Parameters
   TAG=vX.Y.Z + TEST_PYPI=true   → 演练发布到 test.pypi.org（首发前必演练）
   验收：uv run --isolated --no-project \
           --index-url https://test.pypi.org/simple/ \
           --extra-index-url https://pypi.org/simple/ \
           --with ai-eval-scope agent-eval --version
   TAG=vX.Y.Z + TEST_PYPI=false  → 正式发布 pypi.org
```

**纪律**：PyPI 同版本号**不可重传**，发布失败修复后必须 bump 新版本；tag 必须等于包 `__version__`（流水线有硬断言）；凭证走 Jenkins 双 credential（`test-pypi-upload-token` / `pypi-upload-token`，按 `TEST_PYPI` 自动选择）。

详见 [`cicd/README.md`](./cicd/README.md)（流水线阶段/凭证/本地验证序列与发布纪律）。

---

## 新增评估场景（最快上手）

系统是**场景无关 + 数据驱动**的——新增场景是纯配置（写场景包 + 导入），无需改代码。详见 [场景扩展指南](./docs/arch/14场景扩展指南.md)，以内置的 code（代码生成）场景为完整范例。

## 开发环境

已在「开源贡献流程」第 3 步中说明。

## Commit 规范（Conventional Commits）

提交信息由 [commitizen](https://commitizen-tools.github.io/commitizen/) 在 `commit-msg` hook 自动校验。格式：`<type>(<scope>): <subject>`

> 也可用 `uvx commitizen commit` 交互式生成合规 commit message。

## 代码规范

- **Python**：见 [`evaluator/CLAUDE.md`](evaluator/CLAUDE.md)（ruff / mypy / pytest）
- **TypeScript**：见 [`web/CLAUDE.md`](web/CLAUDE.md)（eslint / prettier / vitest）

## 报告问题

- Bug / 功能建议：通过 [Issue 模板](.github/ISSUE_TEMPLATE/) 提交
- 一般性讨论：GitHub Discussions

## 项目结构

详见 [`CLAUDE.md`](CLAUDE.md) 与 [`docs/standard/README.md`](docs/standard/README.md)。

## 文档索引

| 文档 | 内容 |
|------|------|
| [CLAUDE.md](./CLAUDE.md) | 项目总览 + 通用准则 + 快速命令 |
| [docs/arch/01整体架构设计](./docs/arch/01整体架构设计.md) | 系统架构总览 |
| [docs/arch/04评估引擎设计](./docs/arch/04评估引擎设计.md) | 评估引擎（场景抽象 + 指标 + 聚合） |
| [docs/arch/09Web可观测平台架构设计](./docs/arch/09Web可观测平台架构设计.md) | Web 平台架构 |
| [docs/arch/12第三方系统对接方案](./docs/arch/12第三方系统对接方案.md) | 第三方接入（HTTP + MCP + Webhook） |
| [docs/arch/14场景扩展指南](./docs/arch/14场景扩展指南.md) | 如何新增一个评估场景（含 entry_points 可插拔评估器） |
