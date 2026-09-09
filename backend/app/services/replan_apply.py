"""승인된 재설계 변경을 DB 에 적용한다 (SPEC §3.5 POST /reviews/{id}/apply).

사용자가 항목별로 고른 것만 적용한다 (§2.4 4단계). 거절한 항목은 흔적을 남기지 않는다.
승인하지 않은 항목이 남긴 참조(예: 지워진 티켓을 가리키는 선행 관계)는 조용히 건너뛴다.
"""

import uuid
from datetime import timedelta

import asyncpg

from app.models.schemas import ReplanChange
from app.services.node_status import sync_node_status


async def apply_changes(
    conn: asyncpg.Connection,
    *,
    project_id: uuid.UUID,
    changes: list[ReplanChange],
    approved_ids: set[str],
) -> dict:
    """승인된 변경만 적용하고, 적용 결과 요약을 돌려준다."""
    applied: list[str] = []
    skipped: list[str] = []

    for change in changes:
        if change.id not in approved_ids:
            continue
        handler = _HANDLERS.get(change.type)
        if handler is None:
            skipped.append(change.id)
            continue
        ok = await handler(conn, project_id, change.op)
        (applied if ok else skipped).append(change.id)

    node_changes = await sync_node_status(conn, project_id)
    return {"applied": applied, "skipped": skipped, "node_changes": node_changes}


async def _split_ticket(conn: asyncpg.Connection, project_id: uuid.UUID, op: dict) -> bool:
    original = await conn.fetchrow(
        "select * from tickets where id = $1 and project_id = $2",
        uuid.UUID(op["ticket_id"]),
        project_id,
    )
    if original is None:
        return False

    parts = op["parts"]
    await conn.execute(
        "update tickets set title = $2, est_minutes = $3 where id = $1",
        original["id"],
        parts[0]["title"],
        parts[0]["est_minutes"],
    )
    node_ids = [
        r["node_id"]
        for r in await conn.fetch(
            "select node_id from ticket_node_links where ticket_id = $1", original["id"]
        )
    ]

    prev = original["id"]
    # 조각은 원래 티켓 바로 뒤에 온다. 번호는 태스크 안에서 이어 붙인다.
    next_number = await conn.fetchval(
        "select coalesce(max(ticket_number), 0) from tickets where task_id = $1",
        original["task_id"],
    )
    for i, (new_id, part) in enumerate(
        zip(op["new_ticket_ids"], parts[1:], strict=True), start=1
    ):
        ticket_id = uuid.UUID(new_id)
        await conn.execute(
            """
            insert into tickets
              (id, task_id, project_id, ticket_number, title, body, est_minutes, due_date)
            values ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            ticket_id,
            original["task_id"],
            project_id,
            next_number + i,
            part["title"],
            original["body"],
            part["est_minutes"],
            original["due_date"],
        )
        await conn.execute(
            "insert into ticket_dependencies (ticket_id, depends_on) values ($1, $2) "
            "on conflict do nothing",
            ticket_id,
            prev,
        )
        for node_id in node_ids:
            await conn.execute(
                "insert into ticket_node_links (ticket_id, node_id) values ($1, $2) "
                "on conflict do nothing",
                ticket_id,
                node_id,
            )
        await conn.execute(
            "insert into events (project_id, ticket_id, node_id, type, payload) "
            "values ($1, $2, $3, 'created', $4)",
            project_id,
            ticket_id,
            node_ids[0] if node_ids else None,
            {"source": "replan", "split_from": str(original["id"]), "part": i + 1},
        )
        prev = ticket_id
    return True


async def _reduce_ticket(conn: asyncpg.Connection, project_id: uuid.UUID, op: dict) -> bool:
    result = await conn.execute(
        """
        update tickets set title = $3, body = coalesce(nullif($4, ''), body), est_minutes = $5
        where id = $1 and project_id = $2
        """,
        uuid.UUID(op["ticket_id"]),
        project_id,
        op["title"],
        op.get("body") or "",
        op["est_minutes"],
    )
    return result.endswith("1")


async def _drop_ticket(conn: asyncpg.Connection, project_id: uuid.UUID, op: dict) -> bool:
    # 이미 손댄 티켓은 지우지 않는다. 한 일을 되돌리는 건 재설계의 일이 아니다.
    result = await conn.execute(
        "delete from tickets where id = $1 and project_id = $2 and status = 'open'",
        uuid.UUID(op["ticket_id"]),
        project_id,
    )
    return result.endswith("1")


async def _add_ticket(conn: asyncpg.Connection, project_id: uuid.UUID, op: dict) -> bool:
    # 마감일은 태스크가 사는 주에서 온다.
    task = await conn.fetchrow(
        """
        select k.id, g.target_date
        from tasks k
        left join weekly_goals g on g.id = k.weekly_goal_id
        where k.id = $1 and k.project_id = $2
        """,
        uuid.UUID(op["task_id"]),
        project_id,
    )
    if task is None:
        return False

    next_number = await conn.fetchval(
        "select coalesce(max(ticket_number), 0) + 1 from tickets where task_id = $1",
        task["id"],
    )
    ticket_id = uuid.UUID(op["new_ticket_id"])
    await conn.execute(
        """
        insert into tickets
          (id, task_id, project_id, ticket_number, title, body, est_minutes, due_date)
        values ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        ticket_id,
        task["id"],
        project_id,
        next_number,
        op["title"],
        op["body"],
        op["est_minutes"],
        task["target_date"],
    )

    node_ids = []
    for node_key in op.get("node_keys") or []:
        node_id = await conn.fetchval(
            "select id from arch_nodes where project_id = $1 and node_key = $2",
            project_id,
            node_key,
        )
        if node_id:
            node_ids.append(node_id)
            await conn.execute(
                "insert into ticket_node_links (ticket_id, node_id) values ($1, $2) "
                "on conflict do nothing",
                ticket_id,
                node_id,
            )

    blocks = op.get("blocks_ticket_id")
    if blocks:
        await conn.execute(
            "insert into ticket_dependencies (ticket_id, depends_on) values ($1, $2) "
            "on conflict do nothing",
            uuid.UUID(blocks),
            ticket_id,
        )

    await conn.execute(
        "insert into events (project_id, ticket_id, node_id, type, payload) "
        "values ($1, $2, $3, 'created', $4)",
        project_id,
        ticket_id,
        node_ids[0] if node_ids else None,
        {"source": "replan"},
    )
    return True


