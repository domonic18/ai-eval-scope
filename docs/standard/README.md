# 开发规范索引

本目录集中维护项目的编码与协作规范，按需阅读。

| 主题 | 文档 |
|------|------|
| Python 编码规范 | [`../../evaluator/CLAUDE.md`](../../evaluator/CLAUDE.md) |
| TypeScript 编码规范 | [`../../web/CLAUDE.md`](../../web/CLAUDE.md) |
| 提交 / 分支 / PR 规范 | [`../../CONTRIBUTING.md`](../../CONTRIBUTING.md) |
| Git hooks（pre-commit + commitizen） | [`../../.pre-commit-config.yaml`](../../.pre-commit-config.yaml)、[`../../evaluator/pyproject.toml`](../../evaluator/pyproject.toml) `[tool.commitizen]` |
| 配置与数据管理规范 | [`../arch/06数据管理与配置规范.md`](../arch/06数据管理与配置规范.md) |
| 数据库迁移规范（Prisma） | [`../../web/backend/prisma/README.md`](../../web/backend/prisma/README.md) |
| 编辑器/换行规范 | [`../../.editorconfig`](../../.editorconfig)、[`../../.gitattributes`](../../.gitattributes) |

## 规范原则

- **指令式**：规范以「必须 / 禁止 / 优先」表述，配 ✅/❌ 示例，而非冗长描述。
- **渐进式披露**：根 `CLAUDE.md` 仅给索引指针，细节下沉到子项目 `CLAUDE.md` 与本文档。
- **工具强制**：规范由 `pre-commit`（本地 hook）+ GitHub Actions（CI）自动校验，不靠人工把关。

## 提交类型速查（Conventional Commits）

| type | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档 |
| `style` | 代码风格（格式化，不改逻辑） |
| `refactor` | 重构（非 feat/fix） |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `build` | 构建/依赖 |
| `ci` | CI 配置 |
| `chore` | 杂项 |
| `revert` | 回滚 |

格式：`<type>(<scope>): <subject>`，例：`feat(datasets): 新增 HF/ModelScope 数据集下载`
