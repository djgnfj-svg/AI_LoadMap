"""프로젝트 API (SPEC §3.5)."""

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app import auth, db
from app.graphs import interview as interview_rules
from app.graphs.persist import create_project
from app.models.schemas import (
    Blueprint,
    BlueprintConfirmRequest,
    ClarifyAnswerRequest,
    InterviewTurn,
    PlacementDiff,
    PlacementRequest,
    ProjectCreateRequest,
    ReplanApplyRequest,
    ReplanChange,
    SuccessCriterion,
)
from app.services.placement_context import load_placement_context
from app.services.replan_apply import apply_changes

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
            conn, user_id=str(user["id"]), goal_text=req.goal_text, domain=req.domain
        )
    # 고른 도메인을 그래프에 함께 넘긴다 — intake 의 추측보다 이 값이 이긴다.
    request.app.state.runner.start(
        project_id, req.goal_text, _known(req), domain=req.domain
    )
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
            "select goal_text, constraints, interview, domain from projects where id = $1",
            project_id,
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
        domain=run.domain if run else project["domain"],
    )
    return {"project_id": str(project_id), "status": "running"}


@router.post("/{project_id}/blueprint")
async def confirm_blueprint(
    project_id: uuid.UUID,
    req: BlueprintConfirmRequest,
    request: Request,
    user=Depends(auth.current_user),  # noqa: ANN001
) -> dict:
    """완성 기준을 **사용자가** 확정한다 (SPEC §3.3).

    AI 가 쓴 초안을 그대로 받아도 되고, 고쳐 써도 되고, 지워도 되고, 새로 넣어도
    된다. 확정하기 전에는 계획을 만들지 않는다 — 무엇이 「끝」인지는 목표를 가진
    사람만 정할 수 있기 때문이다.

    key 는 여기서 다시 매긴다. 사용자가 순서를 바꾸거나 지운 뒤에도 sc1..scN 이
    빈틈없이 이어져야 주(covers)와의 대응이 읽힌다.
    """
    criteria = [
        SuccessCriterion(key=f"sc{i}", text=text.strip())
        for i, text in enumerate((t for t in req.criteria if t.strip()), start=1)
    ]
    blueprint = Blueprint(summary=req.summary.strip(), criteria=criteria, confirmed=True)

    async with db.transaction() as conn:
        await auth.assert_owns_project(conn, project_id, user)
        project = await conn.fetchrow(
            "select goal_text, constraints, interview, domain from projects where id = $1",
            project_id,
        )
        ticket_count = await conn.fetchval(
            "select count(*) from tickets where project_id = $1", project_id
        )
        if ticket_count:
            raise HTTPException(409, "이미 계획이 만들어진 프로젝트다.")
        domain = req.domain or project["domain"]
        # 확정 사실을 먼저 남긴다. 이 뒤 그래프가 실패해도 사용자가 쓴 것은 남는다.
        await conn.execute(
            "update projects set blueprint = $2, domain = $3 where id = $1",
            project_id,
            blueprint.model_dump(),
            domain,
        )

    runner = request.app.state.runner
    run = runner.get(project_id)
    runner.start(
        project_id,
        run.goal_text if run else project["goal_text"],
        run.known if run else _known_from(project["constraints"]),
        interview=run.interview if run else _interview(project),
        blueprint=blueprint,
        domain=domain,
    )
    return {"project_id": str(project_id), "status": "running"}


def _interview(project) -> list[InterviewTurn]:  # noqa: ANN001
    return [InterviewTurn(**t) for t in (project["interview"] or [])]


def _known_from(constraints) -> dict:  # noqa: ANN001
    """저장된 제약을 intake 에 「이미 아는 값」으로 되돌려준다 (재시작 뒤 이어가기)."""
    return {k: v for k, v in (constraints or {}).items() if v is not None}


