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
                               0003 이 계층을 주 > 태스크 > 티켓으로 바꾼다
                               0004 가 users 를 넣고 프로젝트에 주인을 붙인다
                               0005 가 인터뷰 문답을 프로젝트에 붙인다
scripts/setup.sh               로컬 세팅 한 방
scripts/dev.sh                 백엔드 + 프론트 동시 실행
frontend/
  src/screens/Login.tsx        구글 로그인 (또는 데모 계정)
  src/screens/ProjectList.tsx  내 로드맵 목록
  src/screens/GoalInput.tsx    목표 입력 → 인터뷰(청사진부터) → SSE 진행
  src/screens/Main.tsx         2분할 + 양방향 하이라이트
  src/screens/ReviewSession.tsx 재점검 세션 (집계 → 진단 → diff → 승인)
  src/components/ArchNode.tsx  §2.5 노드 상태 4종 렌더
backend/
  scripts/seed_self.py         이 프로젝트 자신의 로드맵을 시드로 (§6.2 백필 기반)
  app/graphs/                  LangGraph 생성 그래프
    critic.py                  검증 (LLM 미개입) — 이 그래프의 존재 이유
    interview.py               1라운드 고정 질문 (LLM 미개입) + 답변 → 제약 반영
    repair.py                  재시도 소진 시 결정적 복구
    plan_graph.py              intake → interview → decompose → architect → link → critic → emit
    replan_graph.py            collect_signals → diagnose → replan_scope → propose → critic → diff
    replan.py                  제안 → 승인 단위 변환 (순환·120분 위반은 여기서 걸러낸다)
    persist.py                 emit — 검증된 초안을 DB 로
    llm.py                     Claude 호출 경계면 (테스트에서 가짜로 교체)
    mock_planner.py            API 키 없이 그래프를 끝까지 돌리는 목업
  app/auth.py                  구글 ID 토큰 검증 + 서명된 세션 쿠키
  app/api/                     §3.5 REST + SSE
  app/scheduler.py             §3.6 스케줄러 4개 작업
  app/services/detection.py    §2.3·§4.5 실패 감지 — 전부 SQL (R2)
  app/services/alerts.py       §2.3 알람 5종 (톤은 R5)
  app/services/               이벤트 기록, 노드 상태 동기화, 재설계 적용
  tests/                       critic / repair / 그래프 / 저장 / API
```

## 계층

```
프로젝트
  └─ 주        관리 단위이자 최상위. 그 주 마지막 저녁에 화면에 무엇이 있는가
      └─ 태스크  한 덩어리로 묶이는 티켓들의 집. 한 태스크는 한 주에만 산다
          └─ 티켓  실행 단위. 여기서만 실패가 측정된다
```

티켓을 부르는 이름은 두 겹이다 — `08-03` 은 8번 태스크의 셋째 티켓.
**티켓 번호는 태스크마다 01부터 다시 센다.** 그래서 태스크가 없으면 번호도 없다.

상태 낱말은 넷이고 태스크와 티켓이 같은 것을 쓴다:
`open` · `claimed` · `resolved` · `parked`.
⚠ **「막힘」은 상태가 아니다.** `parked` 는 접힘이지 막힘이 아니다. 막힌 티켓은
`claimed` 로 남고 `blocked_reason` 한 줄이 붙는다 — 상태 한 낱말과 막힘 한 줄은
별개의 사실이고, 섞으면 둘 다 못 읽는다.

## 설계상 지키는 것

| 규칙 | 코드에서 강제되는 지점 |
|---|---|
| R1 티켓 ≤ 120분 | `tickets.est_minutes` CHECK 제약 + `critic.py` + 실패 시 `repair.py` 자동 재분할 |
| R2 감지는 SQL만 | `detection.py` · `alerts.py` · `v_node_status` 뷰에 LLM 호출이 없다. AI 는 `diagnose`/`propose` 두 노드에만 등장한다 |
| R3 재설계는 주 1개 | `replan_scope` 가 지연이 가장 많은 주 하나만 고른다 |
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

### 로그인

구글 계정 하나만 받습니다. `.env` 의 `GOOGLE_CLIENT_ID` 가 **비어 있으면 데모 계정**으로
열립니다 — API 키가 없으면 목업 Planner 로 도는 것과 같은 결입니다.

실제 구글 로그인을 켜려면:

1. [Google Cloud Console](https://console.cloud.google.com/apis/credentials) → **사용자 인증 정보**
2. **OAuth 클라이언트 ID 만들기** → 애플리케이션 유형 **웹 애플리케이션**
3. **승인된 JavaScript 원본**에 `http://localhost:5173` 추가 (배포하면 그 도메인도)
4. 받은 클라이언트 ID 를 `.env` 의 `GOOGLE_CLIENT_ID` 에 붙여넣기
5. `SESSION_SECRET` 도 채웁니다 — 비어 있으면 서버를 재시작할 때마다 로그인이 풀립니다

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

