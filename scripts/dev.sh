#!/usr/bin/env bash
# 백엔드(:8000) + 프론트엔드(:5173) 동시 실행. Ctrl-C 로 둘 다 종료.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

[ -d backend/.venv ] || { echo "먼저 ./scripts/setup.sh 를 돌리세요."; exit 1; }
[ -f .env ] || { echo "먼저 ./scripts/setup.sh 를 돌리세요 (.env 없음)."; exit 1; }

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd "$ROOT/backend" && exec ./.venv/bin/uvicorn app.main:app --reload --port 8000) &
(cd "$ROOT/frontend" && exec npm run dev -- --port 5173) &

echo
echo "  백엔드  http://localhost:8000/docs"
echo "  프론트  http://localhost:5173"
echo
wait
