"""API 통합 (SPEC §3.5). 실제 DB 에 붙어 생성 -> 조회 -> 티켓 상태 변경까지 돈다."""

import httpx
import pytest

from app.config import get_settings
from app.services.planner_runs import PlanRunner
from tests.fakes import FakePlanner, make_decompose


@pytest.fixture
async def client(test_dsn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_dsn)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-used")
    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    # LLM 을 부르지 않는 가짜 Planner 를 끼운다. lifespan 은 runner 가 있으면 손대지 않는다.
    app.state.runner = PlanRunner(FakePlanner(), max_retries=3)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app
            yield c

    get_settings.cache_clear()


async def _create_and_wait(client, **body) -> str:
    payload = {"goal_text": "FastAPI 로 로드맵 도구를 4주 안에 만든다"}
    payload.update(body)
    res = await client.post("/projects", json=payload)
    assert res.status_code == 201, res.text
    project_id = res.json()["project_id"]
    run = client.app.state.runner.get(__import__("uuid").UUID(project_id))
    await run.task
    return project_id


async def test_health(client):
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_목표를_넣으면_로드맵과_아키텍처가_함께_생성된다(client):
    """SPEC §1.1 한 줄 정의. D1~D2 완료 기준."""
    project_id = await _create_and_wait(client)

    res = await client.get(f"/projects/{project_id}")
    assert res.status_code == 200
    body = res.json()

    assert body["project"]["title"] == "테스트 프로젝트"
    assert body["generation"]["status"] == "done"
    assert len(body["tasks"]) >= 1
    assert len(body["weekly_goals"]) == 2
    assert len(body["tickets"]) == 4
    assert len(body["arch_nodes"]) == 2
    assert len(body["arch_edges"]) == 1
    assert len(body["ticket_node_links"]) == 4


async def test_모든_티켓이_120분_이내다(client):
    """SPEC §1.7 제품 성공 기준."""
    project_id = await _create_and_wait(client)
    body = (await client.get(f"/projects/{project_id}")).json()
    assert all(t["est_minutes"] <= 120 for t in body["tickets"])


async def test_노드는_React_Flow_좌표를_들고_나온다(client):
    project_id = await _create_and_wait(client)
    body = (await client.get(f"/projects/{project_id}")).json()
    for node in body["arch_nodes"]:
        assert set(node["position"]) == {"x", "y"}
        assert node["computed_status"] == "pending"


async def test_티켓_완료가_노드를_채운다(client):
    """SPEC §2.5 — 데모에서 가장 강한 장면. D6 완료 기준."""
    project_id = await _create_and_wait(client)
    body = (await client.get(f"/projects/{project_id}")).json()

    api_node = next(n for n in body["arch_nodes"] if n["node_key"] == "api")
    api_tickets = [
        link["ticket_id"] for link in body["ticket_node_links"] if link["node_id"] == api_node["id"]
    ]
    assert api_tickets

    res = await client.patch(f"/tickets/{api_tickets[0]}", json={"action": "complete"})
    assert res.status_code == 200
    changed = {c["node_key"]: c["status"] for c in res.json()["node_changes"]}
    assert changed.get("api") == "in_progress"

    for ticket_id in api_tickets[1:]:
        res = await client.patch(f"/tickets/{ticket_id}", json={"action": "complete"})
    assert res.json()["node_changes"][0]["status"] == "done"

    body = (await client.get(f"/projects/{project_id}")).json()
    api_node = next(n for n in body["arch_nodes"] if n["node_key"] == "api")
    assert api_node["status"] == "done"
    assert api_node["progress"] == 1.0


