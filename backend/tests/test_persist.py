"""emit 단계 저장 (app/graphs/persist.py) + DB 제약 (SPEC §4)."""

import uuid
from datetime import date

import asyncpg
import pytest

from app.config import get_settings
from app.graphs.persist import create_project, layout_positions, persist_plan
from app.models.schemas import Constraints, PlanDraft
from tests.fakes import ARCHITECT, make_decompose, make_links

CONSTRAINTS = Constraints(
    duration_weeks=4, hours_per_week=10, level="intermediate", stack=["fastapi"], team_size=1
)
START = date(2026, 9, 7)


def sample_draft() -> PlanDraft:
    d = make_decompose(est_minutes=90, n_tickets=4)
    return PlanDraft(
        tasks=d.tasks,
        weekly_goals=d.weekly_goals,
        tickets=d.tickets,
        nodes=ARCHITECT.nodes,
        edges=ARCHITECT.edges,
        links=make_links(4).links,
    )


async def save(conn) -> uuid.UUID:
    project_id = await create_project(
        conn, user_id=get_settings().demo_user_id, goal_text="테스트 목표", start_date=START
    )
    await persist_plan(
        conn,
        project_id=project_id,
        title="테스트 프로젝트",
        constraints=CONSTRAINTS,
        draft=sample_draft(),
        start_date=START,
    )
    return project_id


async def test_트리_전체가_저장된다(conn):
    project_id = await save(conn)

    counts = {
        table: await conn.fetchval(
            f"select count(*) from {table} where project_id = $1", project_id
        )
        for table in ("tasks", "tickets", "arch_nodes", "arch_edges", "events")
    }
    assert counts == {
        "tasks": 2, "tickets": 4, "arch_nodes": 2, "arch_edges": 1, "events": 4
    }

    goals = await conn.fetchval(
        "select count(*) from weekly_goals where project_id = $1",
        project_id,
    )
    assert goals == 2


async def test_티켓_생성시_created_이벤트가_남는다(conn):
    project_id = await save(conn)
    rows = await conn.fetch(
        "select type, ticket_id, node_id from events where project_id = $1", project_id
    )
    assert {r["type"] for r in rows} == {"created"}
    assert all(r["node_id"] is not None for r in rows)  # 집계용 node_id 가 채워진다


async def test_주에서_티켓_마감일이_계산된다(conn):
    """티켓의 마감일은 그 티켓이 든 태스크가 사는 주에서 온다."""
    project_id = await save(conn)
    rows = await conn.fetch(
        "select t.due_date, g.week_index from tickets t "
        "join tasks k        on k.id = t.task_id "
        "join weekly_goals g on g.id = k.weekly_goal_id "
        "where t.project_id = $1",
        project_id,
    )
    for r in rows:
        # 1주 = 시작일 + 6일
        assert (r["due_date"] - START).days == r["week_index"] * 7 - 1


async def test_선행_관계가_uuid_로_치환되어_저장된다(conn):
    project_id = await save(conn)
    deps = await conn.fetch(
        "select d.* from ticket_dependencies d join tickets t on t.id = d.ticket_id "
        "where t.project_id = $1",
        project_id,
    )
    assert len(deps) == 3  # t2<-t1, t3<-t2, t4<-t3
    assert all(d["ticket_id"] != d["depends_on"] for d in deps)


async def test_노드_좌표가_레이어별로_배치된다():
    positions = layout_positions(sample_draft())
    assert positions["api"]["y"] != positions["db"]["y"]  # backend / data 는 다른 줄
    assert all(isinstance(v["x"], int) for v in positions.values())


async def test_R1_은_DB_가_강제한다(conn):
    """critic 을 우회해도 121분 티켓은 들어가지 않는다 (SPEC §4.2 check 제약)."""
    project_id = await save(conn)
    task_id = await conn.fetchval(
        "select id from tasks where project_id = $1 limit 1", project_id
    )
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(
            "insert into tickets (task_id, project_id, ticket_number, title, est_minutes) "
            "values ($1, $2, 99, '너무 큰 티켓', 121)",
            task_id,
            project_id,
        )


