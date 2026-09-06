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
supabase/migrations/           §4 스키마. 12개 테이블 + 노드 상태 뷰
scripts/setup.sh               로컬 세팅 한 방
scripts/dev.sh                 백엔드 + 프론트 동시 실행
frontend/
  src/screens/GoalInput.tsx    목표 입력 → clarify → SSE 진행
  src/screens/Main.tsx         2분할 + 양방향 하이라이트
  src/screens/ReviewSession.tsx 재점검 세션 (집계 → 진단 → diff → 승인)
  src/components/ArchNode.tsx  §2.5 노드 상태 4종 렌더
backend/
  scripts/seed_self.py         이 프로젝트 자신의 로드맵을 시드로 (§6.2 백필 기반)
  app/graphs/                  LangGraph 생성 그래프
    critic.py                  검증 (LLM 미개입) — 이 그래프의 존재 이유
    repair.py                  재시도 소진 시 결정적 복구
    plan_graph.py              intake → clarify → decompose → architect → link → critic → emit
    replan_graph.py            collect_signals → diagnose → replan_scope → propose → critic → diff
    replan.py                  제안 → 승인 단위 변환 (순환·120분 위반은 여기서 걸러낸다)
    persist.py                 emit — 검증된 초안을 DB 로
    llm.py                     Claude 호출 경계면 (테스트에서 가짜로 교체)
    mock_planner.py            API 키 없이 그래프를 끝까지 돌리는 목업
  app/api/                     §3.5 REST + SSE
  app/scheduler.py             §3.6 스케줄러 4개 작업
  app/services/detection.py    §2.3·§4.5 실패 감지 — 전부 SQL (R2)
  app/services/alerts.py       §2.3 알람 5종 (톤은 R5)
  app/services/               이벤트 기록, 노드 상태 동기화, 재설계 적용
  tests/                       critic / repair / 그래프 / 저장 / API
```

## 설계상 지키는 것

| 규칙 | 코드에서 강제되는 지점 |
|---|---|
| R1 티켓 ≤ 120분 | `tickets.est_minutes` CHECK 제약 + `critic.py` + 실패 시 `repair.py` 자동 재분할 |
| R2 감지는 SQL만 | `detection.py` · `alerts.py` · `v_node_status` 뷰에 LLM 호출이 없다. AI 는 `diagnose`/`propose` 두 노드에만 등장한다 |
| R3 재설계는 마일스톤 1개 | `replan_scope` 가 지연이 가장 많은 마일스톤 하나만 고른다 |
| R4 `missed`는 이벤트 | `defer` 는 `delay_count` 만 올리고 `status` 는 유지. 같은 마감일에 두 번 기록하지 않는다 |
| R5 알람은 진단 | "netcode 쪽에서 3번 멈췄어요. 다시 짤까요?" — 문구가 기능이다 |

## 시작하기

```bash
git clone https://github.com/djgnfj-svg/AI_LoadMap.git
cd AI_LoadMap

./scripts/setup.sh --seed-demo   # DB 생성 + 마이그레이션 + 의존성 + 시드
./scripts/dev.sh                 # 백엔드 :8000 + 프론트 :5173
```

필요한 것: **Python 3.11+**, **Node 20+**, **PostgreSQL 14+**.

`setup.sh` 가 출력하는 `http://localhost:5173/#/<project_id>` 로 들어가면
로드맵 · 아키텍처 · at_risk 노드 · 재점검일이 이미 잡힌 상태로 시작합니다.

| 명령 | 하는 일 |
|---|---|
| `./scripts/setup.sh` | DB · 의존성 · `.env` 만 준비 |
| `./scripts/setup.sh --seed` | + 이 프로젝트 자신의 로드맵 시드 |
| `./scripts/setup.sh --seed-demo` | + 지연·막힘 이력까지 (감지·재점검을 바로 보려면) |
| `./scripts/dev.sh` | 백엔드 + 프론트 동시 실행 |

접속 정보를 바꾸려면 `DATABASE_URL=... ./scripts/setup.sh` 로 넘기거나
루트 `.env` 를 직접 고칩니다. Supabase 를 쓸 거면 프로젝트의
Settings → Database → Connection string (URI) 을 그대로 넣으면 됩니다.

### API 키 없이 돌리기

`.env` 의 `ANTHROPIC_API_KEY` 가 비어 있으면 **목업 Planner** 가 들어갑니다.
그래프 구조 · critic 재시도 · 진단 · 재설계는 그대로 돌고 LLM 호출만 결정적 목업으로 바뀝니다.
목업은 **첫 분해에서 일부러 120분을 넘겨** critic 재시도가 화면에 보이게 합니다.

실제 Claude 를 쓰려면 [키](https://console.anthropic.com/settings/keys)를 `.env` 에 넣으면 됩니다.

### 직접 세팅하기

```bash
createdb roadmap_planner
psql -d roadmap_planner -f supabase/migrations/0001_init.sql
psql -d roadmap_planner -f supabase/migrations/0002_alerts.sql

cd backend && uv venv --python 3.11 .venv && VIRTUAL_ENV=.venv uv pip install -e ".[dev]"
cd ../frontend && npm install
cp .env.example .env       # 레포 루트에 둔다. 백엔드가 루트에서 읽는다.
```

## 테스트

```bash
cd backend
.venv/bin/python -m pytest -q          # 107개
.venv/bin/ruff check app tests scripts

cd ../frontend
npm run build                          # tsc -b && vite build
npm run lint
```

`critic` · `repair` · 생성/재설계 그래프 테스트는 **API 키 없이** 돕니다 (목업 Planner).
DB 테스트는 Postgres 가 필요하고, 없으면 자동으로 skip 합니다.

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
| D4 | React 기본 화면 + 티켓 보드 | 완료 |
| D5 | React Flow 다이어그램 | 완료 |
| D6 | 노드 채워지는 연동 | 완료 (티켓 완료 → 노드 채움, 지연 2건 → at_risk) |
| D7 | 이벤트 기록 + 스케줄러 + 백필 | 완료 |
| D8 | 알람 + 재점검일 생성 | 완료 |
| D9 | 재설계 그래프 + diff 승인 | 완료 |
| D10 | 실제 프로젝트 투입 | `scripts/seed_self.py` 로 시드 완료, 계속 쓰면서 검증 남음 |
| D11 | UI 정리 + 배포 | — |

## API

| Method | Path | 상태 |
|---|---|---|
| POST | `/projects` | 목표 입력 → 생성 그래프 시작 |
| GET | `/projects/{id}/stream` | SSE, 그래프 진행 상황 |
| POST | `/projects/{id}/clarify` | clarify 응답 제출 |
| GET | `/projects/{id}` | 로드맵 + 아키텍처 + 노드 상태 |
| PATCH | `/tickets/{id}` | `start` / `complete` / `block` / `unblock` / `defer` |
| POST | `/tickets/{id}/block` | 막힘 사유 한 줄 입력 |
| GET | `/projects/{id}/alerts` | 미확인 알람 + 잡힌 재점검일 |
| POST | `/alerts/{id}/ack` | 알람 확인 |
| POST | `/projects/{id}/detect` | 스케줄러 작업을 즉시 한 번 (데모·개발용) |
| GET | `/reviews/{id}` | 집계 숫자 + 저장된 재설계 결과 |
| POST | `/reviews/{id}/run` | 재설계 그래프 실행 |
| POST | `/reviews/{id}/apply` | diff 항목별 승인/거절 |
| PATCH | `/reviews/{id}` | 재점검일 미루기 (삭제는 없다) |
| GET | `/projects/{id}/export` | 자를 수 있는 항목 (§0.3) |
