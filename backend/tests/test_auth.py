"""로그인 (0004 / app/auth.py).

세션 쿠키의 서명·만료는 DB 없이 돌고, 소유 격리는 실제 DB 위에서 본다.
"""

import time

import httpx
import pytest

from app import auth
from app.config import get_settings


@pytest.fixture(autouse=True)
def _fixed_secret(monkeypatch):
    """서명 키를 고정한다. 안 그러면 프로세스마다 임시 키가 새로 난다."""
    monkeypatch.setenv("SESSION_SECRET", "test-secret-키-하나")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ─────────────────────────────────────────────────────────────
# 세션 쿠키 (DB 불필요)
# ─────────────────────────────────────────────────────────────


def test_발급한_세션은_다시_읽힌다():
    uid = "11111111-1111-1111-1111-111111111111"
    assert auth.read_session(auth.issue_session(uid)) == uid


def test_서명이_틀리면_안_읽힌다():
    token = auth.issue_session("11111111-1111-1111-1111-111111111111")
    body, _ = token.split(".")
    assert auth.read_session(f"{body}.가짜서명") is None


def test_payload_를_고치면_서명이_깨진다():
    """uid 를 남의 것으로 바꿔치기하는 것이 이 검사의 이유다."""
    import base64
    import json

    other = json.dumps({"uid": "22222222-2222-2222-2222-222222222222", "exp": 2**31})
    forged = base64.urlsafe_b64encode(other.encode()).decode().rstrip("=")
    _, signature = auth.issue_session("11111111-1111-1111-1111-111111111111").split(".")
    assert auth.read_session(f"{forged}.{signature}") is None


def test_만료된_세션은_안_읽힌다(monkeypatch):
    token = auth.issue_session("11111111-1111-1111-1111-111111111111")
    real = time.time  # 패치 전에 잡아 둔다 — 람다 안에서 time.time 을 부르면 자기 자신이다.
    monkeypatch.setattr(time, "time", lambda: real() + 400 * 86400)
    assert auth.read_session(token) is None


@pytest.mark.parametrize("bad", [None, "", "점이없다", "너무.많은.점", "..", "x.y"])
def test_망가진_쿠키는_전부_None(bad):
    assert auth.read_session(bad) is None


# ─────────────────────────────────────────────────────────────
# API (DB 필요)
# ─────────────────────────────────────────────────────────────


@pytest.fixture
async def client(test_dsn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_dsn)
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    get_settings.cache_clear()

    from app.graphs.mock_planner import MockPlanner
    from app.main import create_app
    from app.services.planner_runs import PlanRunner

    app = create_app()
    app.state.runner = PlanRunner(MockPlanner())

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    get_settings.cache_clear()


async def test_로그인하지_않으면_목록을_못_본다(client):
    assert (await client.get("/projects")).status_code == 401


async def test_구글이_없으면_데모_로그인이_열린다(client):
    assert (await client.get("/auth/config")).json()["demo_login"] is True

    res = await client.post("/auth/demo")
    assert res.status_code == 200
    assert res.json()["user"]["email"] == "demo@localhost"

    me = await client.get("/auth/me")
    assert me.json()["user"]["email"] == "demo@localhost"


async def test_구글이_켜져_있으면_데모_문은_닫힌다(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "1234-abc.apps.googleusercontent.com")
    get_settings.cache_clear()
    assert (await client.post("/auth/demo")).status_code == 404
    assert (await client.get("/auth/config")).json()["google_enabled"] is True


async def test_로그아웃하면_다시_401(client):
    await client.post("/auth/demo")
    assert (await client.get("/projects")).status_code == 200
    await client.post("/auth/logout")
    assert (await client.get("/projects")).status_code == 401


async def _connect(dsn: str):
    """앱 풀과 같은 jsonb 코덱을 단 연결. constraints 가 dict 로 들어간다."""
    import json

    import asyncpg

    connection = await asyncpg.connect(dsn)
    await connection.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    return connection


async def _stranger_project(dsn: str, email: str) -> str:
    """남의 계정과 그 프로젝트를 실제로 커밋해 둔다.

    conn 픽스처는 매번 롤백되는 트랜잭션이라 앱이 쓰는 풀에서는 보이지 않는다.
    소유 격리를 보려면 양쪽이 같은 것을 봐야 한다.
    """
    from app.graphs.persist import create_project

    connection = await _connect(dsn)
    try:
        other = await connection.fetchval(
            "insert into users (email, display_name) values ($1, '남') returning id", email
        )
        return str(await create_project(connection, user_id=str(other), goal_text="남의 목표다"))
    finally:
        await connection.close()


async def test_남의_프로젝트는_없는_프로젝트다(client, test_dsn):
    """403 이 아니라 404 다 — 남의 로드맵이 있는지 없는지 알려 줄 이유가 없다."""
    stranger = await _stranger_project(test_dsn, "other@x")

    await client.post("/auth/demo")
    assert (await client.get(f"/projects/{stranger}")).status_code == 404


async def test_내_목록에는_내_것만_나온다(client, test_dsn):
    from app.graphs.persist import create_project

    stranger = await _stranger_project(test_dsn, "other2@x")
    connection = await _connect(test_dsn)
    try:
        mine = await create_project(
            connection, user_id=get_settings().demo_user_id, goal_text="내 목표다"
        )
    finally:
        await connection.close()

    await client.post("/auth/demo")
    ids = [p["id"] for p in (await client.get("/projects")).json()["projects"]]
    assert str(mine) in ids
    assert stranger not in ids
