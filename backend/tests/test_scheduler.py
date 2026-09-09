"""스케줄러 (SPEC §3.6) 와 목업 Planner."""

from datetime import date, timedelta

from app.graphs.critic import run_critic
from app.graphs.mock_planner import MockPlanner
from app.graphs.plan_graph import build_plan_graph
from app.models.schemas import Constraints
from app.scheduler import build_scheduler
from tests.helpers import drive_plan_graph, seed_project

TODAY = date(2026, 9, 20)


def test_스케줄러가_SPEC_3_6_의_네_작업을_등다():
    scheduler = build_scheduler()
    jobs = {j.id: str(j.trigger) for j in scheduler.get_jobs()}
    assert set(jobs) == {"record_missed", "review_days", "alerts", "weekly_review"}
    assert "hour='0', minute='10'" in jobs["record_missed"]
    assert "hour='0', minute='20'" in jobs["review_days"]
    assert "hour='9', minute='0'" in jobs["alerts"]
    assert "day_of_week='sun'" in jobs["weekly_review"]


async def test_스케줄러_작업이_순서대로_지연을_알람까지_끌고_간다(conn, monkeypatch):
    """00:10 missed -> 00:20 재점검일 -> 09:00 알람 이 한 줄로 이어져야 한다."""
    from app.services import alerts, detection

    p = await seed_project(conn, start=date(2026, 9, 1))
    for ticket_id in p.tickets[:2]:
        await conn.execute(
            "update tickets set due_date = $2 where id = $1", ticket_id, TODAY - timedelta(days=2)
        )

    assert await detection.record_missed_tickets(conn, TODAY, p.project_id) == 2
    assert len(await detection.ensure_review_days(conn, p.project_id, TODAY)) == 1
    assert await alerts.generate_alerts(conn, p.project_id, TODAY) >= 1

    node_status = await conn.fetchval(
        "select status from v_node_status where node_id = $1", p.nodes["node_a"]
    )
    assert node_status == "at_risk"  # §2.5 — 그림에서 바로 읽힌다


async def test_목업_Planner_는_critic_을_통과하는_계획을_만든다():
    """API 키 없이도 데모가 끝까지 돈다."""
    planner = MockPlanner()
    graph = build_plan_graph(planner, max_retries=3)
    result = await drive_plan_graph(
        graph, {"goal_text": "6주 안에 주당 12시간으로 앱 하나 만들기", "known": {}, "attempt": 0}
    )

    draft = result["draft"]
    constraints: Constraints = result["constraints"]
    assert constraints.duration_weeks == 6
    assert constraints.hours_per_week == 12
    assert run_critic(draft, constraints).ok
    assert all(t.est_minutes <= 120 for t in draft.tickets)


async def test_목업은_첫_분해에서_일부러_120분을_넘긴다():
    """critic 재시도 루프가 데모에서 실제로 보여야 한다."""
    planner = MockPlanner()
    graph = build_plan_graph(planner, max_retries=3)
    await drive_plan_graph(graph, {"goal_text": "4주 프로젝트", "known": {}, "attempt": 0})
    assert planner.calls.count("DecomposeResult") >= 2


async def test_always_valid_목업은_한_번에_통과한다():
    planner = MockPlanner(always_valid=True)
    graph = build_plan_graph(planner, max_retries=3)
    result = await drive_plan_graph(graph, {"goal_text": "4주 프로젝트", "known": {}, "attempt": 0})
    assert planner.calls.count("DecomposeResult") == 1
    assert result["critic"].ok
