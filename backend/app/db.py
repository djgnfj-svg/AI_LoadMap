"""DB 접근. Supabase(PostgreSQL) 에 asyncpg 로 직접 붙는다.

ORM 을 두지 않는 이유: 이 제품의 실패 감지는 전부 SQL 집계다 (R2).
집계 쿼리가 일급 시민이어야 해서 SQL 을 그대로 쓴다.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

from app.config import get_settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=get_settings().database_url,
            min_size=1,
            max_size=10,
            init=_init_connection,
        )
    return _pool


async def _init_connection(conn: asyncpg.Connection) -> None:
    # jsonb 를 파이썬 dict 로 그대로 주고받는다.
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB 풀이 초기화되지 않았다. init_pool() 을 먼저 불러라.")
    return _pool


@asynccontextmanager
async def acquire() -> AsyncIterator[asyncpg.Connection]:
    async with get_pool().acquire() as conn:
        yield conn


@asynccontextmanager
async def transaction() -> AsyncIterator[asyncpg.Connection]:
    async with get_pool().acquire() as conn, conn.transaction():
        yield conn
