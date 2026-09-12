# 컨테이너 하나가 API 와 프론트엔드를 같이 서빙한다 (TODO §14).
# 오리진이 하나가 되어 CORS · 쿠키 SameSite · OAuth 오리진을 두 곳에 맞출 일이 없다.

# ── 1단계: 프론트엔드를 빌드한다 ──────────────────────────────
# node_modules(137MB)는 여기서만 쓰고 버린다. 최종 이미지에는 dist/ 만 들어간다.
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build

# ── 2단계: 실행 ───────────────────────────────────────────────
FROM python:3.11-slim
# psql 은 scripts/migrate.sh 가 쓴다. 이게 있으면 호스트(Windows)에 psql 을 깔 필요가 없다.
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# 의존성을 먼저 깐다 — 코드만 바뀔 때 이 레이어를 다시 안 만든다.
COPY backend/pyproject.toml backend/
RUN mkdir -p backend/app && touch backend/app/__init__.py \
 && pip install --no-cache-dir -e ./backend

COPY backend/ backend/
COPY supabase/ supabase/
COPY scripts/migrate.sh scripts/
COPY --from=frontend /build/dist/ frontend/dist/

ENV PYTHONUNBUFFERED=1
# 컨테이너 안에서는 늘 8000 이다. 바깥 포트는 compose 가 바꿔 매핑한다.
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

# 뜰 때 적용 안 된 마이그레이션만 먹이고 (§3) 서버를 띄운다.
CMD ["sh", "-c", "./scripts/migrate.sh && exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000"]
