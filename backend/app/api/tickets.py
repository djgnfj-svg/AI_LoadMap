"""티켓 API (SPEC §3.5, §4.3 상태 전이).

`missed` 는 여기 없다. 상태가 아니라 스케줄러가 남기는 이벤트다 (R4).

⚠ 「막힘」도 상태가 아니다. 상태 낱말은 open·claimed·resolved·parked 넷뿐이고,
parked 는 접힘(의도적으로 미룸)이지 막힘이 아니다. 막혔다는 것은 잡고 있다가
멈췄다는 뜻이라 status 는 claimed 로 두고, 사유를 blocked_reason 한 줄이 든다.
"막힌 티켓"을 찾는 쪽은 status 가 아니라 blocked_reason 을 본다.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Body, HTTPException

from app import db
from app.models.schemas import TicketPatchRequest
from app.services.events import record_event
from app.services.node_status import sync_node_status
from app.services.task_status import sync_task_status

router = APIRouter(prefix="/tickets", tags=["tickets"])

# action -> (다음 status, 남길 이벤트). None 이면 status 를 바꾸지 않는다.
_TRANSITIONS: dict[str, tuple[str | None, str]] = {
    "start": ("claimed", "started"),
    "complete": ("resolved", "completed"),
    "block": ("claimed", "blocked"),   # 상태는 그대로 잡고 있는 것. 사유만 붙는다
    "unblock": ("claimed", "started"),
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
                "update tickets set status = 'resolved', completed_at = now(), "
                "blocked_reason = null where id = $1",
                ticket_id,
            )
        elif req.action == "block":
            if not req.reason:
                raise HTTPException(400, "막힘 사유가 필요하다.")
            await conn.execute(
                "update tickets set status = 'claimed', blocked_reason = $2 where id = $1",
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
        # 태스크 상태도 그 안의 티켓에서 되읽는다 (§2.1).
        tasks_changed = await sync_task_status(conn, project_id)
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
        "task_changes": tasks_changed,
    }


@router.post("/{ticket_id}/block")
async def block_ticket(ticket_id: uuid.UUID, reason: str = Body(..., embed=True)) -> dict:
    """막힘 사유 한 줄 입력 (SPEC §2.3 — 마감 24시간 경과 알람의 응답)."""
    return await patch_ticket(ticket_id, TicketPatchRequest(action="block", reason=reason))