⚠ `GOOGLE_CLIENT_ID` 가 들어오는 순간 **데모 로그인 문은 닫힙니다.** 배포한 곳에서
아무나 데모 계정으로 들어오는 것을 막기 위해서입니다.

### API 키 없이 돌리기

`.env` 의 `ANTHROPIC_API_KEY` 가 비어 있으면 **목업 Planner** 가 들어갑니다.
그래프 구조 · critic 재시도 · 진단 · 재설계는 그대로 돌고 LLM 호출만 결정적 목업으로 바뀝니다.
목업은 **첫 분해에서 일부러 120분을 넘겨** critic 재시도가 화면에 보이게 합니다.

실제 Claude 를 쓰려면 [키](https://console.anthropic.com/settings/keys)를 `.env` 에 넣으면 됩니다.

### 직접 세팅하기

```bash
createdb roadmap_planner
# 번호순으로 전부 적용한다. 하나라도 빠지면 뒤엣것이 깨진다.
for f in supabase/migrations/*.sql; do psql -v ON_ERROR_STOP=1 -d roadmap_planner -f "$f"; done

cd backend && uv venv --python 3.11 .venv && VIRTUAL_ENV=.venv uv pip install -e ".[dev]"
cd ../frontend && npm install
cp .env.example .env       # 레포 루트에 둔다. 백엔드가 루트에서 읽는다.
```

## 테스트

```bash
cd backend
.venv/bin/python -m pytest -q          # 134개
.venv/bin/ruff check app tests scripts

cd ../frontend
npm run build                          # tsc -b && vite build
npm run lint
```

`critic` · `repair` · 생성/재설계 그래프 · 세션 쿠키 테스트는 **API 키 없이** 돕니다 (목업 Planner).
DB 테스트는 Postgres 가 필요하고, 없으면 자동으로 skip 합니다 — skip 이 많이 보이면
DB 에 못 붙은 것이지 통과한 것이 아닙니다.

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
| D11 | UI 정리 + 배포 | 진행 중 — 로그인 · 내 로드맵 목록 완료 |

## API

모든 API 가 로그인을 요구합니다. 남의 프로젝트는 403 이 아니라 **404** 입니다 —
403 은 "그 id 는 실재한다"를 알려주는 답이기 때문입니다.

| Method | Path | 상태 |
|---|---|---|
| GET | `/auth/config` | 구글 버튼을 그릴지 데모 버튼을 그릴지 |
| GET | `/auth/me` | 현재 로그인 상태 (로그인 전이면 `user: null`) |
| POST | `/auth/google` | 구글 ID 토큰 → 세션 쿠키 |
| POST | `/auth/demo` | 데모 계정 (구글이 꺼져 있을 때만) |
| POST | `/auth/logout` | 쿠키 삭제 |
| GET | `/projects` | 내 로드맵 목록 |
| POST | `/projects` | 목표 입력 → 생성 그래프 시작 |
| GET | `/projects/{id}/stream` | SSE, 그래프 진행 상황 |
| POST | `/projects/{id}/clarify` | 인터뷰 답변 제출 (새로고침·재시작 뒤에도 이어진다) |
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
