# Roadmap Planner — 프로젝트 기획서 (단일 스펙)

> 이 문서 하나가 프로젝트의 유일한 기준 문서다.
> AI 에이전트는 구현 전 이 문서를 전부 읽고, 충돌이 생기면 §0의 불변 규칙을 우선한다.

- **프로젝트**: 목표를 넣으면 로드맵과 아키텍처가 함께 그려지고, 진행 기록에 따라 스스로 다시 그려지는 도구
- **용도**: 원티드 AI 챔피언십 2026 출품작
- **접수 마감**: 2026-09-18 / **과제 제출**: 2026-09-20
- **작성일**: 2026-09-06

---

## 목차

- [§0. AI 에이전트 작업 지침](#0-ai-에이전트-작업-지침)
- [§1. 제품 정의](#1-제품-정의)
- [§2. 핵심 루프](#2-핵심-루프)
- [§3. 시스템 아키텍처](#3-시스템-아키텍처)
- [§4. 데이터 모델](#4-데이터-모델)
- [§5. 화면 설계](#5-화면-설계)
- [§6. 개발 로드맵](#6-개발-로드맵)
- [§7. 사업성 검토](#7-사업성-검토)

---

## §0. AI 에이전트 작업 지침

### 0.1 불변 규칙 (절대 위반 금지)

| # | 규칙 | 근거 |
|---|---|---|
| R1 | **티켓 1개 = 예상 소요 120분 이내.** 초과 시 강제 재분할 | 실패 지점 특정이 제품의 전부. 티켓이 크면 알람이 소음이 됨 |
| R2 | **실패 감지는 SQL 집계로만.** AI는 감지에 개입하지 않음 | 검증 가능한 숫자만 신뢰 가능. AI 판단이 근거가 되면 제품이 안 됨 |
| R3 | **1회 재설계 범위는 최대 주 1개** | 전체를 다시 그리면 사용자가 자기 계획이라고 느끼지 않음 |
| R4 | **`missed`는 상태가 아니라 이벤트** | 상태로 덮어쓰면 "몇 번 미뤘는가"가 사라짐 |
| R5 | **알람 문구는 책망이 아니라 진단** | 실패 감지 제품은 실패하는 순간 가장 먼저 버려짐 |
| R6 | **새로 배우는 기술 추가 금지** (React Flow만 예외) | 13일 일정 |

### 0.2 작업 순서

1. §4 스키마부터 생성한다. 스키마가 모든 로직의 기준이다.
2. §3.3 생성 그래프를 만든다. `critic` 노드 없이 진행하지 않는다.
3. §2.5 티켓↔노드 연동 시각화를 만든다. 이게 데모의 핵심 장면이다.
4. §2.3~2.4 감지·재점검을 만든다.
5. 나머지.

### 0.3 자를 수 있는 것 / 없는 것

**절대 못 자름**: 생성 그래프 + `critic` 루프 / 티켓↔노드 연동 시각화 / 재점검일 → 재설계 → diff 승인

**자를 수 있음**: 웹푸시(이메일만) / Export

⚠ **인터뷰도 자르지 않기로 했다** (2026-09-09 개정). 「clarify 1회 고정으로 축소」를 되돌린다. 목표 한 줄과 숫자 세 칸으로는 남의 계획과 구별되는 계획이 안 나온다. 게다가 그 1회 답변은 숫자만 뽑히고 문장은 버려지고 있었다 — 사용자가 무슨 말을 해도 계획이 같았다는 뜻이다. 이제 청사진부터 되묻고(§3.3), 답변 **원문**을 `projects.interview` 에 남겨 decompose 프롬프트에 넣는다.

⚠ **로그인은 자르지 않기로 했다** (2026-09-09 개정). 데모 계정 고정으로 두면 `projects.user_id` 가 비고, 프로젝트 id 만 알면 누구나 남의 로드맵을 읽고 고칠 수 있다. 로드맵이 「내 것」이 되려면 계정이 먼저 있어야 한다. 구글 로그인 하나만 받고, 세션은 서명된 쿠키 하나다 — 마이그레이션 `0004_auth.sql`, `app/auth.py`. 클라이언트 ID 가 설정돼 있지 않으면 데모 계정으로 열린다 (API 키가 없으면 목업 Planner 로 도는 것과 같은 결).

**절대 넣지 말 것**: 팀 기능 / 결제 / 다크모드 튜닝 / 랜딩 애니메이션 / 외부 이슈트래커 동기화 / 모바일 앱 / 코드 생성

---

## §1. 제품 정의

### 1.1 한 줄 정의

자연어로 목표를 입력하면 **주 → 태스크 → 실행 티켓**으로 분해되고, 동시에 시스템 아키텍처가 그려진다. 티켓을 완료하면 대응하는 아키텍처 노드가 채워진다. 지연·실패가 쌓이면 재점검일이 자동으로 잡히고, AI가 막힌 구간만 다시 설계한다.

### 1.2 왜 만드는가

AI가 필수인 시대가 되면서 진입 장벽이 코딩에서 **기획**으로 옮겨갔다. 처음 오는 사람이 겪는 순서:

1. 목표는 있다 — "AI 면접 서비스를 만들고 싶다"
2. 무엇부터 해야 할지 모른다
3. LLM에 물어본다 → 그럴듯한 계획이 나온다
4. **계획을 받았지만 첫 주가 지나면 어디쯤인지 모른다**
5. 표류하거나 포기한다

3번까지는 이미 해결된 영역이다. 이 제품은 **4번과 5번**을 겨냥한다.

바이브 코딩의 초석은 결국 로드맵과 청사진이다. 기존 도구는 계획을 **생성**해준다. 생성은 LLM에게 5분이면 되는 일이다. 진짜 문제는 계획이 지켜지지 않을 때 아무도 알려주지 않고, 아무도 다시 그려주지 않는다는 것이다.

> **차별점은 생성이 아니라 추적과 재설계에 있다.**

### 1.3 기존 도구의 빈 자리

| 도구군 | 하는 일 | 못 하는 일 |
|---|---|---|
| ChatGPT / Claude | 계획 생성 | 생성 후 추적 없음. 다음 대화에서 사라짐 |
| Notion / Jira / Linear | 티켓 관리 | 계획을 사람이 직접 짜야 함. 실패해도 아무 일 없음 |
| 마인드맵 AI (ProcessOn 등) | 구조 시각화 | 실행 단위가 아님. 진행 개념 없음 |
| 코딩 에이전트 plan mode | 코드 단위 계획 | 프로젝트 전 기간의 궤적을 못 봄 |

### 1.4 핵심 차별점 3가지

| # | 내용 |
|---|---|
| 1 | **로드맵 ↔ 아키텍처 연동** — 티켓과 노드가 매핑되어 진행률이 그림으로 보임 |
| 2 | **실패 지점 감지** — 어느 티켓·어느 컴포넌트에서 반복해 막히는지 데이터로 특정 |
| 3 | **자동 재점검일** — 반복 실패 시 날짜가 잡히고 그 구간만 부분 재설계 |

### 1.5 타겟

**1차 (데모·검증용)** — 개인 개발자 / 사이드 프로젝트를 여러 개 굴리는 사람
- 계획은 세울 줄 알지만 프로젝트 간 궤적이 흐려짐
- 코딩 에이전트를 쓰므로 **티켓 = 프롬프트 단위**로 바로 소비 가능

**2차 (확장)** — 게임 · 콘텐츠 등 **만드는 사람** 전반
- 소프트웨어가 아니어도 만들어지는 것이 있으면 같은 구조가 성립한다
- 목표를 구조화해서 말하지 못함 → 인터뷰(§3.3)와 도메인 프리셋이 필수

#### 도메인 프리셋 (2026-09-09 개정)

축은 **무엇을 만드는가**다. 이 도구는 만들어지는 것이 있어야 성립한다 — 티켓을 끝내면 그림의 한 칸이 차오르는 게 전부이기 때문이다. 점수나 습관에는 채울 칸이 없다. 그래서 확장 방향은 학습 쪽이 아니라 **제작 쪽**이다.

구조는 도메인과 무관하다 — 주 > 태스크 > 티켓, 티켓이 노드를 채우고, 지연이 쌓이면 재점검일이 잡힌다. **다른 것은 낱말뿐이다.** 그래서 프리셋 하나를 프롬프트에 끼우는 값 묶음으로 두고(`backend/app/graphs/domains.py`) 그래프·critic·감지는 건드리지 않는다.

| | 소프트웨어 | 게임 제작 | 그 밖의 만들기 |
|---|---|---|---|
| 그림 이름 | 아키텍처 | 게임 구조도 | 구성요소 지도 |
| 노드 | 컴포넌트 | 시스템 | 구성요소 |
| `node_type` | service · store · client | system · stage · asset | deliverable · skill · resource |
| `layer` | frontend · backend · data · infra | play · rule · content · build | output · practice · input · support |
| 티켓 본문 | 코딩 에이전트에 붙여넣는다 | 코드는 에이전트에, 에셋은 무엇을 몇 개 만들지 | 처음 하는 사람이 따라 한다 |
| 완료 조건 예시 | "테스트 3개 통과", "빌드 성공" | "친구 4명이 30분을 끊김 없이 돈다" | "영상 1편 업로드", "시제품 1개 조립" |

`external`(내가 만들지 않는 것)은 세 프리셋이 함께 쓴다.

⚠ **게임은 소프트웨어지만 낱말이 다르다.** 게임 로드맵에서 막히는 자리는 「백엔드」가 아니라 넷코드·보스 스테이지·사운드다. 그 낱말로 불러야 §2.3 의 알람이 진단으로 읽힌다 (R5).

도메인은 `intake` 가 목표 문장으로 **추정**하고, 사용자가 청사진 확정 화면에서 **바꾼다**. 추정이 틀려도 계획이 만들어지기 전에 사용자가 잡는다.

### 1.6 사용자 시나리오

```
[Day 0]  목표 입력: "3개월 안에 코옵 멀티플레이어 게임 하나 출시"
           ↓ clarify: 가용 시간? 엔진? 경험 수준? 혼자/팀?
         주 12개 + 태스크 30개 + 티켓 60개 생성
         동시에 아키텍처 다이어그램 생성 (노드 15개)

[Day 1~] 티켓 완료 체크 → 연결된 아키텍처 노드가 채워짐

[Day 5]  티켓 #23 기한 초과 24시간 → 알람
         "어디서 막혔나요?" 한 줄 입력

[Day 9]  같은 노드(netcode)에서 3번째 지연 감지
           ↓ 재점검일 자동 생성 (Day 11)

[Day 11] 재점검 세션
         AI가 netcode 구간만 재설계
         - 2시간 초과분 재분할
         - 선행 학습 티켓 삽입
         - 후속 주 일정 자동 이월
           ↓ 변경 diff를 사용자가 항목별 승인/거절
```

### 1.7 성공 기준

**공모전**
- 데모 영상에서 재점검 → 재설계 → 다이어그램 변화가 3분 안에 전달될 것
- 시드 데이터가 실제 프로젝트일 것 (가짜 데이터 금지)

**제품**
- 생성된 티켓 중 90% 이상이 120분 이내
- 재설계 제안 승인율
- 4주차 생존율 ← 이 제품의 진짜 지표

---

## §2. 핵심 루프

이 절이 제품의 심장이다. 나머지는 전부 이걸 굴리기 위한 장치다.

### 2.1 계층 구조

```
프로젝트 (goal)
  └─ 주              예: "2주 - 캐릭터가 움직인다"          관리 단위
      └─ 태스크       예: "이동과 충돌"                     주당 2~5개
          └─ 티켓     예: "이동 입력 처리 함수 작성" (90분)  실행 단위
```

- **주**: **관리 단위이자 최상위.** 그 주 마지막 저녁에 화면에 무엇이 있는가
- **태스크**: 한 덩어리로 묶이는 티켓들의 집. ⚠ **한 태스크는 한 주에만 산다**
- **티켓**: **여기서만 실패가 측정된다**

번호는 두 겹이다. 태스크 번호는 프로젝트 안에서 전역으로 세고(2주에 17번
태스크가 있을 수 있다), 티켓 번호는 **태스크마다 01부터 다시 센다.**
그래서 티켓을 부르는 이름이 `NN-MM` 이고, 태스크가 없으면 번호도 없다 —
번호 앞자리가 태스크이기 때문이다.

#### 상태 낱말 넷

태스크와 티켓이 같은 낱말을 쓴다: `open` · `claimed` · `resolved` · `parked`.

⚠ **「막힘」은 여기 없다.** `parked` 는 접힘(의도적으로 미룸)이지 막힘이 아니다.
막혔다는 것은 잡고 있다가 멈췄다는 뜻이므로 상태는 `claimed` 로 두고, 사유를
`tickets.blocked_reason` 한 줄과 `blocked` 이벤트가 든다. 상태 한 낱말과 막힘
한 줄은 별개의 사실이고, 섞으면 둘 다 못 읽는다. 막힌 티켓을 찾는 쪽은
`status` 가 아니라 `blocked_reason` 을 본다.

태스크 상태는 사람이 따로 관리하는 값이 아니라 **그 안의 티켓에서 되읽는
값이다** (`app/services/task_status.py`). 한 사실은 한 곳에만 산다.

### 2.2 티켓 설계

#### 왜 2시간 규칙인가 (R1)

LLM에게 분해를 시키면 "인증 구현", "DB 설계" 같은 덩어리가 나온다. 그러면:

```
3일째 미완료 알람 → 사용자는 어디를 손대야 할지 모름 → 알람이 소음 → 앱 삭제
```

티켓이 잘게 쪼개져 있어야 "어느 지점에서 막혔는지"가 특정된다. 실패 지점 특정이 제품의 전부이므로 티켓 크기 통제는 타협 대상이 아니다.

#### 티켓이 물고 있어야 하는 3가지

| 연결 대상 | 용도 |
|---|---|
| 아키텍처 노드 (`ticket_node_links`) | 완료 시 노드가 채워짐 → 시각적 진행률 |
| 이벤트 로그 (`events`) | 지연·차단·완료 기록 누적 |
| 선행 티켓 (`ticket_dependencies`) | 순환 의존 검증, 재설계 시 영향 범위 계산 |

#### 티켓 본문 포맷

코딩 에이전트에 그대로 붙여넣을 수 있게 작성한다.

```markdown
## 무엇을
(한 문장 목표)

## 완료 조건
- [ ] 검증 가능한 조건 1
- [ ] 검증 가능한 조건 2

## 참고
- 연결 컴포넌트: <node_key>
- 선행 티켓: #12, #15
```

완료 조건은 반드시 검증 가능한 형태로 쓴다. "잘 동작한다" ✗ / "테스트 3개 통과", "빌드 성공", "응답 200" ✓

### 2.3 실패 감지

모든 신호는 `events` 테이블 집계로 계산한다. AI는 감지 단계에 개입하지 않는다 (R2).

#### 이벤트 종류

| type | 발생 시점 |
|---|---|
| `created` | 티켓 생성 |
| `started` | 사용자가 시작 표시 |
| `completed` | 완료 체크 |
| `missed` | 마감일 경과 (스케줄러 자동 기록) |
| `deferred` | 사용자가 기한 연기 |
| `blocked` | 사용자가 막힘 사유 입력 |

#### 알람 규칙

| 조건 | 반응 | 강도 |
|---|---|---|
| 마감 24시간 경과 | "어디서 막혔나요?" 한 줄 입력 요청 | 낮음 |
| 동일 티켓 2회 연기 | 티켓 재분할 제안 | 중간 |
| **동일 아키텍처 노드에서 지연 2건 이상** | **재점검일 자동 생성** | 높음 |
| 주간 완료율 50% 미만 | 주간 리뷰 알람 | 중간 |
| 3일 연속 무활동 | 체크인 (알람 아님, 질문) | 낮음 |

#### 알람 톤 (R5)

- ✗ "3일째 완료하지 않았습니다"
- ✓ "netcode 쪽에서 세 번 멈췄어요. 이 구간을 다시 짤까요?"

### 2.4 재점검일 (Review Day)

#### 트리거

동일 노드 지연 2건 이상 → 다음 가용일에 `review_days` 생성.
사용자는 날짜 변경만 가능하고 **삭제 불가**. 미루면 미룬 사실도 이벤트로 기록된다.

#### 세션 흐름

```
1. 집계 제시 (AI 아님, 숫자)
   - 이 노드 관련 티켓 7개 중 3개 지연
   - 평균 지연 2.4일
   - 사용자가 입력한 막힘 사유 3건

2. 진단 (AI)
   - 지식부족 / 범위과다 / 의존성누락 / 외부요인

3. 부분 재설계 (AI) — 최대 주 1개 범위 (R3)
   - 범위 축소 · 재분할 · 선행 학습 티켓 삽입 · 순서 교체
   - 영향받는 후속 주 일정 자동 이월

4. diff 승인
   - 변경 전/후를 나란히 표시, 항목별 승인/거절
```

#### 진단별 처방

| 진단 | 처방 |
|---|---|
| 지식부족 | 선행 학습 티켓 삽입 (자료 링크 포함) |
| 범위과다 | 티켓 재분할, 목표 범위 축소 |
| 의존성누락 | 선행 티켓 추가, 순서 교체 |
| 외부요인 | 일정만 이월, 내용 유지 |

### 2.5 진행 시각화

티켓 완료가 아키텍처 노드 상태로 즉시 반영된다. **데모에서 가장 강한 장면.**

| 노드 상태 | 조건 | 표현 |
|---|---|---|
| `pending` | 연결 티켓 0% 완료 | 회색 외곽선 |
| `in_progress` | 1~99% | 부분 채움 |
| `done` | 100% | 완전 채움 |
| `at_risk` | 지연 2건 이상 | 경고 테두리 (최우선 표시) |

`at_risk`가 다이어그램 위에 직접 보이는 것이 핵심이다. "어디서 막혔는지"가 텍스트가 아니라 **그림에서 즉시 읽힌다.**

---

## §3. 시스템 아키텍처

### 3.1 스택

| 영역 | 선택 | 이유 |
|---|---|---|
| Backend | FastAPI (Python) | 기존 경험 스택, 속도 |
| AI 오케스트레이션 | LangGraph | 조건부 루프(critic 재시도)가 필수. 단순 체인 불가 |
| DB | Supabase (PostgreSQL) | 인증·RLS 기본 제공 → 인증 직접 구현 회피 |
| Frontend | React | React Flow 호환 |
| 다이어그램 | React Flow | 노드 상태 실시간 갱신, 커스텀 노드 렌더 |
| 스케줄러 | APScheduler | 별도 인프라 없이 FastAPI 프로세스 내 실행 |
| LLM | Claude (Sonnet) | 구조화 출력 안정성 |

### 3.2 전체 구성

```
┌─────────────────────────────────────────┐
│  React SPA                              │
│  ┌───────────┐  ┌────────────────────┐  │
│  │ 티켓 보드  │←→│ React Flow 다이어그램│  │
│  └───────────┘  └────────────────────┘  │
│         ↕ 선택 시 양방향 하이라이트        │
└─────────────────┬───────────────────────┘
                  │ REST / SSE
┌─────────────────▼───────────────────────┐
│  FastAPI                                │
│  ├─ /projects   생성·조회               │
│  ├─ /tickets    상태 변경               │
│  ├─ /reviews    재점검 세션             │
│  └─ /graph      LangGraph 실행 (SSE)    │
│                                         │
│  APScheduler                            │
│  └─ 지연 감지 → events 기록 → 알람 큐    │
└─────────────────┬───────────────────────┘
                  │
    ┌─────────────┴──────────────┐
    ▼                            ▼
┌─────────┐              ┌──────────────┐
│Supabase │              │ LangGraph    │
│Postgres │              │ (Claude API) │
└─────────┘              └──────────────┘
```

### 3.3 생성 그래프 (Plan Graph)

```
intake
  │  목표 텍스트 + 제약(기간/주당 가용시간/수준/도구) 파싱 + 도메인 추정 (§1.5)
  ▼
interview ──────────► [사용자 응답 대기]
  │  1라운드: 고정 질문 (LLM 미개입). 청사진 → 완료 기준 → 현재 위치 → 기한.
  │           + 추측으로 채운 가용시간이 있으면 같이 묻는다. 라운드당 최대 5개.
  │  2라운드: LLM 이 1라운드 답을 읽고 아직 모르는 것만 되묻는다 (최대 3개).
  │           더 물을 게 없으면 통과. 라운드 상한은 2다.
  │  답변 원문은 projects.interview 에 남고 decompose 프롬프트로 들어간다.
  ▼
blueprint ──────────► [사용자 확정 대기]
  │  「무엇이 되면 끝났다고 할 수 있나」의 답을 검증 가능한 기준 3~6개로 끊는다.
  │  ⚠ AI 는 **초안만** 쓴다. 고치고 지우고 더하고 확정하는 것은 사용자다.
  │     도메인도 여기서 사용자가 확정한다 (§1.5).
  │     확정 전에는 계획을 만들지 않는다. 무엇이 「끝」인지는 목표를 가진 사람만
  │     정할 수 있고, AI 가 정하면 그 뒤의 계획 전체가 남의 목표가 된다.
  │  인터뷰를 전부 건너뛰었으면 빈 초안을 내민다 (기준을 지어내지 않는다).
  ▼
decompose
  │  주 → 태스크 → 티켓. 주는 covers 로 자기가 끝내는 완성 기준을 가리킨다.
  ▼
architect
  │  컴포넌트 노드 + 엣지 생성
  ▼
link
  │  티켓 ↔ 노드 매핑
  ▼
critic ──── 실패 ────► decompose (최대 3회 재시도)
  │  검증 항목:
  │   - 티켓 예상 소요 ≤ 120분
  │   - 의존성 순환 없음
  │   - 주간 티켓 합계 ≤ 가용시간
  │   - 고아 노드 없음 (모든 노드에 티켓 1개 이상)
  │   - 청사진 커버리지: 모든 완성 기준을 맡는 주가 있다 (집합 연산, LLM 미개입)
  │   - 티켓 본문: 완료 조건 2개 이상, 확인할 수 있는 말로 쓰였다 (§2.2)
  ▼
emit
     DB 저장 + SSE 스트리밍 반환
```

| 노드 | 입력 | 출력 |
|---|---|---|
| `intake` | 자연어 목표 | 구조화된 제약 객체 |
| `interview` | 제약 객체 + 지금까지의 문답 | 이번 라운드 질문 (없으면 통과) + 문답 전문 |
| `blueprint` | 문답 전문 | 완성 기준 **초안** `[{key, text}]` + 완성된 모습 한 문장. 사용자가 확정해야 통과 |
| `decompose` | 제약 객체 | 주/태스크/티켓 트리 |
| `architect` | 제약 + 주·태스크 | 노드·엣지 그래프 |
| `link` | 티켓 + 노드 | 매핑 테이블 |
| `critic` | 전체 | `{ok: bool, violations: []}` |
| `emit` | 검증 통과 결과 | DB 저장 |

> `critic`이 이 그래프의 존재 이유다. **"유동적으로 그린다"는 것은 검증 후 다시 그린다는 뜻**이고, 검증이 없으면 LLM을 한 번 호출한 것과 다르지 않다.

### 3.4 재설계 그래프 (Replan Graph)

재점검일에 실행. 생성 그래프의 부분 재사용.

```
collect_signals
  │  events 집계 (AI 미개입, 순수 SQL)
  │  → 지연 횟수, 완료율, 막힘 사유 텍스트
  ▼
diagnose
  │  지식부족 / 범위과다 / 의존성누락 / 외부요인
  ▼
replan_scope
  │  대상 주 1개로 범위 제한 (R3)
  ▼
decompose (부분)  ← 생성 그래프와 동일 노드 재사용
  ▼
critic            ← 동일
  ▼
diff
     변경 전/후 비교 객체 생성 → 사용자 승인 대기
```

### 3.5 API 개요

| Method | Path | 설명 |
|---|---|---|
| POST | `/projects` | 목표 입력 → 생성 그래프 시작 |
| GET | `/projects/{id}/stream` | SSE, 그래프 진행 상황 스트리밍 |
| POST | `/projects/{id}/clarify` | 인터뷰 답변 제출 (메모리에 실행이 없어도 받는다) |
| POST | `/projects/{id}/blueprint` | 완성 기준 + 도메인 확정 (사용자가 고쳐 쓴 것이 기준이 된다) |
| GET | `/projects/{id}` | 로드맵 + 아키텍처 전체 조회 |
| PATCH | `/tickets/{id}` | 상태 변경 (완료/연기/차단) |
| POST | `/tickets/{id}/block` | 막힘 사유 입력 |
| GET | `/projects/{id}/alerts` | 미확인 알람 목록 |
| POST | `/reviews/{id}/run` | 재설계 그래프 실행 |
| POST | `/reviews/{id}/apply` | diff 항목별 승인/거절 |
| GET | `/projects/{id}/export` | Markdown / JSON 내보내기 |

### 3.6 스케줄러 작업

| 시각 | 작업 |
|---|---|
| 매일 00:10 | 마감 경과 티켓 → `missed` 이벤트 기록 |
| 매일 00:20 | 노드별 지연 집계 → 임계 초과 시 `review_days` 생성 |
| 매일 09:00 | 알람 발송 (웹푸시 / 이메일) |
| 매주 일 20:00 | 주간 완료율 집계 → 주간 리뷰 알람 |

알람 채널은 v1에서 **웹푸시 + 이메일**만. 슬랙 연동은 확장 항목.

---

## §4. 데이터 모델

### 4.1 테이블 목록

| 테이블 | 역할 |
|---|---|
| `projects` | 목표 + 제약 |
| `weekly_goals` | 주 (관리 단위이자 최상위) |
| `tasks` | 태스크 — 한 덩어리로 묶이는 티켓들의 집 |
| `tickets` | 실행 단위 |
| `ticket_dependencies` | 선행 관계 |
| `arch_nodes` | 아키텍처 컴포넌트 |
| `arch_edges` | 컴포넌트 간 관계 |
| `ticket_node_links` | 티켓 ↔ 노드 매핑 (N:M) |
| `events` | **모든 실패 감지의 원천** |
| `review_days` | 재점검일 |
| `replan_sessions` | 재설계 이력 + diff |

### 4.2 스키마

실제 DDL은 `supabase/migrations/0001_init.sql` 에 있다. 이 절과 마이그레이션이 어긋나면 마이그레이션이 기준이다.

```sql
create table projects (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid references auth.users(id),
  title         text not null,
  goal_text     text not null,          -- 원문 목표
  constraints   jsonb not null,         -- {duration_weeks, hours_per_week, level, stack[], team_size}
  interview     jsonb not null default '[]',  -- §3.3 문답 전문 [{round, field, question, answer}]
  blueprint     jsonb not null default '{}',  -- §3.3 {summary, criteria:[{key, text}], confirmed}
  domain        text not null default 'software',  -- §1.5 software | game | general
  status        text default 'active',  -- active | paused | done | abandoned
  created_at    timestamptz default now()
);

create table milestones (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid references projects(id) on delete cascade,
  order_index   int not null,
  title         text not null,
  description   text,
  target_date   date,
  status        text default 'pending'  -- pending | in_progress | done
);

create table weekly_goals (
  id            uuid primary key default gen_random_uuid(),
  milestone_id  uuid references milestones(id) on delete cascade,
  week_index    int not null,           -- 프로젝트 시작 기준 주차
  title         text not null,
  target_date   date
);

create table tickets (
  id             uuid primary key default gen_random_uuid(),
  weekly_goal_id uuid references weekly_goals(id) on delete cascade,
  project_id     uuid references projects(id) on delete cascade,  -- 집계용 비정규화
  order_index    int not null,
  title          text not null,
  body           text,                  -- 무엇을 / 완료조건 / 참고
  est_minutes    int not null check (est_minutes <= 120),  -- R1을 DB가 강제
  status         text default 'todo',   -- todo | doing | done | blocked
  due_date       date,
  delay_count    int default 0,         -- 재점검 트리거 입력값
  blocked_reason text,
  created_at     timestamptz default now(),
  completed_at   timestamptz
);

create table ticket_dependencies (
  ticket_id     uuid references tickets(id) on delete cascade,
  depends_on    uuid references tickets(id) on delete cascade,
  primary key (ticket_id, depends_on)
);

create table arch_nodes (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid references projects(id) on delete cascade,
  node_key      text not null,          -- 'auth', 'netcode', 'db' 등 안정 식별자
  label         text not null,
  node_type     text,                   -- 도메인 프리셋에 따라 (§1.5)
  layer         text,                   -- 도메인 프리셋에 따라 (§1.5)
  position      jsonb,                  -- React Flow 좌표 {x, y}
  status        text default 'pending', -- pending | in_progress | done | at_risk
  unique (project_id, node_key)
);

create table arch_edges (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid references projects(id) on delete cascade,
  from_node     uuid references arch_nodes(id) on delete cascade,
  to_node       uuid references arch_nodes(id) on delete cascade,
  label         text
);

create table ticket_node_links (
  ticket_id     uuid references tickets(id) on delete cascade,
  node_id       uuid references arch_nodes(id) on delete cascade,
  primary key (ticket_id, node_id)
);

create table events (
  id            bigserial primary key,
  project_id    uuid references projects(id) on delete cascade,
  ticket_id     uuid references tickets(id) on delete set null,
  node_id       uuid references arch_nodes(id) on delete set null,  -- 집계 최적화
  type          text not null,          -- created|started|completed|missed|deferred|blocked
  payload       jsonb,
  created_at    timestamptz default now()
);
create index on events (project_id, node_id, type, created_at);

create table review_days (
  id             uuid primary key default gen_random_uuid(),
  project_id     uuid references projects(id) on delete cascade,
  node_id        uuid references arch_nodes(id),
  scheduled_date date not null,
  trigger_reason text,                  -- '동일 노드 지연 3건'
  status         text default 'scheduled' -- scheduled | done | postponed
);

create table replan_sessions (
  id                 uuid primary key default gen_random_uuid(),
  review_day_id      uuid references review_days(id),
  project_id         uuid references projects(id) on delete cascade,
  diagnosis          text,              -- 지식부족 | 범위과다 | 의존성누락 | 외부요인
  scope_milestone_id uuid references milestones(id),
  diff_json          jsonb not null,    -- 변경 전/후
  applied            boolean default false,
  created_at         timestamptz default now()
);
```

### 4.3 티켓 상태 전이

```
todo ──start──► doing ──complete──► done
  │               │
  │               └──block──► blocked ──unblock──► doing
  │
  └──due 경과(스케줄러)──► delay_count += 1, missed 이벤트 기록
                            (status는 유지)
```

`missed`는 상태가 아니라 이벤트다 (R4). 티켓은 여전히 `todo`이고 지연 횟수만 누적된다. 상태와 실패 기록을 분리해야 "몇 번 미뤘는가"를 잃지 않는다.

### 4.4 노드 상태 계산

```sql
select
  n.id,
  count(*) filter (where t.status = 'done')::float / nullif(count(*), 0) as progress,
  count(*) filter (where t.delay_count >= 1) as delayed_tickets
from arch_nodes n
join ticket_node_links l on l.node_id = n.id
join tickets t on t.id = l.ticket_id
where n.project_id = $1
group by n.id;
```

| progress | delayed_tickets | status |
|---|---|---|
| — | ≥ 2 | `at_risk` (최우선) |
| 1.0 | < 2 | `done` |
| 0 < p < 1 | < 2 | `in_progress` |
| 0 | < 2 | `pending` |

### 4.5 재점검 트리거 쿼리

```sql
-- 동일 노드에서 지연 2건 이상 & 미해결 재점검일 없음
select e.node_id, count(*) as delays
from events e
where e.project_id = $1
  and e.type in ('missed', 'deferred')
  and e.created_at > now() - interval '14 days'
group by e.node_id
having count(*) >= 2;
```

**AI는 이 판단에 개입하지 않는다** (R2). 재점검일 생성은 순수 SQL 집계 결과다. AI는 그 이후 "왜 막혔는지"를 진단하는 단계에서만 등장한다. 이 분리가 제품이 신뢰를 얻는 방식이다.

---

## §5. 화면 설계

| 화면 | 구성 | 비고 |
|---|---|---|
| 목표 입력 | 자연어 입력 → **인터뷰**(라운드마다 문답, 원문 보존) → **완성 기준 확정**(사용자가 고쳐 쓴다) → 생성 진행 스트리밍 | SSE로 단계별 표시. 첫 질문은 청사진 |
| 메인 (2분할) | 좌: 티켓 보드(「오늘」·「전체」 탭) / 우: React Flow 다이어그램 | **선택 시 양방향 하이라이트** |
| └ 오늘 | 지금 손댈 수 있는 티켓 + 하루 몫 / 막힌 것 / 선행 대기 | 기본 탭. 규칙은 `frontend/src/today.ts` |
| └ 전체 | 주 > 태스크 > 티켓 (§2.1) | |
| 티켓 상세 | 본문(마크다운), 완료조건 체크, 선행 티켓, 연결 노드 | 복사 버튼 = 에이전트 프롬프트 |
| 알람 | 미확인 알람 목록, 막힘 사유 한 줄 입력 | 톤은 R5 |
| 재점검 세션 | ① 집계 숫자 ② 진단 ③ diff 좌우 비교 ④ 항목별 승인 | 데모 하이라이트 |

메인 화면의 양방향 하이라이트가 제품 인상을 결정한다. 티켓을 클릭하면 해당 노드가 빛나고, 노드를 클릭하면 관련 티켓만 필터된다.

「오늘」 탭은 `due_date` 로 거르지 않는다. 티켓의 `due_date` 는 주차 목표의
`target_date` 를 물려받아 주 경계에 뭉쳐 있어서, `due_date == 오늘` 로 필터하면
어떤 날은 0건이고 어떤 날은 하루치를 넘긴다. 대신 **지금 실제로 손댈 수 있는가**
로 고른다 — 막힌 것(`blocked`)과 선행이 안 끝난 것을 오늘 몫에서 빼고 따로 보여준다.
마감이 지났어도 손댈 수 없으면 오늘 할 일이 아니다. 그건 재점검(§2.4) 대상이다.
하루 몫은 `hours_per_week / 5`, 밀린 것은 몫을 넘겨도 전부 표시한다.

---

## §6. 개발 로드맵

### 6.1 일정

| 일차 | 날짜 | 작업 | 완료 기준 |
|---|---|---|---|
| D1 | 09-07 | Supabase 스키마 + FastAPI 뼈대 | 테이블 생성, `/projects` POST 동작 |
| D2 | 09-08 | 생성 그래프 (intake→emit) | 목표 텍스트 → DB에 트리 저장 |
| D3 | 09-09 | `critic` 루프 + 2시간 규칙 | 위반 시 재분할 실제 동작 |
| D4 | 09-10 | React 기본 화면 + 티켓 보드 | 티켓 조회·완료 체크 |
| D5 | 09-11 | React Flow 다이어그램 | 노드·엣지 렌더링 |
| D6 | 09-12 | **노드 채워지는 연동** | 티켓 완료 → 노드 상태 변화 |
| D7 | 09-13 | 이벤트 기록 + 스케줄러 + 백필 스크립트 | `missed` 자동 기록 |
| D8 | 09-14 | 알람 + 재점검일 생성 | 임계 초과 시 재점검일 등장 |
| D9 | 09-15 | 재설계 그래프 + diff 승인 UI | 재설계 1회 완주 |
| D10 | 09-16 | **실제 프로젝트 투입** | 본인 프로젝트로 시드 |
| D11 | 09-17 | UI 정리 + 배포 | 공개 URL 동작 |
| D12 | 09-18 | **접수 마감** · 제출물 초안 | 접수 완료 |
| D13 | 09-19 | 데모 영상 촬영·편집 | 3분 영상 |
| D14 | 09-20 | **과제 제출** | — |

### 6.2 D10이 중요한 이유

신규 계정으로는 **생성 화면밖에 못 보여준다.** 차별점인 실패 감지·재점검은 데이터가 쌓여야 존재한다.

D10에 진행 중인 실제 프로젝트를 넣고 과거 진행 이력을 실제 날짜로 백필한다. 그러면 ① 데모가 진짜 데이터로 찍히고 ② 알람·재점검이 쓸 만한지 본인이 검증되고 ③ 공모전 이후에도 계속 쓸지가 판명된다.

백필 스크립트는 D7에 미리 작성해둔다.

### 6.3 데모 영상 구성 (3분)

| 구간 | 시간 | 내용 |
|---|---|---|
| 문제 제기 | 0:00–0:25 | 계획은 만들기 쉽지만 지켜지지 않는다 |
| 생성 | 0:25–1:00 | 목표 입력 → 로드맵 + 아키텍처 동시 생성 |
| 연동 | 1:00–1:30 | 티켓 완료 → 노드 채워짐 |
| **실패 감지** | 1:30–2:10 | at_risk 노드 등장 → 알람 → 재점검일 |
| **재설계** | 2:10–2:45 | 진단 → 부분 재설계 → diff 승인 → 다이어그램 변화 |
| 확장 | 2:45–3:00 | 실패 데이터 → 교육기관 대시보드 (1장) |

1:30 이후가 이 제품의 전부다. 앞부분에 시간을 쓰지 않는다.

### 6.4 심사기준 대응

예선: 심사위원 80% + 온라인 투표 20%

| 예선 기준 | 대응 |
|---|---|
| 기획력 | 문제를 "계획 생성"이 아니라 "계획 붕괴"로 정의한 것 |
| 실현 가능성 | 13일 안에 동작하는 배포본. 기존 경험 스택으로 구성 |
| 확장성 | 실패 지점 데이터 → 교육기관/사내 온보딩 B2B (§7) |
| AI 활용의 적절성 | **감지는 SQL, 진단·재설계만 AI.** 근거가 검증 가능한 숫자 |

마지막 항목이 핵심 방어선이다. "AI가 알아서 판단한다"는 제품은 신뢰를 얻지 못하는데, 이 구조는 판단의 입력이 사용자의 실제 기록이다.

본선(10-07 발표 / 10-17 데모데이) 기준은 기획력·확장성·기술력·발표 전달력.

### 6.5 리스크

| 리스크 | 대응 |
|---|---|
| React Flow 학습 시간 초과 | D5에 안 되면 Mermaid 정적 렌더로 폴백 |
| LLM 티켓 분해 품질 편차 | `critic` 재시도 3회 + 도메인 템플릿 3종 하드코딩 |
| 재설계 결과가 부자연스러움 | 범위를 주 1개로 제한, diff 승인 필수 |
| D10 시드 데이터 부족 | 백필 스크립트를 D7에 미리 작성 |

---

## §7. 사업성 검토

공모전 출품작으로서의 판단과 사업으로서의 판단은 분리한다.

### 7.1 결론

개인 대상 B2C로는 구조적으로 어렵다. 돈이 되는 지점은 개인이 아니라 **"사람들이 어디서 막히는지 데이터를 필요로 하는 쪽"** 이다.

### 7.2 B2C의 급소

**① 리텐션 역설**

타겟이 "기획을 못 하는 입문자"인데, 그 사람은 정확히 계획을 안 지키는 사람이다.

```
미완료 → 알람 → 죄책감 → 앱 삭제
```

습관앱·할일앱·다이어트앱이 전부 이 곡선에서 죽었다. **알람을 정교하게 만들수록 이탈이 빨라지는 구조**라 기능 개선이 지표 개선으로 이어지지 않는다. R5(진단 톤), 재점검일 프레이밍, 무활동 3일 질문화로 완화는 되지만 해소는 안 된다.

**② 핵심 가치가 리텐션 뒤에 있다**

| 기능 | 가치 발생 시점 | 가치 크기 |
|---|---|---|
| 로드맵·아키텍처 생성 | 즉시 | 낮음 (LLM 대체 가능) |
| 실패 감지·재설계 | 3~4주 뒤 | 높음 |

대부분 2주 안에 이탈한다. 차별점을 경험하기 전에 나가는 순서다. 온보딩으로 고칠 수 있는 문제가 아니다.

**③ 코딩 에이전트가 이 자리를 흡수 중**

"기획의 벽"은 Claude Code / Cursor의 plan mode가 이미 먹어 들어가고 있다. 대응 각도는 **상위 레이어 포지셔닝**이다 — 에이전트의 plan mode는 세션 단위, 이 제품은 프로젝트 전 기간의 궤적. 티켓을 에이전트 프롬프트 단위로 설계한 것도 그래서다.

### 7.3 B2B 확장 경로

**부트캠프 · 교육기관 · 사내 온보딩**

| 항목 | 내용 |
|---|---|
| 결제 주체 | 수강생이 아니라 **운영자** → 개인 리텐션에 안 걸림 |
| 운영자가 원하는 것 | "우리 커리큘럼에서 몇 기수째 몇 %가 3주차에서 막히는가" |
| 데이터 자산 | 실패 지점이 쌓일수록 로드맵 품질 상승 → **유일한 해자** |
| 이탈의 의미 | B2C에선 손실, B2B에선 커리큘럼 문제를 알려주는 데이터 |

제품 형태 차이: 개인용은 목표→로드맵 생성. 기관용은 **커리큘럼을 템플릿으로 등록 → 수강생별 개인화 인스턴스 → 집계 대시보드**. 집계 대시보드가 실제 판매 대상이고, 개인용 화면은 데이터 수집 창구다.

**콜드스타트 리스크**: 데이터가 없으면 LLM 래퍼고, 데이터는 사용자가 있어야 쌓인다. 초기엔 한 기관과 붙어 파일럿으로 채우는 것 외에 방법이 없다.

### 7.4 검증 계획 (공모전 이후 2주)

| 질문 | 검증 방법 |
|---|---|
| 만든 본인이 계속 쓰는가 | 2주 뒤 접속 로그 |
| 재설계 제안이 쓸 만한가 | 승인율 |
| 알람이 소음인가 신호인가 | 알람 후 24시간 내 행동 전환율 |

본인이 2주 뒤에 안 연다면 그 시점에 접는다. 지금 결론 낼 필요는 없다.
