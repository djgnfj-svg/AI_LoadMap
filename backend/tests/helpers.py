"""테스트용 프로젝트 시드."""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

import asyncpg

from app.graphs.persist import create_project, persist_plan
from app.models.schemas import (
    Constraints,
    DraftEdge,
    DraftLink,
    DraftMilestone,
    DraftNode,
    DraftTicket,
    DraftWeeklyGoal,
    PlanDraft,
)

CONSTRAINTS = Constraints(
    duration_weeks=4, hours_per_week=10, level="intermediate", stack=["fastapi"], team_size=1
)


@dataclass
class Seeded:
    project_id: uuid.UUID
    tickets: list[uuid.UUID]
    nodes: dict[str, uuid.UUID]
    milestones: list[uuid.UUID]


def sample_draft(n_tickets: int = 4) -> PlanDraft:
    """티켓 1~3 은 node_a, 4번부터는 node_b 에 걸린다. 1~3 은 1주차, 나머지는 2주차."""
    return PlanDraft(
        milestones=[
            DraftMilestone(key="m1", order_index=1, title="1단계", description="첫 마일스톤"),
            DraftMilestone(key="m2", order_index=2, title="2단계", description="후속 마일스톤"),
        ],
        weekly_goals=[
            DraftWeeklyGoal(key="w1", milestone_key="m1", week_index=1, title="1주차"),
            DraftWeeklyGoal(key="w2", milestone_key="m2", week_index=2, title="2주차"),
        ],
        tickets=[
            DraftTicket(
                key=f"t{i}",
                weekly_goal_key="w1" if i <= 3 else "w2",
                order_index=i,
                title=f"티켓 {i}",
                body=f"## 무엇을\n티켓 {i}\n\n## 완료 조건\n- [ ] 테스트 통과\n",
                est_minutes=60,
                depends_on=[f"t{i - 1}"] if i > 1 else [],
            )
            for i in range(1, n_tickets + 1)
        ],
        nodes=[
            DraftNode(node_key="node_a", label="컴포넌트 A", node_type="service", layer="backend"),
            DraftNode(node_key="node_b", label="컴포넌트 B", node_type="store", layer="data"),
        ],
        edges=[DraftEdge(from_key="node_a", to_key="node_b", label="쓰기")],
        links=[
            DraftLink(ticket_key=f"t{i}", node_key="node_a" if i <= 3 else "node_b")
            for i in range(1, n_tickets + 1)
        ],
    )


async def seed_project(
    conn: asyncpg.Connection, *, start: date | None = None, n_tickets: int = 4
) -> Seeded:
    draft = sample_draft(n_tickets)
    project_id = await create_project(
        conn, user_id=None, goal_text="테스트 목표", start_date=start or date.today()
    )
    await persist_plan(
        conn,
        project_id=project_id,
        title="테스트 프로젝트",
        constraints=CONSTRAINTS,
        draft=draft,
        start_date=start,
    )
    # 마감을 멀리 밀어둔다. 어떤 티켓이 지연인지는 테스트가 직접 정한다.
    await conn.execute(
        "update tickets set due_date = $2 where project_id = $1",
        project_id,
        (start or date.today()) + timedelta(days=365),
    )
    tickets = [
        r["id"]
        for r in await conn.fetch(
            "select id from tickets where project_id = $1 order by title", project_id
        )
    ]
    nodes = {
        r["node_key"]: r["id"]
        for r in await conn.fetch(
            "select id, node_key from arch_nodes where project_id = $1", project_id
        )
    }
    milestones = [
        r["id"]
        for r in await conn.fetch(
            "select id from milestones where project_id = $1 order by order_index", project_id
        )
    ]
    return Seeded(project_id, tickets, nodes, milestones)
