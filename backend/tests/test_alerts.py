"""알람 규칙 5종 (SPEC §2.3). 문구 톤은 R5 — 책망이 아니라 진단."""

from datetime import date, timedelta

from app.services import alerts, detection
from tests.helpers import seed_project

TODAY = date(2026, 9, 20)


async def _alerts(conn, project_id) -> list:
    return await conn.fetch(
        "select * from alerts where project_id = $1 and acknowledged = false "
        "order by created_at",
        project_id,
    )


async def test_마감_경과_티켓에_막힌_곳을_묻는다(conn):
    p = await seed_project(conn, start=date(2026, 9, 1))
    await conn.execute(
        "update tickets set due_date = $2 where id = $1", p.tickets[0], TODAY - timedelta(days=2)
    )
    assert await alerts.generate_alerts(conn, p.project_id, TODAY) >= 1

    row = next(a for a in await _alerts(conn, p.project_id) if a["rule"] == "due_24h")
    assert row["severity"] == "low"
    assert "어디서 막혔나요?" in row["message"]  # R5 — 질문이지 책망이 아니다


async def test_같은_알람이_매일_쌓이지_않는다(conn):
    p = await seed_project(conn, start=date(2026, 9, 1))
    await conn.execute(
        "update tickets set due_date = $2 where id = $1", p.tickets[0], TODAY - timedelta(days=2)
    )
    await alerts.generate_alerts(conn, p.project_id, TODAY)
    before = len(await _alerts(conn, p.project_id))
    await alerts.generate_alerts(conn, p.project_id, TODAY + timedelta(days=1))
    assert len(await _alerts(conn, p.project_id)) == before


async def test_2회_연기하면_재분할을_제안한다(conn):
    p = await seed_project(conn, start=date(2026, 9, 1))
    for _ in range(2):
        await conn.execute(
            "insert into events (project_id, ticket_id, type) values ($1, $2, 'deferred')",
            p.project_id,
            p.tickets[0],
        )
    await alerts.generate_alerts(conn, p.project_id, TODAY)

    row = next(a for a in await _alerts(conn, p.project_id) if a["rule"] == "deferred_twice")
    assert row["severity"] == "medium"
    assert "쪼갤까요?" in row["message"]


async def test_노드_지연_2건이면_재점검일을_알린다(conn):
    """§2.3 에서 유일하게 강도 '높음'인 규칙."""
    p = await seed_project(conn, start=date(2026, 9, 1))
    for ticket_id in p.tickets[:2]:
        await conn.execute(
            "update tickets set due_date = $2 where id = $1", ticket_id, TODAY - timedelta(days=2)
        )
    await detection.record_missed_tickets(conn, TODAY, p.project_id)
    await alerts.generate_alerts(conn, p.project_id, TODAY)

    row = next(a for a in await _alerts(conn, p.project_id) if a["rule"] == "node_at_risk")
    assert row["severity"] == "high"
    assert row["review_day_id"] is not None
    assert "멈췄어요" in row["message"] and "다시 짤까요?" in row["message"]
    # ✗ "완료하지 않았습니다" 류의 문구가 아니어야 한다 (R5)
    assert "않았습니다" not in row["message"]


async def test_무활동_3일이면_질문한다(conn):
    p = await seed_project(conn, start=date(2026, 9, 1))
    await conn.execute(
        "insert into events (project_id, ticket_id, type, created_at) "
        "values ($1, $2, 'completed', $3)",
        p.project_id,
        p.tickets[0],
        TODAY - timedelta(days=4),
    )
    await alerts.generate_alerts(conn, p.project_id, TODAY)

    row = next(a for a in await _alerts(conn, p.project_id) if a["rule"] == "inactive_3d")
    assert row["severity"] == "low"
    assert row["message"].endswith("?")  # 알람이 아니라 질문이다


async def test_무활동_2일에는_묻지_않는다(conn):
    p = await seed_project(conn, start=date(2026, 9, 1))
    await conn.execute(
        "insert into events (project_id, ticket_id, type, created_at) "
        "values ($1, $2, 'completed', $3)",
        p.project_id,
        p.tickets[0],
        TODAY - timedelta(days=2),
    )
    await alerts.generate_alerts(conn, p.project_id, TODAY)
    assert not [a for a in await _alerts(conn, p.project_id) if a["rule"] == "inactive_3d"]


async def test_주간_완료율_50퍼센트_미만이면_리뷰를_건다(conn):
    p = await seed_project(conn, start=date(2026, 9, 15))  # 1주차가 진행 중
    assert await alerts.generate_weekly_review(conn, p.project_id, date(2026, 9, 20)) == 1

    row = next(a for a in await _alerts(conn, p.project_id) if a["rule"] == "weekly_low")
    assert row["severity"] == "medium"
    assert "같이 볼까요?" in row["message"]


async def test_완료율이_높으면_주간_리뷰를_걸지_않는다(conn):
    p = await seed_project(conn, start=date(2026, 9, 15))
    for ticket_id in p.tickets[:3]:  # 1주차 티켓 전부 완료
        await conn.execute("update tickets set status = 'done' where id = $1", ticket_id)
    assert await alerts.generate_weekly_review(conn, p.project_id, date(2026, 9, 20)) == 0


async def test_확인한_알람은_다시_생길_수_있다(conn):
    """dedupe 는 '미확인 중복'만 막는다. 확인한 뒤 또 걸리면 새로 알려야 한다."""
    p = await seed_project(conn, start=date(2026, 9, 1))
    await conn.execute(
        "update tickets set due_date = $2 where id = $1", p.tickets[0], TODAY - timedelta(days=2)
    )
    await alerts.generate_alerts(conn, p.project_id, TODAY)
    await conn.execute("update alerts set acknowledged = true where project_id = $1", p.project_id)

    await alerts.generate_alerts(conn, p.project_id, TODAY)
    assert len(await _alerts(conn, p.project_id)) >= 1
