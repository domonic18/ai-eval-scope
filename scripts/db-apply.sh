#!/usr/bin/env bash
# 全库建库/迁移统一应用（本地 docker 栈）。
# 单一来源 = db/：全部走 web(public schema) Prisma migrations。
# （gateway schema 已随「执行拆分与网关合并」废弃，eval_jobs 并入 public schema。）
#
# 两步：web(逐条 prisma migration：未应用则 apply+resolve) → prisma generate。
# 前置：make docker-up（postgres 已起且健康）。
# 幂等 + 增量：web 逐条查 _prisma_migrations，已应用的跳过（空库则全应用，已有库只补 pending）。
# 故 `make db-init` 安全重跑，且可在有数据的库上增量迁移。
# 可选 DB_NAME 覆盖目标库（默认 POSTGRES_DB），便于向测试库应用而不动真实库。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "❌ 缺少 .env：请先 cp .env.example .env 并填入凭据" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

PGUSER="${POSTGRES_USER:-eval}"
PGPASSWORD="${POSTGRES_PASSWORD:-evalpassword}"
PGDB="${DB_NAME:-${POSTGRES_DB:-agent_eval}}"

if ! docker compose ps postgres 2>/dev/null | grep -q "Up"; then
  echo "❌ postgres 容器未运行：请先 make docker-up" >&2
  exit 1
fi

WEB_MIGRATIONS="$ROOT/web/backend/prisma/migrations"
DB_URL="postgresql://$PGUSER:$PGPASSWORD@localhost:5432/$PGDB?schema=public"

# 查某 web 迁移是否已在 _prisma_migrations（表不存在视为未应用，返回空）
web_already_applied() {
  docker compose exec -T postgres psql -U "$PGUSER" -d "$PGDB" -tAc \
    "SELECT 1 FROM _prisma_migrations WHERE migration_name='$1'" 2>/dev/null | tr -d '[:space:]'
}

echo "==> 1/2 应用 web(public schema) prisma migrations（增量幂等：已应用的跳过）"
cd "$ROOT/web/backend"

# 在删除遗留指标列的 drop 迁移前，必须先回填 metrics 与 snapshot，否则历史数据会丢失。
# 本地 docker 栈同样适用；脚本幂等，可安全重跑。
ensure_historical_migration() {
  if [ "${_HISTORICAL_MIGRATION_DONE:-}" = "1" ]; then
    return
  fi
  echo ""
  echo "    ⚠️  即将应用删除遗留列的迁移，先执行一次性历史数据迁移（幂等）"
  PLATFORM_DATABASE_URL="$DB_URL" npx tsx scripts/importAssetsToDb.ts
  PLATFORM_DATABASE_URL="$DB_URL" npx tsx scripts/migrateHistoricalMetrics.ts
  _HISTORICAL_MIGRATION_DONE=1
}

for d in $(ls -d "$WEB_MIGRATIONS"/*/ 2>/dev/null | sort); do
  name=$(basename "$d")
  if [ "$(web_already_applied "$name")" = "1" ]; then
    echo "    • skip (applied): web/$name"
    continue
  fi
  # drop_run_legacy_metric_columns 会删除一等指标列，必须在此之前完成数据回填
  if echo "$name" | grep -q "drop_run_legacy"; then
    ensure_historical_migration
  fi
  echo "    • apply: web/$name"
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$PGDB" \
    < "$d/migration.sql" >/dev/null
  PLATFORM_DATABASE_URL="$DB_URL" npx prisma migrate resolve --applied "$name" >/dev/null
done

# 若循环中未触发 drop 迁移（本地空库首次初始化不会走到 drop），仍兜底执行一次，
# 确保 courseware 场景、资产、snapshot 已就绪。
ensure_historical_migration

echo "==> 2/2 生成 prisma client（host node_modules）"
npx prisma generate >/dev/null

echo ""
echo "✅ 完成：web(public) schema 已就绪、迁移已标记、client 已生成（增量幂等，可安全重跑）。"
echo "   目标库 = ${PGDB}；schema 来源 = web/backend/prisma（Prisma）；详见 web/CLAUDE.md。"
