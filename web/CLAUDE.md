# Web 可观测平台开发规范（TypeScript）

仿 Langfuse 的多租户可观测平台：`frontend/`（React + Vite）、`backend/`（Express + Prisma + 对象存储）。评估器（Python）经 API Key 摄取评估结果 → 落 PostgreSQL（结构化）+ 对象存储（大制品）→ 浏览器登录查看多项目趋势/详情。

> 设计基线：[09 Web 可观测平台架构设计](../docs/arch/09Web可观测平台架构设计.md)、需求 [03 Web 可观测平台重构需求](../docs/requirement/03Web可观测平台重构需求.md)。

## 目录结构

```
web/
├── backend/            TypeScript API（纯 JSON）
│   ├── src/            分层：config / middleware / infra / routes / services / repositories / schemas / types / utils
│   │   └── routes/public/   公开摄取端点（HMAC 鉴权）
│   ├── prisma/         schema.prisma + 迁移（规范见 prisma/README.md）
│   ├── test/           vitest + supertest 集成测试
│   ├── server.ts       入口（薄代理）→ 编译为 dist/server.js
│   ├── tsconfig*.json  tsc 配置（build / 类型检查）
│   └── vitest.config.ts
└── frontend/           React + Vite + TS（看板 / 趋势 / 详情）
    └── src/            api / components / pages / store / lib / styles
# 部署文件在仓库根：docker-compose.yml、docker/web/Dockerfile、.dockerignore、.env(.example)
```

## 本地起栈（Docker Compose，推荐）

起 postgres + minio + 后端（postgres 为空库；建库改为起栈后手动 `make db-init`，单一来源 = prisma migrations，已废弃 schema.sql）：

```bash
make docker-up          # = docker compose up -d（根 docker-compose.yml，读根 .env）
make db-init            # 手动建库：按序应用所有 prisma migration + resolve + generate（首次必跑）
curl http://localhost:9000/health
```

健康检查返回 `{ status: "ok", components: { db, object_storage } }`。
MinIO 控制台 http://localhost:9001（eval / evalpassword123）。

停止 / 日志：

```bash
make docker-down
make docker-logs
```

## 本地开发（无 Docker）

需本地或远端 PostgreSQL + 对象存储（MinIO）。环境变量见仓库根 [`../.env.example`](../.env.example)（`PLATFORM_*` 段）：

```bash
cd web/backend
npm install
export PLATFORM_DATABASE_URL="postgresql://eval:evalpassword@localhost:5432/agent_eval?schema=public"
npm run db:migrate:dev     # 首次建表 / 迭代 schema
npm run dev                # tsx watch server.ts（热更，PORT 默认 9000）
```

前端：

```bash
cd web/frontend
npm install
npm run dev
```

构建 / 类型检查：

```bash
npm run build              # tsc → dist/
npm run typecheck          # tsc --noEmit
npm start                  # node dist/server.js（生产）
```

## 代码风格（强制）

- Node 18+，npm 管理依赖。
- **ESLint + Prettier**：规则见各端 `eslint.config.js` / `.prettierrc`。
- **Prettier 统一风格**：无分号、双引号、行宽 100、缩进 2 空格。
- **TypeScript 严格模式**：禁用 `any`（必要时显式 `unknown` + 类型守卫）；函数参数与返回值标注。
- **命名**：组件 `PascalCase`；函数/变量 `camelCase`；自定义 hooks `use` 前缀；类型/接口 `PascalCase`。
- **模块系统**：`backend/` 为 CommonJS（`"type": "commonjs"`）；`frontend/` 为 ESM（`"type": "module"`）。
- backend 分层：`config` / `middleware` / `infra` / `routes` / `services` / `repositories`；新增功能遵循现有分层。

## 数据库与迁移

- backend 用 Prisma，schema 在 `web/backend/prisma/schema.prisma`。
- **操作规范**：[`backend/prisma/README.md`](backend/prisma/README.md) — Prisma 定义结构 + SQL 手动执行控制；含初始化/变更命令流程与禁止事项。
- 日常变更：`prisma migrate dev --create-only`（生成 SQL 不执行）→ 手动跑 SQL → `prisma migrate resolve --applied`。

## 测试

- backend 用 **vitest**（`web/backend/test/`）：API 测试用 supertest；mock 外部依赖（DB / 对象存储 / LLM）。
- 前端以构建为校验（`npm run build`）。

```bash
make web-test           # = cd web/backend && npm test（vitest run）
make web-typecheck      # = cd web/backend && npm run typecheck
```

## API 概览

- `GET /health`、`GET /api/health` — 健康检查（db + object_storage + schema_version）
- `POST /api/v1/auth/{register,login,refresh}`、`GET /api/v1/auth/me` — 账号与 JWT
- `GET|POST /api/v1/orgs/:org/members`、`DELETE /api/v1/orgs/:org/members/:userId` — 组织成员（owner）
- `GET|POST /api/v1/orgs/:org/projects` — 组织下项目
- `GET|PATCH /api/v1/projects/:id`、`POST /api/v1/projects/:id/{archive,unarchive}` — 项目管理
- `GET|POST /api/v1/projects/:id/keys`、`POST /api/v1/projects/:id/keys/:keyId/revoke` — API Key 管理
- `POST /api/public/ingest`（HMAC 鉴权）— 评估结果摄取

> Query API（运行 / 样本 / 趋势 / 制品）见架构文档 §九。

## 生产部署

腾讯云：Express 容器化部署（`node dist/server.js`，默认监听 `PORT=9000`，镜像见 `docker/web/Dockerfile`），PostgreSQL → 云数据库（前置 PgBouncer），对象存储 → COS（`PLATFORM_OBJECT_STORAGE=cos`）。详见架构文档 §十二。

## 质量检查（提交前）

```bash
# backend
cd web/backend && npm run lint && npm run typecheck && npm test
# frontend
cd web/frontend && npm run lint && npm run build
```

详见根 [`CLAUDE.md`](../CLAUDE.md) 与 [规范索引](../docs/standard/README.md)。
