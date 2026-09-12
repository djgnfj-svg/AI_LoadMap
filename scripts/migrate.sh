#!/usr/bin/env bash
# 적용 안 된 마이그레이션만 골라 먹인다.
#
#   ./scripts/migrate.sh                   적용 안 된 것만 적용
#   ./scripts/migrate.sh --baseline 0010   그 번호까지를 돌리지 않고 적용됨으로 표시
#   ./scripts/migrate.sh --status          어디까지 적용됐는지만 본다
#
# `--baseline` 은 **이력 테이블이 생기기 전에 만든 DB** 를 한 번 맞출 때만 쓴다.
# 그 DB 에는 0001~0009 가 이미 들어 있지만 기록이 없어서, 그냥 돌리면
# 0001_init.sql 의 `create table` 에서 죽는다.
set -euo pipefail

cd "$(dirname "$0")/.."
# NOTICE 는 숨긴다 ("already exists, skipping" 이 줄줄이 나오면 진짜 오류가 묻힌다).
export PGOPTIONS="${PGOPTIONS:--c client_min_messages=warning}"
DB_NAME="${DB_NAME:-roadmap_planner}"
DATABASE_URL="${DATABASE_URL:-postgresql://postgres@localhost:5432/${DB_NAME}}"
HISTORY=supabase/migrations/0011_schema_migrations.sql

q()    { psql -v ON_ERROR_STOP=1 -tAq -d "$DATABASE_URL" "$@"; }
num()  { echo "$((10#${1:0:4}))"; }   # 앞 4자리. 10# 이 없으면 0009 가 8진수로 읽힌다.
mark() { q -c "insert into schema_migrations (filename) values ('$1') on conflict do nothing" >/dev/null; }

# 이력 테이블이 먼저 있어야 무엇이 적용됐는지 물어볼 수 있다. 자기 자신도 기록해 둔다.
q -f "$HISTORY" >/dev/null
mark "$(basename "$HISTORY")"

if [ "${1:-}" = "--status" ]; then
  q -c "select filename, applied_at from schema_migrations order by filename"
  exit 0
fi

if [ "${1:-}" = "--baseline" ]; then
  [ -n "${2:-}" ] || { echo "✗ ./scripts/migrate.sh --baseline 0010 처럼 번호를 주세요" >&2; exit 1; }
  for f in supabase/migrations/*.sql; do
    b="$(basename "$f")"
    if [ "$(num "$b")" -le "$(num "$2")" ]; then
      mark "$b"
      echo "  · $b (돌리지 않고 적용됨으로 표시)"
    fi
  done
  shift 2
fi

applied="$(q -c 'select filename from schema_migrations')"
for f in supabase/migrations/*.sql; do
  b="$(basename "$f")"
  if grep -qxF "$b" <<<"$applied"; then
    echo "  · $b"
    continue
  fi
  if ! psql -v ON_ERROR_STOP=1 -q -d "$DATABASE_URL" -f "$f" >/dev/null; then
    echo "✗ $b 에서 실패했습니다." >&2
    echo "  이력 테이블이 생기기 전에 만든 DB 라면 이미 적용된 것까지를 한 번 표시하세요:" >&2
    echo "    ./scripts/migrate.sh --baseline 0010" >&2
    exit 1
  fi
  mark "$b"
  echo "  ✓ $b"
done
