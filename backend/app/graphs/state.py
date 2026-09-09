"""생성 그래프 상태 (SPEC §3.3)."""

from typing import Annotated, TypedDict

from app.models.schemas import (
    ClarifyQuestion,
    Constraints,
    CriticResult,
    InterviewTurn,
    PlanDraft,
)


def _last(_old, new):  # noqa: ANN001
    return new


class PlanState(TypedDict, total=False):
    # 입력
    goal_text: str
    known: dict          # 사용자가 미리 준 제약 (없으면 intake 가 추론)
    clarify_answers: dict[str, str]   # 이번 실행에서 새로 받은 답
    interview: list[InterviewTurn]    # 지금까지의 문답 전문 (DB 에서 실려 온다)

    # intake / interview
    title: str
    constraints: Constraints | None
    missing: list[str]
    clarify_questions: list[ClarifyQuestion]  # 이번에 물을 질문
    awaiting_clarify: bool

    # decompose / architect / link
    draft: PlanDraft

    # critic 루프
    critic: CriticResult | None
    attempt: Annotated[int, _last]
    repairs: list[str]
