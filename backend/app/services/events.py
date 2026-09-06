"""이벤트 기록 (SPEC §2.3). 모든 실패 감지의 원천이다.

티켓이 여러 노드에 걸쳐 있으면 노드마다 한 줄씩 남긴다.
§4.5 의 재점검 트리거가 node_id 로 집계하기 때문에, 한 줄만 남기면
나머지 노드의 신호가 사라진다.
"""

import uuid

import asyncpg

from app.models.schemas import EventType


async def record_event(
    conn: asyncpg.Connection,
    *,
    project_id: uuid.UUID,
    ticket_id: uuid.UUID | None,
    event_type: EventType,
    payload: dict | None = None,
) -> int:
    """이벤트를 남기고 기록된 행 수를 돌려준다."""
    node_ids: list[uuid.UUID] = []
    if ticket_id is not None:
        rows = await conn.fetch(
            "select node_id from ticket_node_links where ticket_id = $1", ticket_id
        )
        node_ids = [r["node_id"] for r in rows]

    targets: list[uuid.UUID | None] = node_ids or [None]
    await conn.executemany(
        "insert into events (project_id, ticket_id, node_id, type, payload) "
        "values ($1, $2, $3, $4, $5)",
        [(project_id, ticket_id, node_id, event_type, payload) for node_id in targets],
    )
    return len(targets)
