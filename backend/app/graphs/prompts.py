"""생성 그래프 프롬프트 (SPEC §3.3).

프롬프트가 지키게 하는 것과 critic 이 검증하는 것이 같은 목록이어야 한다.
프롬프트만 고치고 critic 을 안 고치면 규칙이 두 벌이 된다.
"""

from app.models.schemas import MAX_TICKET_MINUTES, Constraints, CriticResult, PlanDraft

SYSTEM = f"""너는 프로젝트 로드맵 설계자다. 목표를 실행 가능한 단위로 분해하고
동시에 시스템 아키텍처를 그린다.

지켜야 할 규칙:
- 티켓 하나의 예상 소요는 반드시 {MAX_TICKET_MINUTES}분 이내다. 넘으면 실패다.
  "인증 구현", "DB 설계" 같은 덩어리는 티켓이 아니다. 그런 건 4~6개로 쪼개라.
- 완료 조건은 검증 가능해야 한다. "잘 동작한다" 는 안 되고,
  "테스트 3개 통과", "빌드 성공", "응답 200" 은 된다.
- 티켓 본문은 코딩 에이전트에 그대로 붙여넣을 수 있어야 한다.
- 한국어로 쓴다. 사용자가 입력한 목표의 도메인 용어는 그대로 살린다.
"""


INTAKE = """다음 목표에서 프로젝트 제약을 읽어내라.

목표:
{goal_text}

사용자가 이미 알려준 값(있으면 그대로 쓴다):
{known}

- title: 목표를 20자 이내로 줄인 프로젝트 이름
- duration_weeks / hours_per_week / level / stack / team_size 를 채운다.
- 목표 문장에서 근거를 찾을 수 없어 추측으로 채운 필드 이름을 missing 에 넣는다.
  근거가 있어서 확신하는 필드는 missing 에 넣지 마라.
"""


CLARIFY = """아래 필드는 목표 문장만으로는 확신할 수 없어 추측으로 채웠다.

추측으로 채운 필드: {missing}
현재 값: {constraints}

사용자에게 물어볼 질문을 만들어라.
- 최대 5개. 추측한 필드에 대해서만 묻는다.
- 한 문장으로, 답하기 쉽게. 현재 추측값을 괄호로 같이 보여준다.
- 예: "주당 몇 시간 정도 쓸 수 있나요? (지금은 10시간으로 잡아뒀어요)"
"""


DECOMPOSE = """목표를 마일스톤 -> 주차별 목표 -> 티켓으로 분해하라.

목표:
{goal_text}

제약:
- 기간 {duration_weeks}주, 주당 {hours_per_week}시간 (= 주당 {capacity}분)
- 수준: {level}
- 스택: {stack}
- 인원: {team_size}명

구조:
- 마일스톤 3~6개. 사람에게 보여주는 단위다. key 는 m1, m2 ... 로 매긴다.
- 마일스톤당 주차별 목표 2~4개. week_index 는 1부터 시작하고 {duration_weeks} 를 넘지 않는다.
  key 는 w1, w2 ... 로 매긴다.
- 티켓은 실행 단위다. key 는 t1, t2 ... 로 매긴다.
  * est_minutes 는 {max_min} 이하. 예외 없다.
  * 한 주차에 배정된 티켓의 est_minutes 합계가 {capacity} 분을 넘으면 안 된다.
  * depends_on 에는 먼저 끝나야 하는 티켓의 key 를 넣는다. 순환하면 안 된다.
    앞 주차 -> 뒤 주차 방향으로만 의존한다.

티켓 body 는 이 마크다운 형식을 그대로 쓴다:

## 무엇을
(한 문장 목표)

## 완료 조건
- [ ] 검증 가능한 조건
- [ ] 검증 가능한 조건

## 참고
- (필요하면 명령어, 파일 경로, 참고 링크)
"""


