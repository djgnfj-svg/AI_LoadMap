"""재점검 세션 API (SPEC §3.5, §2.4).

§2.4 의 4단계가 그대로 엔드포인트가 된다.
  1. 집계 제시 (AI 아님, 숫자)  -> GET  /reviews/{id}
  2. 진단 (AI)                  -> POST /reviews/{id}/run
  3. 부분 재설계 (AI)           -> 같은 호출
  4. diff 승인                  -> POST /reviews/{id}/apply
"""

import uuid
from datetime import date

from fastapi import APIRouter, Body, HTTPException, Request

from app import db
from app.models.schemas import ReplanApplyRequest, ReplanChange, ReplanDiff
from app.services.replan_apply import apply_changes
from app.services.replan_context import load_replan_context

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("/{review_day_id}")
async def get_review(review_day_id: uuid.UUID) -> dict:
    """재점검 세션 조회. 아직 안 돌렸으면 집계 숫자만 돌려준다 (§2.4 1단계)."""
    async with db.acquire() as conn:
        try:
            ctx = await load_replan_context(conn, review_day_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

        review = await conn.fetchrow("select * from review_days where id = $1", review_day_id)
        session = await conn.fetchrow(
            "select * from replan_sessions where review_day_id = $1 "
            "order by created_at desc limit 1",
            review_day_id,
        )

    return {
        "review_day": {
            "id": str(review["id"]),
            "project_id": str(review["project_id"]),
            "node_id": str(review["node_id"]) if review["node_id"] else None,
            "scheduled_date": review["scheduled_date"].isoformat(),
            "trigger_reason": review["trigger_reason"],
            "status": review["status"],
            "postponed_count": review["postponed_count"],
        },
        "signals": ctx.signals.model_dump(),
        "session": _session_row(session) if session else None,
    }


@router.post("/{review_day_id}/run")
async def run_review(review_day_id: uuid.UUID, request: Request) -> dict:
    """재설계 그래프 실행 (SPEC §3.4). 결과는 승인 대기 상태로 저장된다."""
    graph = request.app.state.replan_graph
    async with db.transaction() as conn:
        try:
            ctx = await load_replan_context(conn, review_day_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

        if not ctx.weeks:
            raise HTTPException(409, "재설계할 계획이 없다.")

        final = await graph.ainvoke({"context": ctx, "attempt": 0})
        diff: ReplanDiff = final["diff"]

        session_id = await conn.fetchval(
            """
            insert into replan_sessions
              (review_day_id, project_id, diagnosis, scope_weekly_goal_id, diff_json)
            values ($1, $2, $3, $4, $5)
            returning id
            """,
            review_day_id,
            ctx.project_id,
            diff.diagnosis,
            uuid.UUID(diff.scope_weekly_goal_id),
            diff.model_dump(mode="json"),
        )

    return {"session_id": str(session_id), "diff": diff.model_dump(mode="json")}


@router.post("/{review_day_id}/apply")
async def apply_review(review_day_id: uuid.UUID, req: ReplanApplyRequest) -> dict:
    """diff 항목별 승인/거절 (§2.4 4단계). 승인한 것만 계획에 들어간다."""
    async with db.transaction() as conn:
        session = await conn.fetchrow(
            "select * from replan_sessions where review_day_id = $1 and applied = false "
            "order by created_at desc limit 1",
            review_day_id,
        )
        if session is None:
            raise HTTPException(404, "적용할 재설계 결과가 없다. 먼저 /run 을 부르자.")

        diff = ReplanDiff(**session["diff_json"])
        changes: list[ReplanChange] = diff.changes
        approved = set(req.approved)
        unknown = approved - {c.id for c in changes}
        if unknown:
            raise HTTPException(400, f"모르는 변경 id: {', '.join(sorted(unknown))}")

        result = await apply_changes(
            conn,
            project_id=session["project_id"],
            changes=changes,
            approved_ids=approved,
        )
        await conn.execute(
            "update replan_sessions set applied = true where id = $1", session["id"]
        )
        await conn.execute(
            "update review_days set status = 'done' where id = $1", review_day_id
        )
        # 이 재점검일에 걸린 알람은 처리된 것으로 본다.
        await conn.execute(
            "update alerts set acknowledged = true where review_day_id = $1", review_day_id
        )

    return {
        "session_id": str(session["id"]),
        "approved": sorted(approved),
        "rejected": sorted({c.id for c in changes} - approved),
        **result,
    }


@router.patch("/{review_day_id}")
async def postpone(review_day_id: uuid.UUID, scheduled_date: str = Body(..., embed=True)) -> dict:
    """날짜 변경만 가능하다. 삭제는 없다 (§2.4).

    미룬 사실도 기록한다 — 재점검일을 계속 미루는 것 자체가 신호다.
    """
    new_date = date.fromisoformat(scheduled_date)
    async with db.transaction() as conn:
        row = await conn.fetchrow(
            """
            update review_days
            set scheduled_date = $2, postponed_count = postponed_count + 1, status = 'scheduled'
            where id = $1
            returning id, project_id, node_id, scheduled_date, postponed_count
            """,
            review_day_id,
            new_date,
        )
        if row is None:
            raise HTTPException(404, "없는 재점검일이다.")
        await conn.execute(
            "insert into events (project_id, node_id, type, payload) "
            "values ($1, $2, 'deferred', $3)",
            row["project_id"],
            row["node_id"],
            {"review_day_id": str(review_day_id), "scheduled_date": new_date.isoformat()},
        )
    return {
        "id": str(row["id"]),
        "scheduled_date": row["scheduled_date"].isoformat(),
        "postponed_count": row["postponed_count"],
    }


def _session_row(record) -> dict:  # noqa: ANN001
    return {
        "id": str(record["id"]),
        "diagnosis": record["diagnosis"],
        "applied": record["applied"],
        "created_at": record["created_at"].isoformat(),
        "diff": record["diff_json"],
    }
