"""도메인 모델. SPEC §2.1 계층 구조 / §4 스키마와 1:1 대응.

LLM 이 만들어내는 초안(Draft*)은 DB uuid 가 아직 없으므로 문자열 `key` 로 서로를 참조한다.
`emit` 단계에서 key -> uuid 로 치환하며 저장한다.
"""

from typing import Literal

from pydantic import BaseModel, Field

Level = Literal["beginner", "intermediate", "advanced"]
NodeType = Literal["service", "store", "client", "external"]
Layer = Literal["frontend", "backend", "data", "infra"]
# 태스크와 티켓이 같은 낱말을 쓴다.
# ⚠ 「막힘」은 여기 없다 — parked 는 접힘(의도적으로 미룸)이지 막힘이 아니다.
# 막힘은 상태가 아니라 blocked_reason 한 줄과 blocked 이벤트가 든다.
WorkStatus = Literal["open", "claimed", "resolved", "parked"]
TicketStatus = WorkStatus
TaskStatus = WorkStatus
NodeStatus = Literal["pending", "in_progress", "done", "at_risk"]
EventType = Literal["created", "started", "completed", "missed", "deferred", "blocked"]
Diagnosis = Literal["지식부족", "범위과다", "의존성누락", "외부요인"]

# SPEC R1 — 티켓 1개 = 예상 소요 120분 이내
MAX_TICKET_MINUTES = 120


# ─────────────────────────────────────────────────────────────
# 제약 (SPEC §3.3 intake 출력)
# ─────────────────────────────────────────────────────────────
class Constraints(BaseModel):
    duration_weeks: int = Field(ge=1, le=104)
    hours_per_week: int = Field(ge=1, le=80)
    level: Level
    stack: list[str]
    team_size: int = Field(ge=1)

    @property
    def weekly_capacity_minutes(self) -> int:
        return self.hours_per_week * 60


class IntakeResult(BaseModel):
    """intake 노드 출력. 목표 원문에서 읽어낼 수 없는 필드는 missing 에 담는다."""

    title: str
    constraints: Constraints
    missing: list[str]


class ClarifyQuestion(BaseModel):
    field: str
    question: str


class ClarifyResult(BaseModel):
    """interview 노드 출력. 한 라운드에 최대 5개 (SPEC §3.3)."""

    questions: list[ClarifyQuestion]


class InterviewTurn(BaseModel):
    """인터뷰 문답 하나. 답변 원문이 여기 남아 decompose 프롬프트로 들어간다.

    `answer` 가 빈 문자열이면 아직 답을 못 받은 질문이다 — 그 상태 그대로 DB
    (`projects.interview`)에 저장되므로, 새로고침해도 이어서 답할 수 있다.
    """

    round: int = Field(ge=1)
    field: str
    question: str
    answer: str = ""


# ─────────────────────────────────────────────────────────────
# 완성 청사진 (SPEC §3.3)
# ─────────────────────────────────────────────────────────────
class SuccessCriterion(BaseModel):
    """「무엇이 되면 끝났다고 할 수 있나」 한 줄. 검증 가능해야 한다.

    key 는 sc1, sc2 ... 다. 주(weekly_goal)가 이 key 로 자기가 맡은 기준을 가리키고,
    critic 이 그 대응을 확인한다 (LLM 미개입).
    """

    key: str
    text: str


class Blueprint(BaseModel):
    """인터뷰 답에서 뽑아낸 완성 상태. 계획이 이것을 덮는지 critic 이 본다."""

    summary: str = ""
    criteria: list[SuccessCriterion] = []


class BlueprintResult(Blueprint):
    """blueprint 노드 출력."""


# ─────────────────────────────────────────────────────────────
# 초안 트리 (SPEC §2.1)
# ─────────────────────────────────────────────────────────────
class DraftWeeklyGoal(BaseModel):
    """주 — 관리 단위이자 최상위."""

    key: str
    week_index: int = Field(ge=1)
    title: str
    # 이 주가 맡는 성공 기준 키. 비어 있어도 파싱은 되고, 대신 critic 이 잡는다.
    covers: list[str] = []


class DraftTask(BaseModel):
    """태스크 — 한 덩어리로 묶이는 티켓들의 집. 한 태스크는 한 주에만 산다."""

    key: str
    weekly_goal_key: str
    task_number: int = Field(ge=1)  # 프로젝트 안에서 전역으로 센다
    title: str
    description: str


class DraftTicket(BaseModel):
    key: str
    task_key: str
    ticket_number: int = Field(ge=1)  # 태스크마다 01 부터 다시 센다
    title: str
    # SPEC §2.2 티켓 본문 포맷 — 무엇을 / 완료 조건 / 참고
    body: str
    est_minutes: int
    depends_on: list[str]


class DecomposeResult(BaseModel):
    weekly_goals: list[DraftWeeklyGoal]
    tasks: list[DraftTask]
    tickets: list[DraftTicket]


class DraftNode(BaseModel):
    node_key: str
    label: str
    node_type: NodeType
    layer: Layer


class DraftEdge(BaseModel):
    from_key: str
    to_key: str
    label: str


class ArchitectResult(BaseModel):
    nodes: list[DraftNode]
    edges: list[DraftEdge]