DECOMPOSE_RETRY = """방금 낸 분해가 검증에서 걸렸다. 아래 위반을 고쳐서 다시 내라.

위반:
{violations}

이전 분해(마일스톤 {n_ms}개 / 주차 {n_wg}개 / 티켓 {n_tk}개):
{previous}

고칠 때 지킬 것:
- 걸린 부분만 고친다. 통과한 부분의 key 와 내용은 그대로 유지한다.
- 티켓을 쪼갤 때는 원래 key 를 유지한 채 새 key 를 추가한다 (t7 -> t7, t7b, t7c).
- 주간 합계가 넘쳤으면 티켓을 뒤 주차로 옮기거나 범위를 줄인다.
"""


ARCHITECT = """이 프로젝트가 만들 시스템의 아키텍처를 그려라.

목표: {goal_text}
스택: {stack}

마일스톤:
{milestones}

- 노드 6~15개. node_key 는 'auth', 'netcode', 'db' 처럼 영문 소문자 안정 식별자다.
  나중에 이 key 로 티켓과 연결되므로 재생성해도 같은 컴포넌트는 같은 key 여야 한다.
- label 은 사람이 읽는 이름(한국어 가능).
- node_type: service | store | client | external
- layer: frontend | backend | data | infra
- 엣지는 실제 호출/의존 방향으로 긋는다. label 에 무엇이 오가는지 짧게 적는다.
- 이 로드맵의 티켓으로 만들어지지 않는 컴포넌트는 넣지 마라.
  붙을 티켓이 없는 노드는 검증에서 걸린다.
"""


LINK = """티켓을 아키텍처 노드에 연결하라.

노드:
{nodes}

티켓:
{tickets}

- 모든 티켓은 최소 1개 노드에 연결된다. 티켓 완료가 노드를 채우는 게 이 제품의 핵심이다.
- 모든 노드는 최소 1개 티켓을 받는다. 티켓이 없는 노드는 만들어지지 않는 컴포넌트다.
- 한 티켓이 여러 노드에 걸치면 여러 줄을 낸다. 다만 3개를 넘기지는 마라
  — 어디서 막혔는지 특정하는 게 목적인데 다 걸치면 특정이 안 된다.
"""


def format_violations(result: CriticResult) -> str:
    return "\n".join(f"- [{v.code}] {v.message}" for v in result.violations)


def format_previous(draft: PlanDraft) -> str:
    lines: list[str] = []
    goal_by_key = {g.key: g for g in draft.weekly_goals}
    for m in sorted(draft.milestones, key=lambda x: x.order_index):
        lines.append(f"{m.key} [마일스톤] {m.title}")
        goals = [g for g in draft.weekly_goals if g.milestone_key == m.key]
        for g in sorted(goals, key=lambda x: x.week_index):
            lines.append(f"  {g.key} [{g.week_index}주차] {g.title}")
            tickets = [t for t in draft.tickets if t.weekly_goal_key == g.key]
            for t in sorted(tickets, key=lambda x: x.order_index):
                deps = f" <- {','.join(t.depends_on)}" if t.depends_on else ""
                lines.append(f"    {t.key} ({t.est_minutes}분) {t.title}{deps}")
    milestone_keys = {m.key for m in draft.milestones}
    orphan_goals = [g for g in draft.weekly_goals if g.milestone_key not in milestone_keys]
    for g in orphan_goals:
        lines.append(f"  {g.key} [{g.week_index}주차, 마일스톤 없음] {g.title}")
    orphan_tickets = [t for t in draft.tickets if t.weekly_goal_key not in goal_by_key]
    for t in orphan_tickets:
        lines.append(f"    {t.key} ({t.est_minutes}분, 주차 없음) {t.title}")
    return "\n".join(lines)


def decompose_prompt(goal_text: str, c: Constraints) -> str:
    return DECOMPOSE.format(
        goal_text=goal_text,
        duration_weeks=c.duration_weeks,
        hours_per_week=c.hours_per_week,
        capacity=c.weekly_capacity_minutes,
        level=c.level,
        stack=", ".join(c.stack) or "미정",
        team_size=c.team_size,
        max_min=MAX_TICKET_MINUTES,
    )


