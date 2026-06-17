# Agent Eval 可观测平台后端

仿 Langfuse 的自托管多租户可观测平台后端（**TypeScript** + Express + Prisma + 对象存储）。
评估器（Python）经 API Key 摄取评估结果 → 落 PostgreSQL（结构化）+ 对象存储（大制品）→ 浏览器登录查看多项目趋势/详情。

> 设计基线：[09Web 可观测平台架构设计](../docs/arch/09Web可观测平台架构设计.md)、需求 [03Web 可观测平台重构需求](../docs/requirement/03Web可观测平台重构需求.md)。
> Sprint 7a 的本地 workspace 查看器 MVP（React + 读本地 JSON）已移除，前端待 Sprint 7f 按新架构重建。

## 目录结构

```
web/
├── backend/            TypeScript API（纯 JSON）
│   ├── src/            分层：config / middleware / infra / routes / services / repositories / types
│   ├── prisma/         schema.prisma + 迁移
│   ├── test/           vitest + supertest 集成测试
│   ├── server.ts       入口（薄代理）→ 编译为 dist/server.js
│   ├── tsconfig*.json  tsc 配置（build / 类型检查）
│   └── vitest.config.ts
└── frontend/           React + Vite + TS（看板/趋势/详情）
# 部署文件在仓库根：docker-compose.yml、docker/platform/Dockerfile、.dockerignore、.env(.example)
```

## 本地起栈（Docker Compose，推荐）

一键起 postgres + minio + 后端（迁移自动应用）：

```bash
make docker-up          # = docker compose up -d（根 docker-compose.yml，读根 .env）
curl http://localhost:3000/health
```

健康检查返回 `{ status: "ok", components: { db, object_storage } }`。
MinIO 控制台 http://localhost:9001（eval / evalpassword123）。

停止 / 日志：

```bash
make docker-down
make docker-logs
```

## 本地开发（无 Docker）

需本地或远端 PostgreSQL + 对象存储（MinIO）。环境变量见仓库根目录 [`../.env.example`](../.env.example)（`PLATFORM_*` 段）：

```bash
cd web/backend
npm install
export PLATFORM_DATABASE_URL="postgresql://eval:evalpassword@localhost:5432/agent_eval?schema=public"
npm run db:migrate:dev     # 首次建表 / 迭代 schema
npm run dev                # tsx watch server.ts（热更，PORT 默认 3000）
```

构建 / 类型检查：

```bash
npm run build              # tsc → dist/
npm run typecheck          # tsc --noEmit
npm start                  # node dist/server.js（生产）
```

## 测试

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
- `POST /api/public/ingest`（HMAC 鉴权）— 评估结果摄取（Sprint 7d）

> Query API（运行/样本/趋势/制品）与前端在 Sprint 7f 落地。

## 生产部署

腾讯云：Express → SCF/容器（`scf_bootstrap.js` 提供 serverless-http 入口，引用 `./dist/server`），PostgreSQL → 云数据库（前置 PgBouncer），对象存储 → COS（`PLATFORM_OBJECT_STORAGE=cos`）。详见架构文档 §十二。
