# 贡献指南

感谢你对 agent-eval-system 的关注！无论是提交 Bug、建议功能，还是贡献代码，都非常欢迎。

## 开发环境

```bash
git clone https://github.com/domonic18/ai-eval-scope.git
cd agent-eval-system
make dev          # 安装 Python 评估器开发依赖
make hooks        # 安装 git hooks（pre-commit + commit-msg）
```

> 前置：Python 3.11+、[uv](https://docs.astral.sh/uv/)、Node 18+（改 `web/` 时）

## 分支策略

- 从 `main` 切分支，命名 `<type>/<简述>`，如 `feat/dataset-download`、`fix/eval-crash`、`docs/arch-update`
- 一个分支聚焦一个改动，便于评审

## Commit 规范（Conventional Commits）

提交信息由 [commitizen](https://commitizen-tools.github.io/commitizen/) 在 `commit-msg` hook 自动校验。

格式：`<type>(<scope>): <subject>`

**type 列表**：

| type | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档 |
| `style` | 代码风格（格式化，不改逻辑） |
| `refactor` | 重构（非 feat/fix） |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `build` | 构建 / 依赖 |
| `ci` | CI 配置 |
| `chore` | 杂项 |
| `revert` | 回滚 |

示例：

```
feat(datasets): 新增 HF/ModelScope 数据集下载
fix(downloader): 修复 modelscope revision=None 下载失败
docs(arch): 更新数据集下载设计
```

> 也可用 `uvx commitizen commit` 交互式生成合规 commit message。

## 代码规范

- **Python**：见 [`evaluator/CLAUDE.md`](evaluator/CLAUDE.md)（ruff / mypy / pytest）
- **TypeScript**：见 [`web/CLAUDE.md`](web/CLAUDE.md)（eslint / prettier / vitest）
- 规范由 `pre-commit`（本地 hook）+ GitHub Actions（CI）强制，详见 [`.pre-commit-config.yaml`](.pre-commit-config.yaml)（commitizen 配置在 [`evaluator/pyproject.toml`](evaluator/pyproject.toml) 的 `[tool.commitizen]`）

提交前请确保 `make check`（ruff + pytest）通过。

## PR 流程

1. 确认分支已通过本地检查：`make check`（Python）+ `npm run lint`（web）
2. 推送分支并向 `main` 发起 Pull Request
3. 按 [PR 模板](.github/pull_request_template.md) 填写：动机、改动内容、破坏性变更、检查清单
4. 等待 CI（GitHub Actions）通过、Reviewer 评审
5. 合并后删除分支

## 报告问题

- Bug / 功能建议：通过 [Issue 模板](.github/ISSUE_TEMPLATE/) 提交
- 一般性讨论：GitHub Discussions

## 项目结构

详见 [`CLAUDE.md`](CLAUDE.md) 与 [`docs/standard/README.md`](docs/standard/README.md)。