# ─────────────────────────────────────────────────────────────
# 재설계 그래프 (SPEC §3.4)
# ─────────────────────────────────────────────────────────────
DIAGNOSE = """아래는 한 아키텍처 컴포넌트에서 반복해 막힌 기록이다.
왜 막혔는지 진단하라.

컴포넌트: {node_label} ({node_key})

숫자 (전부 사용자의 실제 기록이다):
- 이 컴포넌트에 걸린 티켓 {total}개 중 {done}개 완료, {delayed}개 지연
- 마감 놓침 {missed}회, 사용자가 직접 미룬 것 {deferred}회
- 평균 지연 {avg_delay}일

사용자가 직접 적은 막힘 사유:
{blocked}

진단은 넷 중 하나다:
- 지식부족: 무엇을 해야 하는지는 알지만 방법을 모른다
- 범위과다: 티켓이 여전히 크거나 목표 자체가 크다
- 의존성누락: 먼저 끝냈어야 할 게 있는데 순서가 잘못됐다
- 외부요인: 계획 문제가 아니다 (외부 일정, 대기, 개인 사정)

rationale 은 위 숫자를 근거로 두 문장 이내로 쓴다. 사용자를 책망하지 않는다.
"""


PRESCRIPTION = {
    "지식부족": (
        "선행 학습 티켓을 삽입한다 (add_ticket). 막힌 티켓보다 앞에 두고, "
        "body 의 참고 항목에 무엇을 읽고 무엇을 만들어보면 되는지 적는다. "
        "막힌 티켓 자체는 건드리지 않는다."
    ),
    "범위과다": (
        "티켓을 다시 쪼개거나(split_ticket) 목표 범위를 줄인다"
        "(reduce_ticket / drop_ticket). 이번에 꼭 필요하지 않은 건 drop 한다."
    ),
    "의존성누락": (
        "빠진 선행 티켓을 추가하고(add_ticket) 순서를 잡는다(add_dependency). "
        "티켓 내용을 바꾸지는 않는다."
    ),
    "외부요인": (
        "계획은 그대로 두고 일정만 이월한다(shift_milestone). "
        "티켓을 쪼개거나 지우지 않는다."
    ),
}


REPLAN = """재점검 세션이다. 막힌 구간만 다시 설계하라.

진단: {diagnosis}
근거: {rationale}

처방:
{prescription}

범위는 마일스톤 「{milestone_title}」 하나다. 이 밖은 손대지 않는다.
전체를 다시 그리면 사용자가 자기 계획이라고 느끼지 않는다.

현재 이 마일스톤의 티켓:
{tickets}

제약: 주당 {hours_per_week}시간 (= {capacity}분), 티켓 하나는 {max_min}분 이내.

낼 것:
- 변경 3~8건. 처방에 맞는 종류만 쓴다.
- target_ref / depends_on_ref 에는 위 목록의 T번호를 그대로 쓴다.
- 쓰지 않는 필드는 빈 문자열이나 0 으로 둔다.
- 완료된(done) 티켓은 건드리지 않는다. 이미 한 일을 되돌리는 제안은 하지 않는다.
- 각 변경의 reason 은 위 숫자나 막힘 사유를 근거로 한 문장.
"""


REPLAN_RETRY = """방금 낸 제안을 적용해봤더니 검증에서 걸렸다. 고쳐서 다시 내라.

위반:
{violations}

- 걸린 항목만 바꾼다.
- 티켓을 쪼갤 때 각 조각은 {max_min}분 이내여야 한다.
- 주차별 합계가 가용시간을 넘으면 티켓을 줄이거나 뒤로 미뤄라.
"""


def format_scope_tickets(rows: list[dict]) -> str:
    """T1, T2 ... 참조가 붙은 티켓 목록. LLM 은 uuid 대신 이 참조를 쓴다."""
    lines = []
    for row in rows:
        deps = f" <- {','.join(row['depends_on_refs'])}" if row["depends_on_refs"] else ""
        delay = f" 지연 {row['delay_count']}회" if row["delay_count"] else ""
        blocked = f" 막힘: {row['blocked_reason']}" if row.get("blocked_reason") else ""
        lines.append(
            f"{row['ref']} [{row['week_index']}주차] {row['title']} "
            f"({row['est_minutes']}분, {row['status']}){delay}{deps}{blocked}"
        )
    return "\n".join(lines)
