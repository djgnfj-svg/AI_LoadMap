"""프로젝트 API (SPEC §3.5)."""

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app import auth, db
from app.graphs import interview as interview_rules
from app.graphs.persist import create_project
from app.models.schemas import ClarifyAnswerRequest, InterviewTurn, ProjectCreateRequest

router = APIRouter(prefix="/projects", tags=["projects"])

_KNOWN_FIELDS = ("duration_weeks", "hours_per_week", "level", "stack", "team_size")


def _known(req: ProjectCreateRequest) -> dict:
    return {f: getattr(req, f) for f in _KNOWN_FIELDS if getattr(req, f) is not None}


@router.get("")
async def list_projects(user=Depends(auth.current_user)) -> dict:  # noqa: ANN001
    """내 프로젝트 목록. 로그인하면 제일 먼저 그리는 화면이다.

    티켓 수와 완료 수를 같이 준다 — 목록에서 어느 것이 살아 있는지 보려면
    프로젝트마다 상세를 한 번씩 부르게 할 수 없다.
    """
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            select p.id, p.title, p.goal_text, p.status, p.start_date, p.created_at,
                   count(t.id)                                       as ticket_count,
                   count(t.id) filter (where t.status = 'resolved')  as resolved_count
            from projects p
            left join tickets t on t.project_id = p.id
            where p.user_id = $1
            group by p.id
            order by p.created_at desc
            """,
            user["id"],
        )
    return {"projects": [_row(r) for r in rows]}


@router.post("", status_code=201)
async def create(
    req: ProjectCreateRequest, request: Request, user=Depends(auth.current_user)
) -> dict:  # noqa: ANN001
    """목표 입력 -> 생성 그래프 시작. 진행 상황은 /projects/{id}/stream 에서 본다."""
    async with db.transaction() as conn:
        project_id = await create_project(
            conn, user_id=str(user["id"]), goal_text=req.goal_text
        )
    request.app.state.runner.start(project_id, req.goal_text, _known(req))
    return {"project_id": str(project_id), "status": "running"}


@router.get("/{project_id}/stream")
async def stream(
    project_id: uuid.UUID, request: Request, user=Depends(auth.current_user)
) -> EventSourceResponse:  # noqa: ANN001
    """SSE — 생성 그래프 진행 상황."""
    async with db.acquire() as conn:
        await auth.assert_owns_project(conn, project_id, user)
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
    project_id: uuid.UUID,
    req: ClarifyAnswerRequest,
    request: Request,
    user=Depends(auth.current_user),  # noqa: ANN001
) -> dict:
    """인터뷰 답변 제출 -> 받은 답을 얹어 그래프를 다시 돌린다 (SPEC §3.3).

    메모리의 실행 상태가 없어도 받는다. 문답은 `projects.interview` 에 있으므로
    새로고침한 사용자도, 서버가 재시작된 뒤에도 답을 이어서 낼 수 있다.
    """
    async with db.acquire() as conn:
        await auth.assert_owns_project(conn, project_id, user)
        project = await conn.fetchrow(
            "select goal_text, constraints, interview from projects where id = $1", project_id
        )
        ticket_count = await conn.fetchval(
            "select count(*) from tickets where project_id = $1", project_id
        )

    runner = request.app.state.runner
    run = runner.get(project_id)
    turns = _interview(project)

    if run is not None and run.status not in ("awaiting_clarify", "failed"):
        raise HTTPException(409, f"응답을 받을 상태가 아니다: {run.status}")
    if run is None:
        # 메모리에 실행이 없다 — 새로고침했거나 서버가 재시작됐다.
        if ticket_count:
            raise HTTPException(409, "이미 계획이 만들어진 프로젝트다.")
        if not interview_rules.pending(turns):
            raise HTTPException(404, "답을 기다리는 질문이 없다.")

    runner.start(
        project_id,
        run.goal_text if run else project["goal_text"],
        run.known if run else _known_from(project["constraints"]),
        clarify_answers=req.answers,
        interview=run.interview if run else turns,
    )
    return {"project_id": str(project_id), "status": "running"}


def _interview(project) -> list[InterviewTurn]:  # noqa: ANN001
    return [InterviewTurn(**t) for t in (project["interview"] or [])]


def _known_from(constraints) -> dict:  # noqa: ANN001
    """저장된 제약을 intake 에 「이미 아는 값」으로 되돌려준다 (재시작 뒤 이어가기)."""
    return {k: v for k, v in (constraints or {}).items() if v is not None}


def _generation(run, turns: list[InterviewTurn], *, has_plan: bool) -> dict:  # noqa: ANN001
    """생성 진행 상태. 메모리에 실행이 없으면 DB 의 인터뷰가 답한다.

    전에는 실행이 없으면 무조건 "done" 이었다. 그래서 인터뷰 도중 새로고침하면
    티켓 0개짜리 프로젝트가 「완성됨」으로 보이고 되살릴 방법이 없었다.
    """
    if run is not None:
        return {
            "status": run.status,
            "questions": [q.model_dump() for q in run.questions],
            "repairs": run.repairs,
            "error": run.error,
        }
    waiting = interview_rules.pending(turns)
    if waiting and not has_plan:
        return {
            "status": "awaiting_clarify",
            "questions": [q.model_dump() for q in waiting],
            "repairs": [],
            "error": None,
        }
    return {"status": "done", "questions": [], "repairs": [], "error": None}


@router.get("/{project_id}")
async def get_project(
    project_id: uuid.UUID, request: Request, user=Depends(auth.current_user)
) -> dict:  # noqa: ANN001
    """로드맵 + 아키텍처 전체 조회. 노드 상태는 §4.4 뷰에서 계산된 값을 쓴다."""
    async with db.acquire() as conn:
        project = await conn.fetchrow(
            "select * from projects where id = $1 and user_id = $2", project_id, user["id"]
        )
        if project is None:
            # 남의 프로젝트도 여기로 온다 — 있는지 없는지 알려 줄 이유가 없다.
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
    turns = _interview(project)
    return {
        "project": _row(project),
        "generation": _generation(run, turns, has_plan=bool(tickets)),
        # 인터뷰 전문. 사용자가 자기 계획의 근거를 되짚을 수 있어야 한다.
        "interview": [t.model_dump() for t in turns],
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
