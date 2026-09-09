"""critic 검증 규칙 (SPEC §3.3)."""

import pytest

from app.graphs.critic import run_critic
from app.models.schemas import (
    Blueprint,
    Constraints,
    DraftEdge,
    DraftLink,
    DraftTask,
    DraftNode,
    DraftTicket,
    DraftWeeklyGoal,
    PlanDraft,
    SuccessCriterion,
)

CONSTRAINTS = Constraints(
    duration_weeks=4, hours_per_week=10, level="intermediate", stack=["fastapi"], team_size=1
)


def draft(**overrides) -> PlanDraft:
    base = dict(
        tasks=[DraftTask(key="k1", weekly_goal_key="w1", task_number=1, title="태스크", description="")],
        weekly_goals=[DraftWeeklyGoal(key="w1", week_index=1, title="1주")],
        tickets=[
            DraftTicket(
                key="t1", task_key="k1", ticket_number=1,
                title="T", body="b", est_minutes=90, depends_on=[],
            )
        ],
        nodes=[DraftNode(node_key="api", label="API", node_type="service", layer="backend")],
        edges=[],
        links=[DraftLink(ticket_key="t1", node_key="api")],
    )
    base.update(overrides)
    return PlanDraft(**base)


def codes(d: PlanDraft, c: Constraints = CONSTRAINTS) -> set[str]:
    return {v.code for v in run_critic(d, c).violations}


def test_통과하는_초안은_ok():
    result = run_critic(draft(), CONSTRAINTS)
    assert result.ok
    assert result.violations == []


def test_빈_계획은_즉시_실패():
    assert codes(draft(tasks=[], tickets=[])) == {"empty_plan"}


def test_R1_120분_초과_티켓을_잡는다():
    d = draft(
        tickets=[
            DraftTicket(key="t1", task_key="k1", ticket_number=1,
                        title="인증 구현", body="b", est_minutes=121, depends_on=[])
        ]
    )
    result = run_critic(d, CONSTRAINTS)
    assert not result.ok
    violation = next(v for v in result.violations if v.code == "ticket_over_120min")
    assert violation.targets == ["t1"]


def test_정확히_120분은_통과():
    d = draft(
        tickets=[
            DraftTicket(key="t1", task_key="k1", ticket_number=1,
                        title="T", body="b", est_minutes=120, depends_on=[])
        ]
    )
    assert "ticket_over_120min" not in codes(d)


def test_의존성_순환을_잡는다():
    d = draft(
        tickets=[
            DraftTicket(key="t1", task_key="k1", ticket_number=1,
                        title="A", body="b", est_minutes=60, depends_on=["t2"]),
            DraftTicket(key="t2", task_key="k1", ticket_number=2,
                        title="B", body="b", est_minutes=60, depends_on=["t1"]),
        ],
        links=[
            DraftLink(ticket_key="t1", node_key="api"),
            DraftLink(ticket_key="t2", node_key="api"),
        ],
    )
    assert "dependency_cycle" in codes(d)


def test_긴_순환도_잡는다():
    d = draft(
        tickets=[
            DraftTicket(key=k, task_key="k1", ticket_number=i, title=k,
                        body="b", est_minutes=30, depends_on=[dep])
            for i, (k, dep) in enumerate([("t1", "t3"), ("t2", "t1"), ("t3", "t2")], start=1)
        ],
        links=[DraftLink(ticket_key=f"t{i}", node_key="api") for i in (1, 2, 3)],
    )
    assert "dependency_cycle" in codes(d)


def test_순환이_아닌_다이아몬드_의존은_통과():
    d = draft(
        tickets=[
            DraftTicket(key="t1", task_key="k1", ticket_number=1, title="A",
                        body="b", est_minutes=30, depends_on=[]),
            DraftTicket(key="t2", task_key="k1", ticket_number=2, title="B",
                        body="b", est_minutes=30, depends_on=["t1"]),
            DraftTicket(key="t3", task_key="k1", ticket_number=3, title="C",
                        body="b", est_minutes=30, depends_on=["t1"]),
            DraftTicket(key="t4", task_key="k1", ticket_number=4, title="D",
                        body="b", est_minutes=30, depends_on=["t2", "t3"]),
        ],
        links=[DraftLink(ticket_key=f"t{i}", node_key="api") for i in range(1, 5)],
    )
    assert run_critic(d, CONSTRAINTS).ok


