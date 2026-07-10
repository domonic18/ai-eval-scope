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

echo "==> 1/1 web(public schema)：仅应用 pending 迁移（查 _prisma_migrations 差集）"
applied="$(psql "$DB_URL" -tAc "SELECT migration_name FROM _prisma_migrations" 2>/dev/null || true)"
cd "$ROOT/web/backend"
for d in $(ls -d "$WEB_MIGRATIONS"/*/ 2>/dev/null | sort); do
  name=$(basename "$d")
  if grep -qx "$name" <<<"$applied"; then
    echo "    • skip (applied): $name"
    continue
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

echo ""
echo "✅ 线上迁移完成（web pending）。单一来源 = db/。"
