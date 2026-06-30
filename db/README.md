# 数据库建库/迁移治理（全库唯一来源）

本目录是**整个仓库数据库 schema 的唯一来源**：web 平台（`public` schema，Prisma）与 eval-gateway（`gateway` schema，版本化 SQL）的建库/迁移都收敛到此，由**单一命令**统一应用。web 与 gateway 服务都**不在代码里建库**——启动只连库，建库/刷新走命令。

## 目录结构

```
db/
├── README.md                  # 本文件（治理规范）
├── apply.sh                   # 本地：统一应用 web + gateway 两 schema（make db-init）
├── apply-prod.sh              # 线上：增量应用 pending（make db-migrate-prod）
├── web/prisma/                # web = public schema（Prisma 引擎）
│   ├── schema.prisma          #   结构定义 + generator/datasource
│   └── migrations/            #   带时间戳的 migration.sql + migration_lock.toml
└── gateway/migrations/        # gateway = gateway schema（版本化 SQL）
    └── 0001_init_jobs.sql     #   CREATE SCHEMA gateway + jobs 表（幂等）
```

两个 schema 隔离于同一 PG 实例（共享 `PLATFORM_DATABASE_URL`）：web 写 `public.*`，gateway 写 `gateway.*`（gateway 只读 `public.api_keys` 做验签）。

## 命令

| 命令 | 作用 | 范围 |
|------|------|------|
| `make db-init`（= `db/apply.sh`） | 本地 docker 栈建库/刷新 | 空库全量建；已有库增量补 pending（web 逐条查 `_prisma_migrations`，gateway `IF NOT EXISTS`），安全重跑 |
| `make db-migrate-prod`（= `db/apply-prod.sh`） | 线上增量迁移 | 只补 web pending + gateway 幂等 SQL，逐条确认 |

`make db-init` 是**唯一刷新入口**，覆盖三种场景：① 空库从无到有；② 有数据的库上增量应用新迁移（不破坏存量数据）；③ 重复执行（全幂等，跳过已应用）。可选 `DB_NAME=xxx bash db/apply.sh` 指向特定库（默认 `POSTGRES_DB`），便于向测试库应用而不动真实库。

本地首次：`make docker-up` → `make db-init`（postgres 为空库，必须手动建库）。

## web（Prisma / public schema）变更流程

create-only 范式：Prisma 定义结构，SQL **手动执行**控制（不自动跑）。

```bash
cd web/backend
# 1. 改 db/web/prisma/schema.prisma（加 model / 字段 / @@index）
# 2. 生成迁移 SQL（仅生成，不执行）
npx prisma migrate dev --create-only --name <描述性名>   # 如 add_user_avatar
# 3. review
cat ../db/web/prisma/migrations/*_<描述性名>/migration.sql
# 4-5. 实际应用由 `make db-init`（本地）或 `make db-migrate-prod`（线上）统一完成
```

迁移命名：`<动词>_<对象>`（`add_xxx` / `drop_xxx` / `create_xxx_table`）。

## gateway（版本化 SQL / gateway schema）变更流程

新增一个 `<序号>_<描述>.sql`（如 `0002_add_webhook.sql`），DDL 用 `IF NOT EXISTS` 保证幂等，提交即可，由 `make db-init` / `make db-migrate-prod` 按文件名排序应用。

> gateway 暂用「排序执行 + `IF NOT EXISTS` 幂等」，不引入迁移跟踪表（仅 1 张表，YAGNI）。表多了再加 `gateway.schema_migrations`。

## ⚠️ Prisma 迁出 web/backend 的副作用（必读）

`schema.prisma` 位于 `db/web/prisma/`（不在 `web/backend/` 下）。Prisma 按「从 schema 文件向上找 `package.json`」推断项目根，会推断为**仓库根**，于是 `prisma generate` 会在**仓库根**自动安装 `@prisma/client`/`prisma`（产生根级 `node_modules/`、`package.json`、`package-lock.json`）。

应对：
- `schema.prisma` 的 `generator client` 已设显式 `output = "../../../web/backend/node_modules/.prisma/client"`，确保生成的 client 仍落 `web/backend/node_modules/.prisma/client/`，`import "@prisma/client"` 18 处导入不变。
- 根级 Prisma 污染物已在 `.gitignore` 用 `/package.json`、`/package-lock.json`、`/node_modules/`（锚定仓库根）忽略，不会入库。
- 这是 Prisma 项目根推断的副作用，**非本项目依赖**，可随时 `rm -rf node_modules package.json package-lock.json`（仓库根）清理，下次 generate 会按需重建。

## 禁止事项

- ❌ `prisma migrate dev`（无 `--create-only`）——自动执行 SQL，绕过手动控制。
- ❌ `prisma db push`——绕过迁移记录，破坏 `_prisma_migrations` 一致性。
- ❌ 手动 `ALTER TABLE`（不经 schema + migration）——schema 与库不一致。
- ❌ 在 web 或 gateway **代码里建库/建表**（如 SQLAlchemy `Base.metadata.create_all`、`CREATE SCHEMA`）——建库只走 `make db-init` / `make db-migrate-prod`。
- ❌ 手动执行 SQL 后跳过 `migrate resolve --applied`（web）——迁移记录不一致。
