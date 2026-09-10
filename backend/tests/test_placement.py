"""티켓 투입 (SPEC §3.7) — 만들다 생긴 일 하나가 어디에 놓이는가.

DB 없이 돈다. 자리를 정하는 것과 자리를 검증하는 것이 둘 다 순수 함수라서다.
"""

import pytest

from app.graphs.place_graph import build_place_graph
from app.graphs.placement import build_placement_changes
from app.models.schemas import (
    Constraints,
    DraftEdge,
    DraftLink,
    DraftNode,
    DraftTask,
    DraftTicket,
    DraftWeeklyGoal,
    PlacementResult,
    PlanDraft,
)
from app.services.placement_context import PlacementContext
from tests.fakes import FakePlanner

BODY = "## 무엇을\n한 문장\n\n## 완료 조건\n- [ ] 테스트 3개 통과\n- [ ] 빌드 성공\n"

CONSTRAINTS = Constraints(
    duration_weeks=2, hours_per_week=10, level="intermediate", stack=[], team_size=1
)


def ticket_row(ref_id: str, title: str, *, task: str, week: int, status: str = "open") -> dict:
    return {
        "id": ref_id,
        "title": title,
        "status": status,
        "est_minutes": 60,
        "task_id": task,
        "task_number": 1,
        "task_title": "기반",
        "week_index": week,
        "week_title": f"{week}주",
        "depends_on": [],
        "depends_on_refs": [],
    }


def task_row(task_id: str, week: int) -> dict:
    return {
        "id": task_id,
        "task_number": week,
        "title": f"{week}주 태스크",
        "weekly_goal_id": f"w{week}",
        "week_index": week,
        "week_title": f"{week}주",
    }


REF_TICKETS = {
    "T1": ticket_row("tk1", "저장소 만들기", task="k1", week=1, status="resolved"),
    "T2": ticket_row("tk2", "모델 설계", task="k1", week=1),
    "T3": ticket_row("tk3", "화면 붙이기", task="k2", week=2),
}
REF_TASKS = {"K1": task_row("k1", 1), "K2": task_row("k2", 2)}
NODE_KEYS = {"api", "db"}


def result(**over) -> PlacementResult:
    base = dict(
        task_ref="K1",
        title="넷코드 붙이기",
        body=BODY,
        est_minutes=90,
        depends_on_refs=[],
        blocks_refs=[],
        node_keys=["api"],
        reason="같은 갈래다",
    )
    return PlacementResult(**{**base, **over})


def build(**over):
    return build_placement_changes(
        result(**over),
        fallback_title="넷코드 붙이기",
        ref_to_ticket=REF_TICKETS,
        ref_to_task=REF_TASKS,
        node_keys=NODE_KEYS,
        dependency_map={t["id"]: [] for t in REF_TICKETS.values()},
    )


# ── 자리 잡기 ─────────────────────────────────────────────────
def test_새_티켓과_선후관계가_승인_단위로_나온다():
    changes, line = build(depends_on_refs=["T2"], blocks_refs=["T3"])

    assert [c.type for c in changes] == ["add_ticket", "add_dependency"]
    add = changes[0]
    assert add.op["task_id"] == "k1"
    # 뒤로 밀리는 것 하나는 add_ticket 이 함께 넣는다 (blocks_ticket_id).
    assert add.op["blocks_ticket_id"] == "tk3"
    # 먼저 끝나야 하는 것은 따로 낸다 — 새 티켓이 들어간 뒤에 걸려야 하기 때문이다.
    assert changes[1].op == {"ticket_id": add.op["new_ticket_id"], "depends_on": "tk2"}
    assert line == "1주차 · 1주 태스크 · 「모델 설계」 다음 · 「화면 붙이기」 앞"


def test_이미_끝난_티켓은_선행으로_세지_않는다():
    """T1 은 resolved 다. 끝난 일을 기다리게 하면 새 티켓이 영원히 안 열린다."""
    changes, _ = build(depends_on_refs=["T1"])

    assert [c.type for c in changes] == ["add_ticket"]


def test_앞뒤로_같은_티켓을_걸면_뒤쪽을_버린다():
    """T2 다음이면서 T2 앞일 수는 없다. 순환은 diff 에 올리지 않는다."""
    changes, line = build(depends_on_refs=["T2"], blocks_refs=["T2"])

    assert [c.type for c in changes] == ["add_ticket", "add_dependency"]
    assert changes[0].op["blocks_ticket_id"] is None  # 뒤쪽만 버렸다
    assert "앞" not in line


