# Web 可观测平台开发规范（TypeScript）

本目录是仿 Langfuse 的多租户可观测平台：`frontend/`（React + Vite）、`backend/`（Express + Prisma + 对象存储）。

## 环境

- Node 18+，npm 管理依赖
- backend：`cd web/backend && npm install && npm run dev`
- frontend：`cd web/frontend && npm install && npm run dev`

## 代码风格（强制）

- **ESLint + Prettier**：规则见各端 `eslint.config.js` / `.prettierrc`。
- **Prettier 统一风格**：无分号、双引号、行宽 100、缩进 2 空格。
- **TypeScript 严格模式**：禁用 `any`（必要时显式 `unknown` + 类型守卫）；函数参数与返回值标注。
- **命名**：组件 `PascalCase`；函数/变量 `camelCase`；自定义 hooks `use` 前缀；类型/接口 `PascalCase`。
- **模块系统**：`backend/` 为 CommonJS（`"type": "commonjs"`）；`frontend/` 为 ESM（`"type": "module"`）。
- backend 分层：`config` / `middleware` / `infra` / `routes` / `services` / `repositories`；新增功能遵循现有分层。

## 数据库与迁移

- backend 用 Prisma，schema 在 `web/backend/prisma/schema.prisma`
- **操作规范**：[`docs/standard/数据库迁移规范.md`](../docs/standard/数据库迁移规范.md) — Prisma 定义结构 + SQL 手动执行控制；含初始化/变更命令流程与禁止事项
- 日常变更：`prisma migrate dev --create-only`（生成 SQL 不执行）→ 手动跑 SQL → `prisma migrate resolve --applied`

## 测试

- backend 用 **vitest**（`web/backend/test/`）：`cd web/backend && npm test`
- API 测试用 supertest；mock 外部依赖（DB / 对象存储 / LLM）。

## 质量检查（提交前）

```bash
# backend
cd web/backend && npm run lint && npm run typecheck && npm test
# frontend
cd web/frontend && npm run lint && npm run build
```

详见根 [`CLAUDE.md`](../CLAUDE.md) 与 [规范索引](../docs/standard/README.md)。