def _generation(  # noqa: ANN001
    run, turns: list[InterviewTurn], blueprint: Blueprint, *, has_plan: bool
) -> dict:
    """생성 진행 상태. 메모리에 실행이 없으면 DB 의 인터뷰·청사진이 답한다.

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
    if not has_plan:
        waiting = interview_rules.pending(turns)
        if waiting:
            return {
                "status": "awaiting_clarify",
                "questions": [q.model_dump() for q in waiting],
                "repairs": [],
                "error": None,
            }
        # 인터뷰는 끝났는데 청사진을 아직 확정하지 않았다.
        if turns and not blueprint.confirmed:
            return {"status": "awaiting_blueprint", "questions": [], "repairs": [], "error": None}
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
        "generation": _generation(
            run, turns, Blueprint(**(project["blueprint"] or {})), has_plan=bool(tickets)
        ),
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


# ─────────────────────────────────────────────────────────────
# 티켓 투입 (SPEC §3.7) — 만들다 생긴 일을 받아 자리를 잡아 준다
# ─────────────────────────────────────────────────────────────
async def _assert_owns(conn, project_id: uuid.UUID, user) -> None:  # noqa: ANN001
    """남의 프로젝트는 403 이 아니라 404 다 — 403 은 그 id 가 실재함을 알려 준다."""
    owned = await conn.fetchval(
        "select 1 from projects where id = $1 and user_id = $2", project_id, user["id"]
    )
    if not owned:
        raise HTTPException(404, "없는 프로젝트다.")


@router.post("/{project_id}/tickets", status_code=201)
async def place_ticket(
    project_id: uuid.UUID,
    req: PlacementRequest,
    request: Request,
    user=Depends(auth.current_user),
) -> dict:  # noqa: ANN001
    """새로 생긴 일 하나를 받아 자리를 정한다. **아직 적용하지 않는다.**

    결과는 승인 대기 상태로 저장된다 — AI 가 계획을 말없이 바꾸지 않는 것이
    이 제품의 규칙이다 (청사진 확정 · 재설계 diff 와 같은 결).
    """
    title = req.title.strip()
    if len(title) < 2:
        raise HTTPException(400, "무슨 일인지 한 줄은 적어야 한다.")

    graph = request.app.state.place_graph
    async with db.transaction() as conn:
        await _assert_owns(conn, project_id, user)
        # 계획이 있는지부터 본다. 인터뷰 중인 프로젝트는 제약도 비어 있어서
        # 컨텍스트를 읽는 것 자체가 터진다.
        if not await conn.fetchval(
            "select count(*) from tasks where project_id = $1", project_id
        ):
            raise HTTPException(409, "아직 계획이 없다. 로드맵부터 만들자.")

        project = await conn.fetchrow(
            "select domain from projects where id = $1", project_id
        )
        ctx = await load_placement_context(conn, project_id)

        final = await graph.ainvoke(
            {
                "context": ctx,
                "domain": project["domain"],
                "title": title,
                "body": req.body,
                "attempt": 0,
            }
        )
        diff: PlacementDiff = final["diff"]
        session_id = await conn.fetchval(
            "insert into replan_sessions (project_id, diff_json) values ($1, $2) "
            "returning id",
            project_id,
            diff.model_dump(mode="json"),
        )

    return {"session_id": str(session_id), "diff": diff.model_dump(mode="json")}


@router.post("/{project_id}/tickets/{session_id}/apply")
async def apply_placement(
    project_id: uuid.UUID,
    session_id: uuid.UUID,
    req: ReplanApplyRequest,
    user=Depends(auth.current_user),
) -> dict:  # noqa: ANN001
    """항목별 승인. 자리를 거절하면 티켓 자체가 안 들어간다."""
    async with db.transaction() as conn:
        await _assert_owns(conn, project_id, user)
        session = await conn.fetchrow(
            "select * from replan_sessions where id = $1 and project_id = $2 "
            "and review_day_id is null and applied = false",
            session_id,
            project_id,
        )
        if session is None:
            raise HTTPException(404, "적용할 배치 결과가 없다.")

        diff = PlacementDiff(**session["diff_json"])
        changes: list[ReplanChange] = diff.changes
        approved = set(req.approved)
        unknown = approved - {c.id for c in changes}
        if unknown:
            raise HTTPException(400, f"모르는 변경 id: {', '.join(sorted(unknown))}")

        result = await apply_changes(
            conn, project_id=project_id, changes=changes, approved_ids=approved
        )
        await conn.execute(
            "update replan_sessions set applied = true where id = $1", session_id
        )

    return {
        "session_id": str(session_id),
        "approved": sorted(approved),
        "rejected": sorted({c.id for c in changes} - approved),
        **result,
    }