async def test_연기는_상태를_바꾸지_않고_지연만_누적한다(client):
    """SPEC R4 — missed 는 상태가 아니라 이벤트다."""
    project_id = await _create_and_wait(client)
    body = (await client.get(f"/projects/{project_id}")).json()
    ticket_id = body["tickets"][0]["id"]

    res = await client.patch(
        f"/tickets/{ticket_id}", json={"action": "defer", "new_due_date": "2026-10-01"}
    )
    ticket = res.json()["ticket"]
    assert ticket["status"] == "open"        # 상태는 그대로
    assert ticket["delay_count"] == 1        # 지연만 누적
    assert ticket["due_date"] == "2026-10-01"


async def test_지연_2건이면_노드가_at_risk_로_바뀐다(client):
    """SPEC §2.5 — at_risk 는 그림 위에서 바로 읽혀야 한다."""
    project_id = await _create_and_wait(client)
    body = (await client.get(f"/projects/{project_id}")).json()
    api_node = next(n for n in body["arch_nodes"] if n["node_key"] == "api")
    api_tickets = [
        link["ticket_id"] for link in body["ticket_node_links"] if link["node_id"] == api_node["id"]
    ]

    await client.patch(f"/tickets/{api_tickets[0]}", json={"action": "defer"})
    res = await client.patch(f"/tickets/{api_tickets[1]}", json={"action": "defer"})

    changed = {c["node_key"]: c["status"] for c in res.json()["node_changes"]}
    assert changed.get("api") == "at_risk"


async def test_막힘_사유를_남기면_blocked_이벤트가_쌓인다(client):
    """SPEC §2.3 — 사용자가 입력한 막힘 사유는 재점검 세션의 입력이 된다."""
    project_id = await _create_and_wait(client)
    body = (await client.get(f"/projects/{project_id}")).json()
    ticket_id = body["tickets"][0]["id"]

    res = await client.post(
        f"/tickets/{ticket_id}/block", json={"reason": "네트워크 동기화가 안 됨"}
    )
    assert res.status_code == 200
    # 막힘은 상태가 아니다 — 잡고 있다가 멈춘 것이라 claimed 로 남고 사유가 한 줄 붙는다.
    assert res.json()["ticket"]["status"] == "claimed"
    assert res.json()["ticket"]["blocked_reason"] == "네트워크 동기화가 안 됨"


async def test_정보가_부족하면_clarify_질문을_돌려준다(client):
    """SPEC §3.3 clarify — 부족한 정보만, 최대 5개."""
    client.app.state.runner = PlanRunner(FakePlanner(missing=["hours_per_week"]))
    project_id = await _create_and_wait(client)

    body = (await client.get(f"/projects/{project_id}")).json()
    assert body["generation"]["status"] == "awaiting_clarify"
    assert [q["field"] for q in body["generation"]["questions"]] == ["hours_per_week"]
    assert body["tickets"] == []  # 답을 받기 전에는 아무것도 저장하지 않는다

    res = await client.post(
        f"/projects/{project_id}/clarify", json={"answers": {"hours_per_week": "주 15시간"}}
    )
    assert res.status_code == 200
    run = client.app.state.runner.get(__import__("uuid").UUID(project_id))
    await run.task

    body = (await client.get(f"/projects/{project_id}")).json()
    assert body["generation"]["status"] == "done"
    assert body["project"]["constraints"]["hours_per_week"] == 15
    assert len(body["tickets"]) == 4


async def test_재시도가_소진되면_복구_내역이_사용자에게_보인다(client):
    """SPEC §3.3 — LLM 이 끝까지 120분을 못 지켜도 계획은 나온다. 대신 무엇을 고쳤는지 밝힌다."""
    client.app.state.runner = PlanRunner(
        FakePlanner(decompose_results=[make_decompose(est_minutes=200)]), max_retries=1
    )
    project_id = await _create_and_wait(client)

    body = (await client.get(f"/projects/{project_id}")).json()
    assert body["generation"]["repairs"]
    assert all(t["est_minutes"] <= 120 for t in body["tickets"])


async def test_없는_프로젝트는_404(client):
    res = await client.get("/projects/00000000-0000-0000-0000-000000000099")
    assert res.status_code == 404
