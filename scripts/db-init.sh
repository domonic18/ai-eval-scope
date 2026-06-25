#!/usr/bin/env bash
# 本地 docker 栈首次建库（手动，方案 B）。
#
# 按时间戳顺序应用所有 prisma migration → 标记为已应用 → 生成 client。
# 完全手动：不跑 `prisma migrate deploy`，SQL 内容 100% 由人工 create-only 生成并 commit。
#
# 前置：make docker-up（postgres 已起且健康）。
# 后续 schema 变更走 create-only 流程（web/backend/prisma/README.md §二）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "❌ 缺少 .env：请先 cp .env.example .env 并填入凭据" >&2
  exit 1
fi
# 从 .env 读 postgres 凭据（与 docker-compose env_file 一致）
set -a
# shellcheck disable=SC1091
source .env
set +a

PGUSER="${POSTGRES_USER:-eval}"
PGPASSWORD="${POSTGRES_PASSWORD:-evalpassword}"
PGDB="${POSTGRES_DB:-agent_eval}"

# 确认 postgres 容器在跑
if ! docker compose ps postgres 2>/dev/null | grep -q "Up"; then
  echo "❌ postgres 容器未运行：请先 make docker-up" >&2
  exit 1
fi

echo "==> 1/3 按时间戳顺序应用 migration.sql（经 postgres 容器，ON_ERROR_STOP）"
for d in $(ls -d web/backend/prisma/migrations/*/ | sort); do
  name=$(basename "$d")
  echo "    • $name"
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$PGDB" \
    < "$d/migration.sql" >/dev/null
done

echo "==> 2/3 标记迁移为已应用（写 _prisma_migrations；host prisma 连 localhost:5432）"
DB_URL="postgresql://$PGUSER:$PGPASSWORD@localhost:5432/$PGDB?schema=public"
cd web/backend
for d in $(ls -d prisma/migrations/*/ | sort); do
  name=$(basename "$d")
  if PLATFORM_DATABASE_URL="$DB_URL" npx prisma migrate resolve --applied "$name" >/dev/null 2>&1; then
    echo "    • resolved: $name"
  else
    echo "    • already resolved: $name"
  fi
done

echo "==> 3/3 生成 prisma client（host node_modules）"
npx prisma generate >/dev/null

echo ""
echo "✅ 建库完成：表已创建、迁移已标记、client 已生成。"
echo "   访问 http://localhost:9000 ；后续 schema 变更走 create-only 流程（规范 §二）。"
