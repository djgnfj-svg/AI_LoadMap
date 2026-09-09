"""프로젝트 API (SPEC §3.5)."""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app import db
from app.config import get_settings
from app.graphs.persist import create_project
from app.models.schemas import ClarifyAnswerRequest, ProjectCreateRequest

router = APIRouter(prefix="/projects", tags=["projects"])

_KNOWN_FIELDS = ("duration_weeks", "hours_per_week", "level", "stack", "team_size")


def _known(req: ProjectCreateRequest) -> dict:
    return {f: getattr(req, f) for f in _KNOWN_FIELDS if getattr(req, f) is not None}


@router.post("", status_code=201)
async def create(req: ProjectCreateRequest, request: Request) -> dict:
    """목표 입력 -> 생성 그래프 시작. 진행 상황은 /projects/{id}/stream 에서 본다."""
    settings = get_settings()
    async with db.transaction() as conn:
        project_id = await create_project(
            conn, user_id=settings.demo_user_id, goal_text=req.goal_text
        )
    request.app.state.runner.start(project_id, req.goal_text, _known(req))
    return {"project_id": str(project_id), "status": "running"}


@router.get("/{project_id}/stream")
async def stream(project_id: uuid.UUID, request: Request) -> EventSourceResponse:
    """SSE — 생성 그래프 진행 상황."""
    run = request.app.state.runner.get(project_id)
    if run is None:
        raise HTTPException(404, "진행 중인 생성이 없다.")

    async def gen():
        while True:
            try:
                event = await asyncio.wait_for(run.queue.get(), timeout=120)
            except TimeoutError:
                yield {"event": "ping", "data": "{}"}
                continue
            if event.get("event") == "__eof__":
                break
            yield {"event": event["event"], "data": _json(event)}

    return EventSourceResponse(gen())


@router.post("/{project_id}/clarify")
async def clarify(
    project_id: uuid.UUID, req: ClarifyAnswerRequest, request: Request
) -> dict:
    """clarify 응답 제출 -> 같은 목표로 그래프를 다시 돌린다 (SPEC §0.3 — clarify 1회 고정)."""
    runner = request.app.state.runner
    run = runner.get(project_id)
    if run is None:
        raise HTTPException(404, "진행 중인 생성이 없다.")
    if run.status != "awaiting_clarify":
        raise HTTPException(409, f"응답을 받을 상태가 아니다: {run.status}")
    runner.start(project_id, run.goal_text, run.known, clarify_answers=req.answers)
    return {"project_id": str(project_id), "status": "running"}


@router.get("/{project_id}")
async def get_project(project_id: uuid.UUID, request: Request) -> dict:
    """로드맵 + 아키텍처 전체 조회. 노드 상태는 §4.4 뷰에서 계산된 값을 쓴다."""
    async with db.acquire() as conn:
        project = await conn.fetchrow("select * from projects where id = $1", project_id)
        if project is None:
            raise HTTPException(404, "없는 프로젝트다.")

        goals = await conn.fetch(
            "select * from weekly_goals where project_id = $1 order by week_index nulls last",
            project_id,
        )
        tasks = await conn.fetch(
            "select * from tasks where project_id = $1 order by task_number nulls last",
            project_id,
        )
        tickets = await conn.fetch(
            "select * from tickets where project_id = $1 order by ticket_number nulls last",
            project_id,
        )
        deps = await conn.fetch(
            """
            select d.* from ticket_dependencies d
            join tickets t on t.id = d.ticket_id
            where t.project_id = $1
            """,
            project_id,
        )
        nodes = await conn.fetch(
            """
            select n.*, s.progress, s.delayed_tickets, s.ticket_count,
                   s.status as computed_status
            from arch_nodes n
            join v_node_status s on s.node_id = n.id
            where n.project_id = $1
            order by n.node_key
            """,
            project_id,
        )
        edges = await conn.fetch(
            "select * from arch_edges where project_id = $1", project_id
        )
        links = await conn.fetch(
            """
            select l.* from ticket_node_links l
            join tickets t on t.id = l.ticket_id
            where t.project_id = $1
            """,
            project_id,
        )

    run = request.app.state.runner.get(project_id)
    return {
        "project": _row(project),
        "generation": {
            "status": run.status if run else "done",
            "questions": [q.model_dump() for q in run.questions] if run else [],
            "repairs": run.repairs if run else [],
            "error": run.error if run else None,
        },
        "weekly_goals": [_row(r) for r in goals],
        "tasks": [_row(r) for r in tasks],
        "tickets": [_row(r) for r in tickets],
        "ticket_dependencies": [_row(r) for r in deps],
        "arch_nodes": [_row(r) for r in nodes],
        "arch_edges": [_row(r) for r in edges],
        "ticket_node_links": [_row(r) for r in links],
    }


def _row(record) -> dict:  # noqa: ANN001
    return {k: _scalar(v) for k, v in dict(record).items()}


def _scalar(value):  # noqa: ANN001, ANN201
    import datetime

    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime.datetime | datetime.date):
        return value.isoformat()
    return value


def _json(event: dict) -> str:
    import json

    return json.dumps({k: v for k, v in event.items() if k != "event"}, ensure_ascii=False)
