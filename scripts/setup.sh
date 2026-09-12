#!/usr/bin/env bash
# 로컬 개발 환경 세팅. 한 번만 돌리면 된다.
#
#   ./scripts/setup.sh              DB 만들고 의존성 설치
#   ./scripts/setup.sh --seed       + 이 프로젝트 자신의 로드맵을 시드로 넣기
#   ./scripts/setup.sh --seed-demo  + 지연·막힘 이력까지 (감지·재점검 화면을 바로 보려면)
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
DB_NAME="${DB_NAME:-roadmap_planner}"
DATABASE_URL="${DATABASE_URL:-postgresql://postgres@localhost:5432/${DB_NAME}}"

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }
need() {
  command -v "$1" >/dev/null 2>&1 || { echo "  ✗ $1 이 필요합니다. $2"; exit 1; }
}

say "1/5  필요한 것 확인"
need python3 "https://www.python.org/downloads/"
need node    "https://nodejs.org/  (20 이상)"
need psql    "PostgreSQL 14 이상. macOS: brew install postgresql@16"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || { echo "  ✗ Python 3.11 이상이 필요합니다 (현재 $(python3 -V))"; exit 1; }
echo "  ✓ python $(python3 -V | cut -d' ' -f2) / node $(node -v) / psql $(psql -V | cut -d' ' -f3)"

say "2/5  데이터베이스"
if psql "$DATABASE_URL" -c 'select 1' >/dev/null 2>&1; then
  echo "  ✓ 이미 있음: $DB_NAME"
else
  # 같은 접속 정보의 maintenance DB 로 붙어 만든다 (createdb 는 DATABASE_URL 을 안 읽는다).
  ADMIN_URL="${DATABASE_URL%/*}/postgres"
  psql -q -d "$ADMIN_URL" -c "create database \"${DB_NAME}\"" 2>/dev/null || {
    echo "  ✗ 데이터베이스 생성 실패. Postgres 가 떠 있는지, 접속 정보가 맞는지 확인하세요."
    echo "    DATABASE_URL=$DATABASE_URL"
    exit 1
  }
  echo "  ✓ 생성: $DB_NAME"
fi
# 적용 안 된 것만 먹인다 (scripts/migrate.sh). 배포에서는 이 스크립트만 따로 돌린다.
DATABASE_URL="$DATABASE_URL" ./scripts/migrate.sh "$@"

say "3/5  백엔드"
cd "$ROOT/backend"
if [ ! -d .venv ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.11 .venv >/dev/null
  else
    python3 -m venv .venv
  fi
fi
# venv 실행 파일 위치: POSIX 는 bin/, Windows(Git Bash) 는 Scripts/
VENV_BIN=bin
if [ -d .venv/Scripts ]; then VENV_BIN=Scripts; fi
if command -v uv >/dev/null 2>&1; then
  VIRTUAL_ENV=.venv uv pip install -q -e ".[dev]"
else
  "./.venv/$VENV_BIN/pip" install -q --upgrade pip
  "./.venv/$VENV_BIN/pip" install -q -e ".[dev]"
fi
echo "  ✓ backend/.venv"

say "4/5  프론트엔드"
cd "$ROOT/frontend"
npm install --silent
echo "  ✓ frontend/node_modules"

say "5/5  .env"
cd "$ROOT"
if [ -f .env ]; then
  echo "  · .env 가 이미 있어 건드리지 않습니다"
else
  sed "s|^DATABASE_URL=.*|DATABASE_URL=${DATABASE_URL}|" .env.example > .env
  echo "  ✓ .env 생성 (ANTHROPIC_API_KEY 를 채우거나 USE_MOCK_PLANNER=true 로 두세요)"
fi

if [ "${1:-}" = "--seed" ] || [ "${1:-}" = "--seed-demo" ]; then
  say "시드"
  cd "$ROOT/backend"
  ARGS="--reset"
  [ "${1:-}" = "--seed-demo" ] && ARGS="--reset --demo-history"
  VENV_BIN=bin
  if [ -d .venv/Scripts ]; then VENV_BIN=Scripts; fi
  DATABASE_URL="$DATABASE_URL" "./.venv/$VENV_BIN/python" scripts/seed_self.py $ARGS
fi

say "끝났습니다"
cat <<'MSG'
  ./scripts/dev.sh        백엔드 + 프론트엔드 동시 실행
  http://localhost:5173   접속

  API 키가 없어도 됩니다. .env 의 ANTHROPIC_API_KEY 가 비어 있으면
  목업 Planner 가 들어가고, 생성·재설계 그래프는 그대로 돕니다.
MSG
