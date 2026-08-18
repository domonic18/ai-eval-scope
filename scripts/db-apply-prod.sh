#!/usr/bin/env bash
# 全库建库/迁移统一应用（线上/生产）。
# 与 scripts/db-apply.sh 同源，差异：
#   - 凭据从 .secret/.env 读（生产 PLATFORM_DATABASE_URL，或由 POSTGRES_* 拼接，密码 URL 编码）；
#   - web 段只补未应用的 pending 迁移（查 _prisma_migrations 差集，不重跑已应用）；
#   - 逐条可见、需人工 y 确认；不跑 prisma generate（client 由 CI/Docker 构建生成）。
#
# gateway schema 已废弃（eval_jobs 并入 public schema）。
#
# ⚠️ 生产操作：执行前务必确认 DB_URL 指向正确的线上库，建议先备份。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

SECRET_ENV="$ROOT/.secret/.env"
if [ -f "$SECRET_ENV" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$SECRET_ENV"
  set +a
elif [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
else
  echo "❌ 缺少 .secret/.env 或 .env" >&2
  exit 1
fi

# 构建生产 DB URL（优先 PLATFORM_DATABASE_URL；否则由 POSTGRES_* 拼，密码 URL 编码）
url_encode() {
  python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$1"
}
if [ -n "${PLATFORM_DATABASE_URL:-}" ]; then
  DB_URL="$PLATFORM_DATABASE_URL"
else
  _user="${POSTGRES_USER:-eval}"
  _pwd="$(url_encode "${POSTGRES_PASSWORD:-evalpassword}")"
  _host="${POSTGRES_HOST:?POSTGRES_HOST required when PLATFORM_DATABASE_URL unset}"
  _port="${POSTGRES_PORT:-5432}"
  _db="${POSTGRES_DB:-agent_eval}"
  DB_URL="postgresql://$_user:$_pwd@$_host:$_port/$_db?schema=public"
fi
echo "目标库：$DB_URL"

WEB_MIGRATIONS="$ROOT/web/backend/prisma/migrations"

echo "==> 1/2 web(public schema)：仅应用 pending 迁移（查 _prisma_migrations 差集）"
applied="$(psql "$DB_URL" -tAc "SELECT migration_name FROM _prisma_migrations" 2>/dev/null || true)"
cd "$ROOT/web/backend"

# 在删除遗留指标列的 drop 迁移前，必须先回填 metrics，否则历史数据会丢失。
# 注意：此处仅做数据回填（migrateHistoricalMetrics），不做资产导入（importAssetsToDb）；
# 资产导入依赖后续迁移创建的表（如 defaults_assets），迁移全部完成后兜底执行。
_HISTORICAL_METRICS_DONE=0
ensure_historical_metrics() {
  if [ "$_HISTORICAL_METRICS_DONE" = "1" ]; then
    return
  fi
  echo ""
  echo "    ⚠️  即将应用删除遗留列的迁移，先执行一次性历史数据回填（幂等）"
  PLATFORM_DATABASE_URL="$DB_URL" npx tsx scripts/migrateHistoricalMetrics.ts
  _HISTORICAL_METRICS_DONE=1
}

_IMPORT_ASSETS_DONE=0
import_scenario_assets() {
  if [ "$_IMPORT_ASSETS_DONE" = "1" ]; then
    return
  fi
  echo ""
  echo "    📦 导入场景资产（courseware 场景/规则/提示词/指标等，幂等）"
  PLATFORM_DATABASE_URL="$DB_URL" npx tsx scripts/importAssetsToDb.ts
  _IMPORT_ASSETS_DONE=1
}

for d in $(ls -d "$WEB_MIGRATIONS"/*/ 2>/dev/null | sort); do
  name=$(basename "$d")
  if grep -qx "$name" <<<"$applied"; then
    echo "    • skip (applied): $name"
    continue
  fi
  # drop_run_legacy_metric_columns 与 drop_sample_legacy_score_columns 会删除一等列，
  # 必须在此之前完成数据回填
  if echo "$name" | grep -qE "drop_run_legacy|drop_sample_legacy"; then
    ensure_historical_metrics
  fi
  read -r -p "    应用 web/$name？[y/N] " ans </dev/tty
  if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
    psql "$DB_URL" -v ON_ERROR_STOP=1 -f "$d/migration.sql"
    PLATFORM_DATABASE_URL="$DB_URL" npx prisma migrate resolve --applied "$name" >/dev/null
    echo "    • applied: $name"
  else
    echo "    • skipped: $name"
  fi
done

# 全部迁移完成后导入场景资产（表已就绪，幂等，安全重跑）
import_scenario_assets

echo ""
echo "✅ 线上迁移完成（web pending + 历史数据）。单一来源 = db/。"
