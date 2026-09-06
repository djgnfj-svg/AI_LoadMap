"""티켓 API (SPEC §3.5, §4.3 상태 전이).

`missed` 는 여기 없다. 상태가 아니라 스케줄러가 남기는 이벤트다 (R4).
"""

import uuid
from datetime import date

from fastapi import APIRouter, Body, HTTPException

from app import db
from app.models.schemas import TicketPatchRequest
from app.services.events import record_event
from app.services.node_status import sync_node_status

router = APIRouter(prefix="/tickets", tags=["tickets"])

# action -> (다음 status, 남길 이벤트). None 이면 status 를 바꾸지 않는다.
_TRANSITIONS: dict[str, tuple[str | None, str]] = {
    "start": ("doing", "started"),
    "complete": ("done", "completed"),
    "block": ("blocked", "blocked"),
    "unblock": ("doing", "started"),
    "defer": (None, "deferred"),  # 연기해도 status 는 유지된다 (R4)
}


@router.patch("/{ticket_id}")
async def patch_ticket(ticket_id: uuid.UUID, req: TicketPatchRequest) -> dict:
    next_status, event_type = _TRANSITIONS[req.action]

    async with db.transaction() as conn:
        ticket = await conn.fetchrow("select * from tickets where id = $1", ticket_id)
        if ticket is None:
            raise HTTPException(404, "없는 티켓이다.")
        project_id = ticket["project_id"]

        if req.action == "defer":
            new_due = date.fromisoformat(req.new_due_date) if req.new_due_date else None
            await conn.execute(
                """
                update tickets
                set delay_count = delay_count + 1,
                    due_date = coalesce($2, due_date)
                where id = $1
                """,
                ticket_id,
                new_due,
            )
        elif req.action == "complete":
            await conn.execute(
                "update tickets set status = 'done', completed_at = now(), "
                "blocked_reason = null where id = $1",
                ticket_id,
            )
        elif req.action == "block":
            if not req.reason:
                raise HTTPException(400, "막힘 사유가 필요하다.")
            await conn.execute(
                "update tickets set status = 'blocked', blocked_reason = $2 where id = $1",
                ticket_id,
                req.reason,
            )
        else:
            await conn.execute(
                "update tickets set status = $2, blocked_reason = null where id = $1",
                ticket_id,
                next_status,
            )

        payload = {}
        if req.reason:
            payload["reason"] = req.reason
        if req.action == "defer" and req.new_due_date:
            payload["new_due_date"] = req.new_due_date

        await record_event(
            conn,
            project_id=project_id,
            ticket_id=ticket_id,
            event_type=event_type,  # type: ignore[arg-type]
            payload=payload or None,
        )
        # SPEC §2.5 — 티켓 완료가 즉시 노드 상태로 반영된다.
        changed = await sync_node_status(conn, project_id)
        updated = await conn.fetchrow("select * from tickets where id = $1", ticket_id)

    return {
        "ticket": {
            "id": str(updated["id"]),
            "status": updated["status"],
            "delay_count": updated["delay_count"],
            "due_date": updated["due_date"].isoformat() if updated["due_date"] else None,
            "blocked_reason": updated["blocked_reason"],
        },
        "node_changes": changed,
    }


@router.post("/{ticket_id}/block")
async def block_ticket(ticket_id: uuid.UUID, reason: str = Body(..., embed=True)) -> dict:
    """막힘 사유 한 줄 입력 (SPEC §2.3 — 마감 24시간 경과 알람의 응답)."""
    return await patch_ticket(ticket_id, TicketPatchRequest(action="block", reason=reason))
