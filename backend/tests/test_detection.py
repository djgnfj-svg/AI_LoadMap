"""실패 감지 (SPEC §2.3, §4.5). 전부 SQL 이고 AI 는 개입하지 않는다 (R2)."""

from datetime import date, timedelta

import pytest

from app.services import detection
from tests.helpers import at_utc, seed_project

TODAY = date(2026, 9, 20)


async def test_마감_지난_티켓에_missed_를_남긴다(conn):
    p = await seed_project(conn, start=date(2026, 9, 1))
    await conn.execute(
        "update tickets set due_date = $2 where id = $1", p.tickets[0], TODAY - timedelta(days=3)
    )

    assert await detection.record_missed_tickets(conn, TODAY, p.project_id) == 1

    row = await conn.fetchrow(
        "select delay_count, status from tickets where id = $1", p.tickets[0]
    )
    assert row["delay_count"] == 1
    assert row["status"] == "open"  # R4 — missed 는 상태가 아니다

    event = await conn.fetchrow(
        "select * from events where ticket_id = $1 and type = 'missed'", p.tickets[0]
    )
    assert event["payload"]["overdue_days"] == 3
    assert event["node_id"] is not None  # 집계용 node_id 가 채워진다


async def test_같은_마감일에_두_번_기록하지_않는다(conn):
    """스케줄러가 매일 돌아도 5일 밀린 티켓의 지연이 5로 불어나면 안 된다."""
    p = await seed_project(conn, start=date(2026, 9, 1))
    await conn.execute(
        "update tickets set due_date = $2 where id = $1", p.tickets[0], TODAY - timedelta(days=3)
    )

    assert await detection.record_missed_tickets(conn, TODAY, p.project_id) == 1
    assert await detection.record_missed_tickets(conn, TODAY + timedelta(days=1), p.project_id) == 0
    assert await detection.record_missed_tickets(conn, TODAY + timedelta(days=2), p.project_id) == 0

    assert await conn.fetchval(
        "select delay_count from tickets where id = $1", p.tickets[0]
    ) == 1


async def test_기한을_옮기면_새_마감일에_다시_기록된다(conn):
    p = await seed_project(conn, start=date(2026, 9, 1))
    await conn.execute(
        "update tickets set due_date = $2 where id = $1", p.tickets[0], TODAY - timedelta(days=3)
    )
    await detection.record_missed_tickets(conn, TODAY, p.project_id)

    await conn.execute(
        "update tickets set due_date = $2 where id = $1", p.tickets[0], TODAY - timedelta(days=1)
    )
    assert await detection.record_missed_tickets(conn, TODAY, p.project_id) == 1
    assert await conn.fetchval(
        "select delay_count from tickets where id = $1", p.tickets[0]
    ) == 2


async def test_완료된_티켓은_건너뛴다(conn):
    p = await seed_project(conn, start=date(2026, 9, 1))
    await conn.execute(
        "update tickets set due_date = $2, status = 'resolved' where id = $1",
        p.tickets[0],
        TODAY - timedelta(days=5),
    )
    assert await detection.record_missed_tickets(conn, TODAY, p.project_id) == 0


async def test_동일_노드_지연_2건이면_재점검일이_잡힌다(conn):
    """SPEC §4.5 — 이 판단에 AI 는 개입하지 않는다."""
    p = await seed_project(conn, start=date(2026, 9, 1))
    for ticket_id in p.tickets[:2]:  # 둘 다 node_a 에 걸려 있다
        await conn.execute(
            "update tickets set due_date = $2 where id = $1", ticket_id, TODAY - timedelta(days=2)
        )
    await detection.record_missed_tickets(conn, TODAY, p.project_id)

    delays = await detection.node_delays(conn, p.project_id, TODAY)
    assert [(d.node_key, d.delays) for d in delays] == [("node_a", 2)]

    created = await detection.ensure_review_days(conn, p.project_id, TODAY)
    assert len(created) == 1
    assert created[0]["scheduled_date"] == TODAY + timedelta(days=detection.REVIEW_LEAD_DAYS)
    assert "지연 2건" in created[0]["trigger_reason"]


async def test_미해결_재점검일이_있으면_또_만들지_않는다(conn):
    p = await seed_project(conn, start=date(2026, 9, 1))
    for ticket_id in p.tickets[:2]:
        await conn.execute(
            "update tickets set due_date = $2 where id = $1", ticket_id, TODAY - timedelta(days=2)
        )
    await detection.record_missed_tickets(conn, TODAY, p.project_id)

    assert len(await detection.ensure_review_days(conn, p.project_id, TODAY)) == 1
    assert len(await detection.ensure_review_days(conn, p.project_id, TODAY)) == 0


async def test_지연_1건이면_재점검일이_안_잡힌다(conn):
    p = await seed_project(conn, start=date(2026, 9, 1))
    await conn.execute(
        "update tickets set due_date = $2 where id = $1", p.tickets[0], TODAY - timedelta(days=2)
    )
    await detection.record_missed_tickets(conn, TODAY, p.project_id)
    assert await detection.ensure_review_days(conn, p.project_id, TODAY) == []


async def test_14일보다_오래된_지연은_집계에서_빠진다(conn):
    p = await seed_project(conn, start=date(2026, 8, 1))
    old = TODAY - timedelta(days=detection.DELAY_WINDOW_DAYS + 1)
    for ticket_id in p.tickets[:2]:
        await conn.execute(
            "insert into events (project_id, ticket_id, node_id, type, created_at) "
            "select $1, $2, node_id, 'missed', $3 from ticket_node_links where ticket_id = $2",
            p.project_id,
            ticket_id,
            at_utc(old),
        )
    assert await detection.node_delays(conn, p.project_id, TODAY) == []


async def test_동일_티켓_2회_연기를_잡는다(conn):
    p = await seed_project(conn, start=date(2026, 9, 1))
    for _ in range(2):
        await conn.execute(
            "insert into events (project_id, ticket_id, type) values ($1, $2, 'deferred')",
            p.project_id,
            p.tickets[0],
        )
    rows = await detection.tickets_deferred_twice(conn, p.project_id)
    assert [r["defers"] for r in rows] == [2]


async def test_주간_완료율을_센다(conn):
    p = await seed_project(conn, start=date(2026, 9, 1))
    await conn.execute("update tickets set status = 'resolved' where id = $1", p.tickets[0])
    result = await detection.weekly_completion(conn, p.project_id, 1)
    assert (result.total, result.done) == (3, 1)
    assert result.rate == pytest.approx(1 / 3)


async def test_무활동_일수는_사용자_행동만_센다(conn):
    """스케줄러가 남긴 missed 를 활동으로 치면 무활동 알람이 영원히 안 뜬다."""
    p = await seed_project(conn, start=date(2026, 9, 1))
    assert await detection.days_since_activity(conn, p.project_id, TODAY) is None

    await conn.execute(
        "insert into events (project_id, ticket_id, type, created_at) "
        "values ($1, $2, 'missed', $3)",
        p.project_id,
        p.tickets[0],
        at_utc(TODAY),
    )
    assert await detection.days_since_activity(conn, p.project_id, TODAY) is None

    await conn.execute(
        "insert into events (project_id, ticket_id, type, created_at) "
        "values ($1, $2, 'completed', $3)",
        p.project_id,
        p.tickets[0],
        at_utc(TODAY - timedelta(days=4)),
    )
    assert await detection.days_since_activity(conn, p.project_id, TODAY) == 4