async def _add_dependency(conn: asyncpg.Connection, project_id: uuid.UUID, op: dict) -> bool:
    both = await conn.fetchval(
        "select count(*) from tickets where project_id = $1 and id = any($2::uuid[])",
        project_id,
        [uuid.UUID(op["ticket_id"]), uuid.UUID(op["depends_on"])],
    )
    if both != 2:
        return False
    await conn.execute(
        "insert into ticket_dependencies (ticket_id, depends_on) values ($1, $2) "
        "on conflict do nothing",
        uuid.UUID(op["ticket_id"]),
        uuid.UUID(op["depends_on"]),
    )
    return True


async def _shift_week(conn: asyncpg.Connection, project_id: uuid.UUID, op: dict) -> bool:
    """§2.4 — 영향받는 후속 주 일정 자동 이월. 내용은 건드리지 않는다."""
    ids = [uuid.UUID(x) for x in op["weekly_goal_ids"]]
    days = timedelta(days=int(op["days"]))
    if not ids:
        return False
    await conn.execute(
        "update weekly_goals set target_date = target_date + $2 "
        "where id = any($1::uuid[]) and project_id = $3",
        ids,
        days,
        project_id,
    )
    # 티켓의 마감일은 그 티켓이 든 태스크가 사는 주를 따라간다.
    await conn.execute(
        """
        update tickets t set due_date = t.due_date + $2
        from tasks k
        where k.id = t.task_id and k.weekly_goal_id = any($1::uuid[])
        """,
        ids,
        days,
    )
    return True


_HANDLERS = {
    "split_ticket": _split_ticket,
    "reduce_ticket": _reduce_ticket,
    "drop_ticket": _drop_ticket,
    "add_ticket": _add_ticket,
    "add_dependency": _add_dependency,
    "shift_week": _shift_week,
}