class DraftLink(BaseModel):
    ticket_key: str
    node_key: str


class LinkResult(BaseModel):
    links: list[DraftLink]


class PlanDraft(BaseModel):
    """생성 그래프가 굴리는 계획 초안 전체."""

    blueprint: Blueprint = Blueprint()
    weekly_goals: list[DraftWeeklyGoal] = []
    tasks: list[DraftTask] = []
    tickets: list[DraftTicket] = []
    nodes: list[DraftNode] = []
    edges: list[DraftEdge] = []
    links: list[DraftLink] = []


# ─────────────────────────────────────────────────────────────
# critic (SPEC §3.3)
# ─────────────────────────────────────────────────────────────
ViolationCode = Literal[
    "ticket_over_120min",  # R1
    "uncovered_criterion",  # 청사진의 기준을 어느 주도 맡지 않는다
    "weak_ticket_body",     # 완료 조건이 없거나 확인할 수 없다
    "dependency_cycle",
    "weekly_overload",
    "orphan_node",
    "unlinked_ticket",
    "dangling_reference",
    "duplicate_key",
    "empty_plan",
]


class Violation(BaseModel):
    code: ViolationCode
    message: str
    targets: list[str] = []  # 위반에 관련된 key 목록


class CriticResult(BaseModel):
    ok: bool
    violations: list[Violation]


# ─────────────────────────────────────────────────────────────
# API 입출력
# ─────────────────────────────────────────────────────────────
class GoogleLoginRequest(BaseModel):
    """구글 로그인 버튼이 돌려준 ID 토큰. 서버가 구글에 진짜인지 확인한다."""

    id_token: str = Field(min_length=1)


class ProjectCreateRequest(BaseModel):
    goal_text: str = Field(min_length=5)
    # 사용자가 미리 아는 제약이 있으면 넣는다. 없으면 intake 가 추론하고 clarify 가 묻는다.
    duration_weeks: int | None = None
    hours_per_week: int | None = None
    level: Level | None = None
    stack: list[str] | None = None
    team_size: int | None = None


class ClarifyAnswerRequest(BaseModel):
    answers: dict[str, str]


class TicketPatchRequest(BaseModel):
    """SPEC §4.3 상태 전이. `missed` 는 여기에 없다 — 상태가 아니라 이벤트다 (R4)."""

    action: Literal["start", "complete", "block", "unblock", "defer"]
    reason: str | None = None
    new_due_date: str | None = None  # defer 전용 (ISO date)


# ─────────────────────────────────────────────────────────────
# 재설계 (SPEC §3.4, §2.4)
# ─────────────────────────────────────────────────────────────
class ReplanSignals(BaseModel):
    """collect_signals 출력. 전부 SQL 집계다 — AI 미개입 (R2).

    재점검 세션은 이 숫자를 먼저 보여주고 시작한다 (§2.4 1단계).
    """

    node_key: str
    node_label: str
    total_tickets: int
    done_tickets: int
    delayed_tickets: int
    missed_count: int
    deferred_count: int
    avg_delay_days: float
    blocked_reasons: list[str]


class DiagnoseResult(BaseModel):
    """§2.4 2단계 — 여기서부터 AI 가 등장한다."""

    diagnosis: Diagnosis
    rationale: str


ChangeType = Literal[
    "split_ticket",     # 범위과다 — 티켓 재분할
    "add_ticket",       # 지식부족 — 선행 학습 티켓 삽입 / 의존성누락 — 선행 티켓 추가
    "reduce_ticket",    # 범위과다 — 목표 범위 축소
    "drop_ticket",      # 범위과다 — 이번 범위에서 제외
    "add_dependency",   # 의존성누락 — 순서 교체
    "shift_week",       # 외부요인 — 일정만 이월, 내용 유지
]


class SplitPart(BaseModel):
    title: str
    est_minutes: int


class ProposedChange(BaseModel):
    """LLM 이 내는 제안 한 건. 티켓은 uuid 대신 T1, T2 같은 참조로 가리킨다."""

    type: ChangeType
    target_ref: str      # 대상 티켓 참조 (add_ticket/shift_week 은 빈 문자열)
    depends_on_ref: str  # add_dependency / add_ticket 의 선행 티켓 참조
    reason: str
    title: str           # add_ticket, reduce_ticket
    body: str
    est_minutes: int     # add_ticket, reduce_ticket
    parts: list[SplitPart]  # split_ticket
    shift_days: int      # shift_week


class ReplanProposal(BaseModel):
    changes: list[ProposedChange]


class ReplanChange(BaseModel):
    """diff 한 항목. 사용자는 이 단위로 승인/거절한다 (§2.4 4단계)."""

    id: str
    type: ChangeType
    label: str
    reason: str
    before: str | None = None
    after: str | None = None
    op: dict  # 적용에 필요한 구체 데이터 (uuid 포함)


class ReplanDiff(BaseModel):
    signals: ReplanSignals
    diagnosis: Diagnosis
    rationale: str
    scope_weekly_goal_id: str
    scope_weekly_goal_title: str
    changes: list[ReplanChange]
    residual_violations: list[Violation] = []
    repairs: list[str] = []


class ReplanApplyRequest(BaseModel):
    """항목별 승인. 목록에 없는 항목은 거절로 본다."""

    approved: list[str]