async def test_노드_상태_뷰가_진행률을_계산한다(conn):
    """SPEC §4.4 — 감지는 SQL 이 한다 (R2)."""
    project_id = await save(conn)

    rows = await conn.fetch(
        "select node_key, status, progress from v_node_status where project_id = $1", project_id
    )
    assert {r["status"] for r in rows} == {"pending"}

    # api 노드에 붙은 티켓 하나를 완료
    ticket_id = await conn.fetchval(
        "select l.ticket_id from ticket_node_links l join arch_nodes n on n.id = l.node_id "
        "where n.project_id = $1 and n.node_key = 'api' limit 1",
        project_id,
    )
    await conn.execute("update tickets set status = 'resolved' where id = $1", ticket_id)

    api = await conn.fetchrow(
        "select * from v_node_status where project_id = $1 and node_key = 'api'", project_id
    )
    assert api["status"] == "in_progress"
    assert 0 < api["progress"] < 1


async def test_지연_2건이면_노드가_at_risk_가_된다(conn):
    """SPEC §2.5 — at_risk 는 진행률보다 우선한다."""
    project_id = await save(conn)
    ticket_ids = await conn.fetch(
        "select l.ticket_id from ticket_node_links l join arch_nodes n on n.id = l.node_id "
        "where n.project_id = $1 and n.node_key = 'api'",
        project_id,
    )
    for r in ticket_ids:
        await conn.execute(
            "update tickets set status = 'resolved', delay_count = 1 where id = $1", r["ticket_id"]
        )

    api = await conn.fetchrow(
        "select * from v_node_status where project_id = $1 and node_key = 'api'", project_id
    )
    assert api["progress"] == 1.0
    assert api["status"] == "at_risk"  # 100% 완료여도 지연 2건이면 at_risk


async def test_태스크_상태는_티켓에서_되읽는다(conn):
    """§2.1 — 태스크는 티켓들의 집이다. 안이 다 끝났는데 open 이면 보드가 거짓말한다."""
    from app.services.task_status import sync_task_status

    project_id = await save(conn)
    task_id = await conn.fetchval(
        "select id from tasks where project_id = $1 order by task_number limit 1", project_id
    )
    assert await conn.fetchval("select status from tasks where id = $1", task_id) == "open"

    # 하나만 잡으면 claimed
    one = await conn.fetchval(
        "select id from tickets where task_id = $1 order by ticket_number limit 1", task_id
    )
    await conn.execute("update tickets set status = 'claimed' where id = $1", one)
    await sync_task_status(conn, project_id)
    assert await conn.fetchval("select status from tasks where id = $1", task_id) == "claimed"

    # 전부 끝나면 resolved
    await conn.execute("update tickets set status = 'resolved' where task_id = $1", task_id)
    await sync_task_status(conn, project_id)
    assert await conn.fetchval("select status from tasks where id = $1", task_id) == "resolved"

    # 남은 것이 전부 접혔으면 parked
    await conn.execute("update tickets set status = 'parked' where id = $1", one)
    await sync_task_status(conn, project_id)
    assert await conn.fetchval("select status from tasks where id = $1", task_id) == "parked"


async def test_막힘은_상태가_아니라_사유_한_줄이다(conn):
    """상태 낱말 넷에 막힘은 없다. 막힌 티켓은 claimed 이고 사유가 붙어 있다."""
    project_id = await save(conn)
    ticket_id = await conn.fetchval(
        "select id from tickets where project_id = $1 limit 1", project_id
    )
    await conn.execute(
        "update tickets set status = 'claimed', blocked_reason = $2 where id = $1",
        ticket_id,
        "CORS 가 계속 막힌다",
    )
    row = await conn.fetchrow(
        "select status, blocked_reason from tickets where id = $1", ticket_id
    )
    assert row["status"] == "claimed"
    assert row["blocked_reason"] == "CORS 가 계속 막힌다"

    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(
            "update tickets set status = 'blocked' where id = $1", ticket_id
        )
