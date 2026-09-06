"""생성 그래프 상태 (SPEC §3.3)."""

from typing import Annotated, TypedDict

from app.models.schemas import ClarifyQuestion, Constraints, CriticResult, PlanDraft


def _last(_old, new):  # noqa: ANN001
    return new


class PlanState(TypedDict, total=False):
    # 입력
    goal_text: str
    known: dict          # 사용자가 미리 준 제약 (없으면 intake 가 추론)
    clarify_answers: dict[str, str]

    # intake / clarify
    title: str
    constraints: Constraints | None
    missing: list[str]
    clarify_questions: list[ClarifyQuestion]
    awaiting_clarify: bool

    # decompose / architect / link
    draft: PlanDraft

    # critic 루프
    critic: CriticResult | None
    attempt: Annotated[int, _last]
    repairs: list[str]
