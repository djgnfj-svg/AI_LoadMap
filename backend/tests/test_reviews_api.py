"""재점검 세션 API 통합 (SPEC §2.4 전 구간, §3.5).

집계 -> 진단 -> 부분 재설계 -> 항목별 승인이 실제 DB 위에서 한 번 완주하는지 본다.
"""

from datetime import date, timedelta

import httpx
import pytest

from app.config import get_settings
from app.graphs.mock_planner import MockPlanner
from app.graphs.replan_graph import build_replan_graph
from app.services import alerts as alert_service
from app.services import detection
from app.services.planner_runs import PlanRunner
from tests.helpers import seed_project

TODAY = date(2026, 9, 20)


@pytest.fixture
async def app_client(test_dsn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_dsn)
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    planner = MockPlanner()
    app.state.runner = PlanRunner(planner)
    app.state.replan_graph = build_replan_graph(planner, max_retries=2)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            assert (await c.post("/auth/demo")).status_code == 200
            yield c

    get_settings.cache_clear()


async def _prepare(dsn) -> tuple[str, str]:
    """지연 2건 + 막힘 사유를 만들고 (project_id, review_day_id) 를 돌려준다."""
    import asyncpg

    conn = await asyncpg.connect(dsn)
    import json

    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    try:
        p = await seed_project(conn, start=date(2026, 9, 1))
        for ticket_id in p.tickets[:2]:
            await conn.execute(
                "update tickets set due_date = $2 where id = $1",
                ticket_id,
                TODAY - timedelta(days=3),
            )
        await conn.execute(
            "update tickets set status = 'claimed', blocked_reason = $2 where id = $1",
            p.tickets[0],
            "방법을 모르겠다",
        )
        await detection.record_missed_tickets(conn, TODAY)
        await alert_service.generate_alerts(conn, p.project_id, TODAY)
        review_id = await conn.fetchval(
            "select id from review_days where project_id = $1", p.project_id
        )
        return str(p.project_id), str(review_id)
    finally:
        await conn.close()


async def test_알람_목록과_재점검일을_함께_준다(app_client, test_dsn):
    project_id, review_id = await _prepare(test_dsn)

    res = await app_client.get(f"/projects/{project_id}/alerts")
    body = res.json()
    assert res.status_code == 200
    assert any(a["rule"] == "node_at_risk" and a["severity"] == "high" for a in body["alerts"])
    assert [r["id"] for r in body["review_days"]] == [review_id]


async def test_알람을_확인하면_목록에서_빠진다(app_client, test_dsn):
    project_id, _ = await _prepare(test_dsn)
    alerts = (await app_client.get(f"/projects/{project_id}/alerts")).json()["alerts"]

    await app_client.post(f"/alerts/{alerts[0]['id']}/ack")
    after = (await app_client.get(f"/projects/{project_id}/alerts")).json()["alerts"]
    assert len(after) == len(alerts) - 1


async def test_돌리기_전에도_집계_숫자는_보인다(app_client, test_dsn):
    """§2.4 1단계는 AI 없이 먼저 보여준다."""
    _project_id, review_id = await _prepare(test_dsn)

    body = (await app_client.get(f"/reviews/{review_id}")).json()
    assert body["session"] is None
    assert body["signals"]["delayed_tickets"] == 2
    assert body["signals"]["blocked_reasons"] == ["방법을 모르겠다"]


async def test_재설계를_실행하면_진단과_diff_가_나온다(app_client, test_dsn):
    _project_id, review_id = await _prepare(test_dsn)

    res = await app_client.post(f"/reviews/{review_id}/run")
    assert res.status_code == 200
    diff = res.json()["diff"]
    assert diff["diagnosis"] in ("지식부족", "범위과다", "의존성누락", "외부요인")
    assert diff["changes"]
    assert diff["residual_violations"] == []

    # 세션이 저장돼 새로고침해도 같은 diff 를 본다
    again = (await app_client.get(f"/reviews/{review_id}")).json()
    assert again["session"]["diff"]["diagnosis"] == diff["diagnosis"]
    assert again["session"]["applied"] is False


async def test_승인한_항목만_계획에_들어간다(app_client, test_dsn):
    """§2.4 4단계 — 항목별 승인/거절."""
    project_id, review_id = await _prepare(test_dsn)
    diff = (await app_client.post(f"/reviews/{review_id}/run")).json()["diff"]
    before = len((await app_client.get(f"/projects/{project_id}")).json()["tickets"])

    approved = [diff["changes"][0]["id"]]
    res = await app_client.post(f"/reviews/{review_id}/apply", json={"approved": approved})
    body = res.json()
    assert body["approved"] == approved
    assert body["rejected"] == [c["id"] for c in diff["changes"][1:]]
    assert body["applied"] == approved

    after = (await app_client.get(f"/projects/{project_id}")).json()["tickets"]
    if diff["changes"][0]["type"] == "add_ticket":
        assert len(after) == before + 1
    assert all(t["est_minutes"] <= 120 for t in after)  # R1 은 재설계 뒤에도 지켜진다


async def test_적용하면_재점검일이_닫히고_알람도_정리된다(app_client, test_dsn):
    project_id, review_id = await _prepare(test_dsn)
    await app_client.post(f"/reviews/{review_id}/run")
    await app_client.post(f"/reviews/{review_id}/apply", json={"approved": []})

    body = (await app_client.get(f"/reviews/{review_id}")).json()
    assert body["review_day"]["status"] == "done"
    assert body["session"]["applied"] is True

    alerts = (await app_client.get(f"/projects/{project_id}/alerts")).json()
    assert not [a for a in alerts["alerts"] if a["rule"] == "node_at_risk"]


async def test_모르는_변경_id_는_거절한다(app_client, test_dsn):
    _project_id, review_id = await _prepare(test_dsn)
    await app_client.post(f"/reviews/{review_id}/run")

    res = await app_client.post(f"/reviews/{review_id}/apply", json={"approved": ["c999"]})
    assert res.status_code == 400


async def test_재점검일은_미룰_수만_있고_지울_수_없다(app_client, test_dsn):
    """§2.4 — 사용자는 날짜 변경만 가능하다. 미룬 사실도 기록된다."""
    _project_id, review_id = await _prepare(test_dsn)

    res = await app_client.patch(f"/reviews/{review_id}", json={"scheduled_date": "2026-10-01"})
    assert res.status_code == 200
    assert res.json() == {
        "id": review_id,
        "scheduled_date": "2026-10-01",
        "postponed_count": 1,
    }
    assert (await app_client.request("DELETE", f"/reviews/{review_id}")).status_code == 405


async def test_감지를_즉시_돌릴_수_있다(app_client, test_dsn):
    project_id, _ = await _prepare(test_dsn)
    res = await app_client.post(f"/projects/{project_id}/detect", json={})
    assert res.status_code == 200
    assert res.json()["missed_events"] >= 0
