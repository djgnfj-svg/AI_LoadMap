"""테스트용 프로젝트 시드."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import asyncpg

from app.graphs.persist import create_project, persist_plan
from app.models.schemas import (
    Constraints,
    DraftEdge,
    DraftLink,
    DraftTask,
    DraftNode,
    DraftTicket,
    DraftWeeklyGoal,
    PlanDraft,
)

def at_utc(day: date) -> datetime:
    """timestamptz 컬럼에 넣을 그 날 자정 (UTC).

    asyncpg 는 순수 date 를 '로컬' 자정으로 인코딩한다. DB 는 UTC 라
    UTC 가 아닌 곳에서 돌리면 하루가 밀린다 — KST 에서 무활동 일수가
    4 대신 5 로 나오던 것이 이것이다. 날짜를 넣을 때는 이걸 쓴다.
    """
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


CONSTRAINTS = Constraints(
    duration_weeks=4, hours_per_week=10, level="intermediate", stack=["fastapi"], team_size=1
)


@dataclass
class Seeded:
    project_id: uuid.UUID
    tickets: list[uuid.UUID]
    nodes: dict[str, uuid.UUID]
    weeks: list[uuid.UUID]
    tasks: list[uuid.UUID]


def sample_draft(n_tickets: int = 4) -> PlanDraft:
    """티켓 1~3 은 node_a, 4번부터는 node_b 에 걸린다. 1~3 은 1주, 나머지는 2주."""
    return PlanDraft(
        weekly_goals=[
            DraftWeeklyGoal(key="w1", week_index=1, title="1주"),
            DraftWeeklyGoal(key="w2", week_index=2, title="2주"),
        ],
        tasks=[
            DraftTask(
                key="k1", weekly_goal_key="w1", task_number=1,
                title="태스크 1", description="1주의 태스크",
            ),
            DraftTask(
                key="k2", weekly_goal_key="w2", task_number=2,
                title="태스크 2", description="2주의 태스크",
            ),
        ],
        tickets=[
            DraftTicket(
                key=f"t{i}",
                task_key="k1" if i <= 3 else "k2",
                # 번호는 태스크마다 1 부터 다시 센다
                ticket_number=i if i <= 3 else i - 3,
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
    weeks = [
        r["id"]
        for r in await conn.fetch(
            "select id from weekly_goals where project_id = $1 order by week_index", project_id
        )
    ]
    tasks = [
        r["id"]
        for r in await conn.fetch(
            "select id from tasks where project_id = $1 order by task_number", project_id
        )
    ]
    return Seeded(project_id, tickets, nodes, weeks, tasks)
