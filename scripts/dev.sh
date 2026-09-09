#!/usr/bin/env bash
# 백엔드(:8000) + 프론트엔드(:5173) 동시 실행. Ctrl-C 로 둘 다 종료.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

[ -d backend/.venv ] || { echo "먼저 ./scripts/setup.sh 를 돌리세요."; exit 1; }
[ -f .env ] || { echo "먼저 ./scripts/setup.sh 를 돌리세요 (.env 없음)."; exit 1; }

# venv 실행 파일 위치: POSIX 는 bin/, Windows(Git Bash) 는 Scripts/
VENV_BIN=bin
if [ -d backend/.venv/Scripts ]; then VENV_BIN=Scripts; fi
PY="$ROOT/backend/.venv/$VENV_BIN/python"

# Windows 의 Smart App Control 은 로컬에서 만들어진 서명 없는 실행 파일을 막는다.
# venv 안의 python·uvicorn 이 여기 걸리면 (os error 4551) venv 를 만든 원본
# 인터프리터로 돌리고 패키지만 venv 에서 빌려온다. 나머지 환경에서는 그대로다.
if ! "$PY" -c "" >/dev/null 2>&1; then
  BASE="$(sed -n 's/^home[[:space:]]*=[[:space:]]*//p' backend/.venv/pyvenv.cfg)/python"
  if [ -n "$BASE" ] && "$BASE" -c "" >/dev/null 2>&1; then
    echo "  · venv 실행 파일이 차단되어 원본 인터프리터로 돌립니다"
    SITE="$(printf %s "$ROOT/backend/.venv/$VENV_BIN" | sed 's|/Scripts$|/Lib/site-packages|')"
    export PYTHONPATH="$SITE${PYTHONPATH:+;$PYTHONPATH}"
    PY="$BASE"
  else
    echo "backend/.venv 의 python 을 실행할 수 없습니다. ./scripts/setup.sh 를 다시 돌리세요."
    exit 1
  fi
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd "$ROOT/backend" && exec "$PY" -m uvicorn app.main:app --reload --port 8000) &
(cd "$ROOT/frontend" && exec npm run dev -- --port 5173) &

echo
echo "  백엔드  http://localhost:8000/docs"
echo "  프론트  http://localhost:5173"
echo
wait
