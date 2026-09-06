"""테스트 공용 픽스처.

DB 가 필요한 테스트는 TEST_DATABASE_URL(기본: 로컬 Postgres)에 붙는다.
붙을 수 없으면 skip 한다 — 순수 로직 테스트(critic, repair, 그래프)는 DB 없이 돈다.
"""

import asyncio
import os
import pathlib
import uuid

import asyncpg
import pytest

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations"
ADMIN_DSN = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres@127.0.0.1:55432/postgres"
)


def _dsn_for(db_name: str) -> str:
    base, _, _ = ADMIN_DSN.rpartition("/")
    return f"{base}/{db_name}"


async def _create_db(db_name: str) -> str:
    admin = await asyncpg.connect(ADMIN_DSN, timeout=3)
    await admin.execute(f'create database "{db_name}"')
    await admin.close()

    dsn = _dsn_for(db_name)
    conn = await asyncpg.connect(dsn)
    for path in sorted(MIGRATIONS.glob("*.sql")):
        await conn.execute(path.read_text())
    await conn.close()
    return dsn


async def _drop_db(db_name: str) -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    await admin.execute(
        "select pg_terminate_backend(pid) from pg_stat_activity where datname = $1", db_name
    )
    await admin.execute(f'drop database if exists "{db_name}"')
    await admin.close()


@pytest.fixture(scope="session")
def test_dsn():
    """마이그레이션이 적용된 일회용 DB 를 만들고 끝나면 지운다.

    이벤트 루프 스코프 문제를 피하려고 동기 픽스처 안에서 asyncio.run 을 쓴다.
    """
    db_name = f"rp_test_{uuid.uuid4().hex[:10]}"
    try:
        dsn = asyncio.run(_create_db(db_name))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"테스트용 Postgres 에 붙을 수 없다: {exc}")

    yield dsn

    asyncio.run(_drop_db(db_name))


@pytest.fixture
async def conn(test_dsn):
    """테스트마다 롤백되는 커넥션."""
    import json

    connection = await asyncpg.connect(test_dsn)
    await connection.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    tx = connection.transaction()
    await tx.start()
    try:
        yield connection
    finally:
        await tx.rollback()
        await connection.close()