def test_모르는_참조와_노드는_조용히_버린다():
    changes, _ = build(depends_on_refs=["T9"], blocks_refs=["T9"], node_keys=["api", "없는키"])

    assert [c.type for c in changes] == ["add_ticket"]
    assert changes[0].op["node_keys"] == ["api"]


def test_120분을_넘기면_잘라_넣는다():
    """critic 이 잡을 위반이라도 여기서 걸러낼 수 있으면 여기서 거른다."""
    changes, _ = build(est_minutes=300)

    assert changes[0].op["est_minutes"] == 120


def test_모르는_태스크는_버리지_않고_알린다():
    """자리를 못 고른 것은 조용히 넘길 수 없다 — 넣을 데가 없다는 뜻이다."""
    with pytest.raises(ValueError, match="모르는 태스크 참조"):
        build(task_ref="K9")


# ── 그래프 ────────────────────────────────────────────────────
def context() -> PlacementContext:
    draft = PlanDraft(
        weekly_goals=[
            DraftWeeklyGoal(key="w1", week_index=1, title="1주"),
            DraftWeeklyGoal(key="w2", week_index=2, title="2주"),
        ],
        tasks=[
            DraftTask(key="k1", weekly_goal_key="w1", task_number=1, title="기반", description=""),
            DraftTask(key="k2", weekly_goal_key="w2", task_number=2, title="연결", description=""),
        ],
        tickets=[
            DraftTicket(
                key=t["id"],
                task_key=t["task_id"],
                ticket_number=i,
                title=t["title"],
                body=BODY,
                est_minutes=60,
                depends_on=[],
            )
            for i, t in enumerate(REF_TICKETS.values(), start=1)
        ],
        nodes=[
            DraftNode(node_key="api", label="API", node_type="service", layer="backend"),
            DraftNode(node_key="db", label="DB", node_type="store", layer="data"),
        ],
        edges=[DraftEdge(from_key="api", to_key="db", label="쿼리")],
        # 노드마다 티켓이 하나는 붙어야 한다 (critic 의 고아 노드 검사).
        links=[
            DraftLink(ticket_key=t["id"], node_key="db" if t["id"] == "tk3" else "api")
            for t in REF_TICKETS.values()
        ],
    )
    return PlacementContext(
        project_id=None,  # type: ignore[arg-type]
        constraints=CONSTRAINTS,
        base_draft=draft,
        ref_to_ticket=dict(REF_TICKETS),
        ref_to_task=dict(REF_TASKS),
        nodes=[
            {"node_key": "api", "label": "API", "layer": "backend"},
            {"node_key": "db", "label": "DB", "layer": "data"},
        ],
    )


async def test_그래프가_승인_대기_diff_를_낸다():
    planner = FakePlanner(placements=[result(depends_on_refs=["T2"])])
    graph = build_place_graph(planner)

    final = await graph.ainvoke(
        {"context": context(), "domain": "game", "title": "넷코드 붙이기", "attempt": 0}
    )
    diff = final["diff"]

    assert diff.title == "넷코드 붙이기"
    assert diff.placement.startswith("1주차")
    assert [c.type for c in diff.changes] == ["add_ticket", "add_dependency"]
    assert diff.residual_violations == []


async def test_주간_가용시간을_넘기면_다시_고른다():
    """critic 이 잡고 propose 로 되돌린다 (생성·재설계와 같은 critic).

    가용시간을 주 3시간(180분)으로 낮춘다. 1주에는 이미 120분이 들어 있어
    120분짜리를 더 넣으면 넘치고, 2주(60분)에 30분짜리는 들어간다.
    """
    planner = FakePlanner(
        placements=[result(est_minutes=120), result(task_ref="K2", est_minutes=30)],
        constraints=CONSTRAINTS,
    )
    graph = build_place_graph(planner, max_retries=2)
    ctx = context()
    ctx.constraints = Constraints(
        duration_weeks=2, hours_per_week=3, level="intermediate", stack=[], team_size=1
    )

    final = await graph.ainvoke(
        {"context": ctx, "domain": "game", "title": "넷코드 붙이기", "attempt": 0}
    )

    assert planner.calls.count("PlacementResult") == 2
    assert final["diff"].residual_violations == []
    assert final["diff"].changes[0].op["task_id"] == "k2"
