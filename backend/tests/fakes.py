"""가짜 Planner. API 키 없이 생성 그래프 전체를 돌린다."""

from typing import Any

from pydantic import BaseModel

from app.models.schemas import (
    ArchitectResult,
    BlueprintResult,
    ClarifyQuestion,
    ClarifyResult,
    Constraints,
    DecomposeResult,
    DraftEdge,
    DraftLink,
    DraftTask,
    DraftNode,
    DraftTicket,
    DraftWeeklyGoal,
    IntakeResult,
    LinkResult,
    SuccessCriterion,
)


BLUEPRINT = BlueprintResult(
    summary="돌아가는 로드맵 도구",
    criteria=[
        SuccessCriterion(key="sc1", text="목표를 넣으면 티켓이 나온다"),
        SuccessCriterion(key="sc2", text="티켓을 끝내면 다이어그램이 채워진다"),
    ],
)


def make_decompose(
    est_minutes: int = 90, n_tickets: int = 4, covers: list[list[str]] | None = None
) -> DecomposeResult:
    covered = covers or [["sc1"], ["sc2"]]
    return DecomposeResult(
        weekly_goals=[
            DraftWeeklyGoal(key="w1", week_index=1, title="1주 - 기반", covers=covered[0]),
            DraftWeeklyGoal(key="w2", week_index=2, title="2주 - 연결", covers=covered[1]),
        ],
        tasks=[
            DraftTask(
                key="k1", weekly_goal_key="w1", task_number=1,
                title="기반", description="첫 동작",
            ),
            DraftTask(
                key="k2", weekly_goal_key="w2", task_number=2,
                title="연결", description="이어 붙인다",
            ),
        ],
        tickets=[
            DraftTicket(
                key=f"t{i}",
                task_key="k1" if i <= n_tickets // 2 else "k2",
                # 번호는 태스크마다 1 부터 다시 센다
                ticket_number=i if i <= n_tickets // 2 else i - n_tickets // 2,
                title=f"티켓 {i}",
                body=(
                    "## 무엇을\n한 문장\n\n"
                    "## 완료 조건\n- [ ] 테스트 3개 통과\n- [ ] 빌드 성공\n"
                ),
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
        followups: list[str] | None = None,
        blueprint: BlueprintResult | None = None,
        domain: str = "software",
        constraints: Constraints | None = None,
        n_tickets: int = 4,
    ) -> None:
        self.decompose_results = decompose_results or [make_decompose(n_tickets=n_tickets)]
        self.missing = missing or []
        # 2라운드 후속 질문. 기본은 「더 물을 것 없음」이다 (1라운드로 끝난다).
        self.followups = followups or []
        self.blueprint = blueprint if blueprint is not None else BLUEPRINT
        self.domain = domain
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
                title="테스트 프로젝트",
                constraints=self.constraints,
                missing=self.missing,
                domain=self.domain,
            )
        if name == "ClarifyResult":
            # 인터뷰 2라운드 — 1라운드 답을 읽고 더 물을 게 있는지 정하는 자리다.
            return ClarifyResult(
                questions=[
                    ClarifyQuestion(field=f, question=f"{f} 알려주세요") for f in self.followups
                ]
            )
        if name == "BlueprintResult":
            return self.blueprint
        if name == "DecomposeResult":
            index = min(self.calls.count("DecomposeResult") - 1, len(self.decompose_results) - 1)
            return self.decompose_results[index]
        if name == "ArchitectResult":
            return ARCHITECT
        if name == "LinkResult":
            return make_links(self.n_tickets)
        raise AssertionError(f"예상하지 못한 출력 모델: {name}")
