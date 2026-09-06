"""도메인 모델. SPEC §2.1 계층 구조 / §4 스키마와 1:1 대응.

LLM 이 만들어내는 초안(Draft*)은 DB uuid 가 아직 없으므로 문자열 `key` 로 서로를 참조한다.
`emit` 단계에서 key -> uuid 로 치환하며 저장한다.
"""

from typing import Literal

from pydantic import BaseModel, Field

Level = Literal["beginner", "intermediate", "advanced"]
NodeType = Literal["service", "store", "client", "external"]
Layer = Literal["frontend", "backend", "data", "infra"]
TicketStatus = Literal["todo", "doing", "done", "blocked"]
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
    """clarify 노드 출력. 최대 5개 (SPEC §3.3)."""

    questions: list[ClarifyQuestion]


# ─────────────────────────────────────────────────────────────
# 초안 트리 (SPEC §2.1)
# ─────────────────────────────────────────────────────────────
class DraftMilestone(BaseModel):
    key: str
    order_index: int
    title: str
    description: str


class DraftWeeklyGoal(BaseModel):
    key: str
    milestone_key: str
    week_index: int = Field(ge=1)
    title: str


class DraftTicket(BaseModel):
    key: str
    weekly_goal_key: str
    order_index: int
    title: str
    # SPEC §2.2 티켓 본문 포맷 — 무엇을 / 완료 조건 / 참고
    body: str
    est_minutes: int
    depends_on: list[str]


class DecomposeResult(BaseModel):
    milestones: list[DraftMilestone]
    weekly_goals: list[DraftWeeklyGoal]
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

    milestones: list[DraftMilestone] = []
    weekly_goals: list[DraftWeeklyGoal] = []
    tickets: list[DraftTicket] = []
    nodes: list[DraftNode] = []
    edges: list[DraftEdge] = []
    links: list[DraftLink] = []


# ─────────────────────────────────────────────────────────────
# critic (SPEC §3.3)
# ─────────────────────────────────────────────────────────────
ViolationCode = Literal[
    "ticket_over_120min",  # R1
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
