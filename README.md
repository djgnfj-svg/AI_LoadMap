# Roadmap Planner

목표를 넣으면 **로드맵과 아키텍처가 함께 그려지고**, 진행 기록에 따라 스스로 다시 그려지는 도구.

- 기준 문서: **[docs/SPEC.md](docs/SPEC.md)** — 이 하나가 프로젝트의 유일한 스펙이다.
- 용도: 원티드 AI 챔피언십 2026 출품작 (접수 09-18 / 제출 09-20)

기존 도구는 계획을 **생성**해준다. 생성은 LLM에게 5분이면 되는 일이다.
진짜 문제는 계획이 지켜지지 않을 때 아무도 알려주지 않고, 아무도 다시 그려주지 않는다는 것이다.
**차별점은 생성이 아니라 추적과 재설계에 있다.**

---

## 구조

```
docs/SPEC.md                   기준 문서 (§0 불변 규칙 R1~R6 포함)
supabase/migrations/           §4 스키마. 11개 테이블 + 노드 상태 뷰
backend/
  app/graphs/                  LangGraph 생성 그래프
    critic.py                  검증 (LLM 미개입) — 이 그래프의 존재 이유
    repair.py                  재시도 소진 시 결정적 복구
    plan_graph.py              intake → clarify → decompose → architect → link → critic → emit
    persist.py                 emit — 검증된 초안을 DB 로
    llm.py                     Claude 호출 경계면 (테스트에서 가짜로 교체)
  app/api/                     §3.5 REST + SSE
  app/services/                이벤트 기록, 노드 상태 동기화, 그래프 실행 관리
  tests/                       critic / repair / 그래프 / 저장 / API
```

## 설계상 지키는 것

| 규칙 | 코드에서 강제되는 지점 |
|---|---|
| R1 티켓 ≤ 120분 | `tickets.est_minutes` CHECK 제약 + `critic.py` + 실패 시 `repair.py` 자동 재분할 |
| R2 감지는 SQL만 | `v_node_status` 뷰, `events` 집계. LLM 은 `app/graphs/llm.py` 밖으로 나가지 않는다 |
| R4 `missed`는 이벤트 | `PATCH /tickets/{id}` 의 `defer` 는 `delay_count` 만 올리고 `status` 는 유지 |

## 개발 환경

```bash
# 1) DB
#    Supabase 프로젝트의 connection string 을 쓰거나, 로컬 Postgres 를 쓴다.
createdb roadmap_planner
psql -d roadmap_planner -f supabase/migrations/0001_init.sql

# 2) 백엔드
cd backend
uv venv --python 3.11 .venv
VIRTUAL_ENV=.venv uv pip install -e ".[dev]"
cp ../.env.example ../.env    # DATABASE_URL, ANTHROPIC_API_KEY 채우기

.venv/bin/uvicorn app.main:app --reload   # http://localhost:8000/docs
```

## 테스트

```bash
cd backend
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests
```

`critic` · `repair` · 생성 그래프 테스트는 **API 키 없이** 돈다 (`tests/fakes.py` 의 가짜 Planner).
저장 · API 테스트는 Postgres 가 필요하고, 없으면 자동으로 skip 한다.

```bash
# 다른 DB 를 쓰려면
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/postgres pytest -q
```

## 진행 상황

| 일차 | 작업 | 상태 |
|---|---|---|
| D1 | Supabase 스키마 + FastAPI 뼈대 | 완료 |
| D2 | 생성 그래프 (intake→emit) | 완료 |
| D3 | `critic` 루프 + 2시간 규칙 | 완료 |
| D4 | React 기본 화면 + 티켓 보드 | — |
| D5 | React Flow 다이어그램 | — |
| D6 | 노드 채워지는 연동 | 백엔드 완료 (`PATCH /tickets/{id}` → `node_changes`) |
| D7 | 이벤트 기록 + 스케줄러 + 백필 | 이벤트 기록만 완료 |
| D8 | 알람 + 재점검일 생성 | — |
| D9 | 재설계 그래프 + diff 승인 | — |

## API

| Method | Path | 상태 |
|---|---|---|
| POST | `/projects` | 목표 입력 → 생성 그래프 시작 |
| GET | `/projects/{id}/stream` | SSE, 그래프 진행 상황 |
| POST | `/projects/{id}/clarify` | clarify 응답 제출 |
| GET | `/projects/{id}` | 로드맵 + 아키텍처 + 노드 상태 |
| PATCH | `/tickets/{id}` | `start` / `complete` / `block` / `unblock` / `defer` |
| POST | `/tickets/{id}/block` | 막힘 사유 한 줄 입력 |
| GET | `/projects/{id}/alerts` | D8 |
| POST | `/reviews/{id}/run` · `/apply` | D9 |
| GET | `/projects/{id}/export` | 자를 수 있는 항목 (§0.3) |