def test_주간_가용시간_초과를_잡는다():
    tight = Constraints(
        duration_weeks=4, hours_per_week=2, level="beginner", stack=[], team_size=1
    )  # 주당 120분
    d = draft(
        tickets=[
            DraftTicket(key="t1", task_key="k1", ticket_number=1, title="A",
                        body="b", est_minutes=90, depends_on=[]),
            DraftTicket(key="t2", task_key="k1", ticket_number=2, title="B",
                        body="b", est_minutes=90, depends_on=[]),
        ],
        links=[
            DraftLink(ticket_key="t1", node_key="api"),
            DraftLink(ticket_key="t2", node_key="api"),
        ],
    )
    result = run_critic(d, tight)
    violation = next(v for v in result.violations if v.code == "weekly_overload")
    assert "180분" in violation.message and "120분" in violation.message


def test_고아_노드를_잡는다():
    d = draft(
        nodes=[
            DraftNode(node_key="api", label="API", node_type="service", layer="backend"),
            DraftNode(node_key="cache", label="캐시", node_type="store", layer="data"),
        ]
    )
    violation = next(v for v in run_critic(d, CONSTRAINTS).violations if v.code == "orphan_node")
    assert violation.targets == ["cache"]


def test_노드에_안_붙은_티켓을_잡는다():
    d = draft(
        tickets=[
            DraftTicket(key="t1", task_key="k1", ticket_number=1, title="A",
                        body="b", est_minutes=30, depends_on=[]),
            DraftTicket(key="t2", task_key="k1", ticket_number=2, title="B",
                        body="b", est_minutes=30, depends_on=[]),
        ]
    )
    violation = next(
        v for v in run_critic(d, CONSTRAINTS).violations if v.code == "unlinked_ticket"
    )
    assert violation.targets == ["t2"]


@pytest.mark.parametrize(
    "overrides",
    [
        {
            # k1 은 멀쩡하고, k9 만 없는 주를 가리킨다.
            "tasks": [
                DraftTask(
                    key="k1", weekly_goal_key="w1", task_number=1,
                    title="태스크", description="",
                ),
                DraftTask(
                    key="k9", weekly_goal_key="없음", task_number=9,
                    title="X", description="",
                ),
            ]
        },
        {"edges": [DraftEdge(from_key="api", to_key="없음", label="")]},
        {
            "links": [
                DraftLink(ticket_key="t1", node_key="api"),
                DraftLink(ticket_key="없음", node_key="api"),
            ]
        },
    ],
)
def test_끊긴_참조를_잡는다(overrides):
    assert "dangling_reference" in codes(draft(**overrides))


def test_중복_키를_잡는다():
    d = draft(
        tickets=[
            DraftTicket(key="t1", task_key="k1", ticket_number=1, title="A",
                        body="b", est_minutes=30, depends_on=[]),
            DraftTicket(key="t1", task_key="k1", ticket_number=2, title="B",
                        body="b", est_minutes=30, depends_on=[]),
        ]
    )
    assert "duplicate_key" in codes(d)


# ── 청사진 커버리지 (§3.3) ─────────────────────────────────────
BLUEPRINT = Blueprint(
    summary="돌아가는 것",
    criteria=[
        SuccessCriterion(key="sc1", text="목표를 넣으면 티켓이 나온다"),
        SuccessCriterion(key="sc2", text="티켓을 끝내면 노드가 채워진다"),
    ],
)


def test_어느_주도_안_맡은_완성_기준은_걸린다():
    """사용자가 말한 완성 조건이 계획에서 사라지는 것을 여기서 잡는다."""
    d = draft(
        blueprint=BLUEPRINT,
        weekly_goals=[DraftWeeklyGoal(key="w1", week_index=1, title="1주", covers=["sc1"])],
    )
    assert "uncovered_criterion" in codes(d)


def test_모든_기준을_주가_맡으면_통과한다():
    d = draft(
        blueprint=BLUEPRINT,
        weekly_goals=[
            DraftWeeklyGoal(key="w1", week_index=1, title="1주", covers=["sc1", "sc2"])
        ],
    )
    assert "uncovered_criterion" not in codes(d)


def test_없는_기준을_가리키면_끊긴_참조다():
    d = draft(
        blueprint=BLUEPRINT,
        weekly_goals=[
            DraftWeeklyGoal(key="w1", week_index=1, title="1주", covers=["sc1", "sc2", "sc9"])
        ],
    )
    assert "dangling_reference" in codes(d)


def test_기준이_없으면_커버리지를_따지지_않는다():
    """인터뷰를 전부 건너뛴 경우다. 없는 기준을 지어내 강요하지 않는다."""
    d = draft(weekly_goals=[DraftWeeklyGoal(key="w1", week_index=1, title="1주")])
    assert codes(d) == set()
