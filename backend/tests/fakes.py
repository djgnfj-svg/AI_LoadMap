"""가짜 Planner. API 키 없이 생성 그래프 전체를 돌린다."""

from typing import Any

from pydantic import BaseModel

from app.models.schemas import (
    ArchitectResult,
    ClarifyQuestion,
    ClarifyResult,
    Constraints,
    DecomposeResult,
    DraftEdge,
    DraftLink,
    DraftMilestone,
    DraftNode,
    DraftTicket,
    DraftWeeklyGoal,
    IntakeResult,
    LinkResult,
)


def make_decompose(est_minutes: int = 90, n_tickets: int = 4) -> DecomposeResult:
    return DecomposeResult(
        milestones=[
            DraftMilestone(key="m1", order_index=1, title="프로토타입", description="첫 동작")
        ],
        weekly_goals=[
            DraftWeeklyGoal(key="w1", milestone_key="m1", week_index=1, title="1주차 - 기반"),
            DraftWeeklyGoal(key="w2", milestone_key="m1", week_index=2, title="2주차 - 연결"),
        ],
        tickets=[
            DraftTicket(
                key=f"t{i}",
                weekly_goal_key="w1" if i <= n_tickets // 2 else "w2",
                order_index=i,
                title=f"티켓 {i}",
                body="## 무엇을\n한 문장\n\n## 완료 조건\n- [ ] 테스트 통과\n",
                est_minutes=est_minutes,
                depends_on=[f"t{i - 1}"] if i > 1 else [],
            )
            for i in range(1, n_tickets + 1)
        ],
    )


ARCHITECT = ArchitectResult(
    nodes=[
        DraftNode(node_key="api", label="API 서버", node_type="service", layer="backend"),
        DraftNode(node_key="db", label="DB", node_type="store", layer="data"),
    ],
    edges=[DraftEdge(from_key="api", to_key="db", label="쿼리")],
)


def make_links(n_tickets: int = 4) -> LinkResult:
    return LinkResult(
        links=[
            DraftLink(ticket_key=f"t{i}", node_key="api" if i % 2 else "db")
            for i in range(1, n_tickets + 1)
        ]
    )


class FakePlanner:
    """decompose 호출 순서에 따라 미리 정해둔 결과를 돌려준다."""

    def __init__(
        self,
        decompose_results: list[DecomposeResult] | None = None,
        *,
        missing: list[str] | None = None,
        constraints: Constraints | None = None,
        n_tickets: int = 4,
    ) -> None:
        self.decompose_results = decompose_results or [make_decompose(n_tickets=n_tickets)]
        self.missing = missing or []
        self.constraints = constraints or Constraints(
            duration_weeks=4,
            hours_per_week=10,
            level="intermediate",
            stack=["fastapi", "react"],
            team_size=1,
        )
        self.n_tickets = n_tickets
        self.calls: list[str] = []

    async def structured(
        self, *, system: str, prompt: str, output_model: type[BaseModel]
    ) -> Any:
        name = output_model.__name__
        self.calls.append(name)

        if name == "IntakeResult":
            return IntakeResult(
                title="테스트 프로젝트", constraints=self.constraints, missing=self.missing
            )
        if name == "ClarifyResult":
            return ClarifyResult(
                questions=[
                    ClarifyQuestion(field=f, question=f"{f} 알려주세요") for f in self.missing
                ]
            )
        if name == "DecomposeResult":
            index = min(self.calls.count("DecomposeResult") - 1, len(self.decompose_results) - 1)
            return self.decompose_results[index]
        if name == "ArchitectResult":
            return ARCHITECT
        if name == "LinkResult":
            return make_links(self.n_tickets)
        raise AssertionError(f"예상하지 못한 출력 모델: {name}")
