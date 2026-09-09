"""재설계 그래프 (SPEC §3.4) — 목업 Planner 로 API 키 없이 전 구간을 돈다."""

from datetime import date, timedelta

import pytest

from app.graphs.mock_planner import MockPlanner
from app.graphs.replan_graph import build_replan_graph
from app.services import detection
from app.services.replan_context import load_replan_context
from tests.helpers import seed_project

TODAY = date(2026, 9, 20)


async def _review_context(conn, *, blocked_reason: str | None = None, deferred: int = 0):
    """지연 2건을 만들어 재점검일을 잡고, 그 컨텍스트를 돌려준다."""
    p = await seed_project(conn, start=date(2026, 9, 1))
    for ticket_id in p.tickets[:2]:
        await conn.execute(
            "update tickets set due_date = $2 where id = $1", ticket_id, TODAY - timedelta(days=3)
        )
    await detection.record_missed_tickets(conn, TODAY, p.project_id)

    if blocked_reason:
        await conn.execute(
            "update tickets set status = 'claimed', blocked_reason = $2 where id = $1",
            p.tickets[0],
            blocked_reason,
        )
    for _ in range(deferred):
        await conn.execute(
            "insert into events (project_id, ticket_id, node_id, type) "
            "values ($1, $2, $3, 'deferred')",
            p.project_id,
            p.tickets[0],
            p.nodes["node_a"],
        )

    created = await detection.ensure_review_days(conn, p.project_id, TODAY)
    ctx = await load_replan_context(conn, created[0]["review_day_id"])
    return p, ctx


async def _run(ctx, planner=None):
    graph = build_replan_graph(planner or MockPlanner(), max_retries=2)
    final = await graph.ainvoke({"context": ctx, "attempt": 0})
    return final["diff"]


async def test_집계는_SQL_결과_그대로_들어간다(conn):
    """§2.4 1단계 — AI 가 만지기 전의 숫자."""
    _p, ctx = await _review_context(conn, blocked_reason="netcode 동기화가 안 됨")
    diff = await _run(ctx)

    assert diff.signals.node_key == "node_a"
    assert diff.signals.delayed_tickets == 2
    assert diff.signals.missed_count == 2
    assert diff.signals.blocked_reasons == ["netcode 동기화가 안 됨"]


async def test_막힘_사유가_있으면_지식부족으로_진단한다(conn):
    _p, ctx = await _review_context(conn, blocked_reason="어떻게 하는지 모르겠다")
    diff = await _run(ctx)

    assert diff.diagnosis == "지식부족"
    # §2.4 처방 — 선행 학습 티켓 삽입
    assert "add_ticket" in {c.type for c in diff.changes}


async def test_미룬_횟수가_많으면_범위과다로_진단하고_재분할한다(conn):
    _p, ctx = await _review_context(conn, deferred=3)
    diff = await _run(ctx)

    assert diff.diagnosis == "범위과다"
    assert "split_ticket" in {c.type for c in diff.changes}


async def test_범위는_주_한_개다(conn):
    """R3 — 전체를 다시 그리면 사용자가 자기 계획이라고 느끼지 않는다."""
    _p, ctx = await _review_context(conn, blocked_reason="막힘")
    diff = await _run(ctx)

    scope_ids = {ctx.tickets[t]["weekly_goal_id"] for t in ctx.tickets}
    assert len(scope_ids) > 1  # 시드에 주가 둘 이상 있고
    assert diff.scope_weekly_goal_id in scope_ids  # 재설계는 그중 하나만 건드린다


async def test_변경은_critic_을_통과한_것만_남는다(conn):
    _p, ctx = await _review_context(conn, deferred=3)
    diff = await _run(ctx)
    assert diff.residual_violations == []


async def test_모든_변경에_근거_문장이_붙는다(conn):
    """§2.4 — 사용자가 항목별로 판단하려면 왜 바꾸는지가 있어야 한다."""
    _p, ctx = await _review_context(conn, blocked_reason="막힘")
    diff = await _run(ctx)

    assert diff.changes
    assert all(c.reason for c in diff.changes)
    assert all(c.label for c in diff.changes)


async def test_진단과_처방이_짝을_이룬다(conn):
    """외부요인이면 내용을 건드리지 않고 일정만 민다 (§2.4)."""
    _p, ctx = await _review_context(conn)  # 막힘 사유도 연기도 없다
    diff = await _run(ctx)

    if diff.diagnosis == "외부요인":
        assert {c.type for c in diff.changes} <= {"shift_week"}


@pytest.mark.parametrize("retries", [0, 2])
async def test_재시도_상한과_무관하게_결과를_낸다(conn, retries):
    _p, ctx = await _review_context(conn, deferred=3)
    graph = build_replan_graph(MockPlanner(), max_retries=retries)
    final = await graph.ainvoke({"context": ctx, "attempt": 0})
    assert final["diff"].changes is not None
