"""알람 API (SPEC §3.5, §5 알람 화면)."""

import uuid
from datetime import date

from fastapi import APIRouter, Body, HTTPException

from app import db
from app.services import alerts as alert_service
from app.services import detection

router = APIRouter(tags=["alerts"])


@router.get("/projects/{project_id}/alerts")
async def list_alerts(project_id: uuid.UUID, include_read: bool = False) -> dict:
    """미확인 알람 목록. 강도 높은 것부터 (SPEC §2.3)."""
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            select a.*, t.title as ticket_title, n.label as node_label,
                   r.scheduled_date as review_date, r.status as review_status
            from alerts a
            left join tickets t     on t.id = a.ticket_id
            left join arch_nodes n  on n.id = a.node_id
            left join review_days r on r.id = a.review_day_id
            where a.project_id = $1 and ($2 or a.acknowledged = false)
            order by
              case a.severity when 'high' then 0 when 'medium' then 1 else 2 end,
              a.created_at desc
            """,
            project_id,
            include_read,
        )
        reviews = await conn.fetch(
            """
            select r.*, n.label as node_label, n.node_key
            from review_days r
            left join arch_nodes n on n.id = r.node_id
            where r.project_id = $1 and r.status = 'scheduled'
            order by r.scheduled_date
            """,
            project_id,
        )
    return {
        "alerts": [_row(r) for r in rows],
        "review_days": [_row(r) for r in reviews],
    }


@router.post("/alerts/{alert_id}/ack")
async def acknowledge(alert_id: uuid.UUID) -> dict:
    async with db.transaction() as conn:
        row = await conn.fetchrow(
            "update alerts set acknowledged = true where id = $1 returning id", alert_id
        )
    if row is None:
        raise HTTPException(404, "없는 알람이다.")
    return {"id": str(alert_id), "acknowledged": True}


@router.post("/projects/{project_id}/detect")
async def run_detection(project_id: uuid.UUID, today: str | None = Body(None, embed=True)) -> dict:
    """스케줄러 작업을 즉시 한 번 돌린다 (SPEC §3.6).

    데모와 개발용이다. 운영에서는 APScheduler 가 정해진 시각에 돌린다.
    감지는 전부 SQL 이므로 이 엔드포인트도 LLM 을 부르지 않는다 (R2).
    """
    day = date.fromisoformat(today) if today else None
    async with db.transaction() as conn:
        missed = await detection.record_missed_tickets(conn, day, project_id)
        created_reviews = await detection.ensure_review_days(conn, project_id, day)
        created_alerts = await alert_service.generate_alerts(conn, project_id, day)
        weekly = await alert_service.generate_weekly_review(conn, project_id, day)
        from app.services.node_status import sync_node_status

        node_changes = await sync_node_status(conn, project_id)
    return {
        "missed_events": missed,
        "review_days_created": len(created_reviews),
        "alerts_created": created_alerts + weekly,
        "node_changes": node_changes,
    }


def _row(record) -> dict:  # noqa: ANN001
    import datetime

    out = {}
    for k, v in dict(record).items():
        if isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, datetime.datetime | datetime.date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
