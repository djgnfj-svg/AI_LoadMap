"""API 통합 (SPEC §3.5). 실제 DB 에 붙어 생성 -> 조회 -> 티켓 상태 변경까지 돈다."""

import uuid

import httpx
import pytest

from app.config import get_settings
from app.graphs.interview import MAX_ROUNDS as INTERVIEW_ROUNDS
from app.services.planner_runs import PlanRunner
from tests.fakes import FakePlanner, make_decompose


@pytest.fixture
async def client(test_dsn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_dsn)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-used")
    # 구글 클라이언트 ID 가 없어야 /auth/demo 가 열린다.
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    # LLM 을 부르지 않는 가짜 Planner 를 끼운다. lifespan 은 runner 가 있으면 손대지 않는다.
    app.state.runner = PlanRunner(FakePlanner(), max_retries=3)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app
            # 모든 API 가 로그인을 요구한다 (0004). 쿠키는 클라이언트가 물고 있는다.
            assert (await c.post("/auth/demo")).status_code == 200
            yield c

    get_settings.cache_clear()


async def _create(client, **body) -> str:
    """프로젝트를 만들고 첫 실행이 끝날 때까지 기다린다 (보통 인터뷰 1라운드에서 멈춘다)."""
    payload = {"goal_text": "FastAPI 로 로드맵 도구를 4주 안에 만든다"}
    payload.update(body)
    res = await client.post("/projects", json=payload)
    assert res.status_code == 201, res.text
    project_id = res.json()["project_id"]
    await _wait(client, project_id)
    return project_id


async def _wait(client, project_id: str) -> None:
    run = client.app.state.runner.get(uuid.UUID(project_id))
    if run is not None:
        await run.task


async def _answer_interview(client, project_id: str, **answers: str) -> None:
    """인터뷰가 끝날 때까지 답한다. 화면이 하는 일과 같다."""
    for _ in range(INTERVIEW_ROUNDS + 1):
        body = (await client.get(f"/projects/{project_id}")).json()
        if body["generation"]["status"] != "awaiting_clarify":
            return
        payload = {q["field"]: answers.get(q["field"], "테스트 답변") for q in
                   body["generation"]["questions"]}
        res = await client.post(f"/projects/{project_id}/clarify", json={"answers": payload})
        assert res.status_code == 200, res.text
        await _wait(client, project_id)
    raise AssertionError("인터뷰가 끝나지 않았다")


async def _create_and_wait(client, **body) -> str:
    """계획이 만들어질 때까지 — 인터뷰까지 마친다."""
    project_id = await _create(client, **body)
    await _answer_interview(client, project_id)
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


async def test_처음에는_청사진을_묻는다(client):
    """SPEC §3.3 인터뷰 — 목표만 받고 바로 쪼개지 않는다."""
    project_id = await _create(client)

    body = (await client.get(f"/projects/{project_id}")).json()
    assert body["generation"]["status"] == "awaiting_clarify"
    assert body["generation"]["questions"][0]["field"] == "blueprint"
    assert "청사진" in body["generation"]["questions"][0]["question"]
    assert body["tickets"] == []  # 답을 받기 전에는 아무것도 저장하지 않는다


async def test_인터뷰_답변은_원문으로_저장된다(client):
    """숫자만 뽑고 문장을 버리면 사용자가 무슨 말을 해도 계획이 안 바뀐다."""
    project_id = await _create(client)
    await _answer_interview(
        client,
        project_id,
        blueprint="친구 4명이 30분 세션을 끊김 없이 도는 코옵 게임",
        deadline="3개월",
    )

    body = (await client.get(f"/projects/{project_id}")).json()
    assert body["generation"]["status"] == "done"
    saved = {t["field"]: t["answer"] for t in body["interview"]}
    assert saved["blueprint"] == "친구 4명이 30분 세션을 끊김 없이 도는 코옵 게임"
    assert body["project"]["constraints"]["duration_weeks"] == 13  # 3개월
    assert len(body["tickets"]) == 4


async def test_완성_기준이_저장되고_주가_맡는다(client):
    """§3.3 — 사용자가 말한 완성 조건이 계획에 남아 있어야 한다."""
    project_id = await _create_and_wait(client)

    body = (await client.get(f"/projects/{project_id}")).json()
    criteria = body["project"]["blueprint"]["criteria"]
    assert [c["key"] for c in criteria] == ["sc1", "sc2"]

    covered = {k for g in body["weekly_goals"] for k in g["covers"]}
    assert covered == {"sc1", "sc2"}  # 모든 기준을 어느 주가 맡는다


async def test_새로고침해도_인터뷰가_이어진다(client):
    """질문이 메모리에만 있으면 새로고침 한 번에 프로젝트가 영영 멈춘다."""
    project_id = await _create(client)
    # 서버가 재시작된 것과 같은 상태 — 실행 상태가 사라진다.
    client.app.state.runner = PlanRunner(FakePlanner())

    body = (await client.get(f"/projects/{project_id}")).json()
    assert body["generation"]["status"] == "awaiting_clarify"
    assert body["generation"]["questions"][0]["field"] == "blueprint"

    await _answer_interview(client, project_id, blueprint="되살아난 인터뷰")
    body = (await client.get(f"/projects/{project_id}")).json()
    assert body["generation"]["status"] == "done"
    assert len(body["tickets"]) == 4


async def test_추측한_값은_인터뷰에서_같이_묻는다(client):
    client.app.state.runner = PlanRunner(FakePlanner(missing=["hours_per_week"]))
    project_id = await _create(client)

    body = (await client.get(f"/projects/{project_id}")).json()
    fields = [q["field"] for q in body["generation"]["questions"]]
    assert fields[-1] == "hours_per_week"

    await _answer_interview(client, project_id, hours_per_week="주 15시간")
    body = (await client.get(f"/projects/{project_id}")).json()
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
