"""emit — 검증된 초안을 DB 에 저장한다 (SPEC §3.3).

그래프 안에서 저장하지 않고 여기서 하는 이유: 트랜잭션 경계를 그래프 밖에 두면
"검증까지 끝난 초안"과 "저장된 계획"을 분리해 테스트할 수 있다.

초안의 문자열 key 를 uuid 로 치환하는 곳도 여기다.
"""

import uuid
from datetime import date, timedelta

import asyncpg

from app.models.schemas import Constraints, PlanDraft

# React Flow 좌표 계산용 (SPEC §4.2 arch_nodes.position)
LAYER_ORDER = ["frontend", "backend", "data", "infra"]
_X_STEP = 260
_Y_STEP = 160


def layout_positions(draft: PlanDraft) -> dict[str, dict[str, int]]:
    """레이어별로 가로 정렬한 결정적 좌표. 프론트에서 다시 계산할 필요가 없다."""
    positions: dict[str, dict[str, int]] = {}
    per_layer: dict[str, int] = {}
    for node in draft.nodes:
        layer = node.layer if node.layer in LAYER_ORDER else "backend"
        col = per_layer.get(layer, 0)
        per_layer[layer] = col + 1
        positions[node.node_key] = {
            "x": col * _X_STEP,
            "y": LAYER_ORDER.index(layer) * _Y_STEP,
        }
    return positions


def _week_end(start: date, week_index: int) -> date:
    """week_index 주차의 마지막 날. 1주차 = 시작일 + 6일."""
    return start + timedelta(days=week_index * 7 - 1)


async def create_project(
    conn: asyncpg.Connection,
    *,
    user_id: str | None,
    goal_text: str,
    title: str = "(생성 중)",
    constraints: Constraints | None = None,
    start_date: date | None = None,
) -> uuid.UUID:
    """프로젝트 행을 먼저 만든다.

    생성 그래프가 돌기 전에 id 가 있어야 /projects/{id}/stream 과 /projects/{id}/clarify
    (SPEC §3.5) 가 성립한다. 트리는 emit 에서 persist_plan 이 채운다.
    """
    return await conn.fetchval(
        """
        insert into projects (user_id, title, goal_text, constraints, start_date)
        values ($1, $2, $3, $4, $5)
        returning id
        """,
        uuid.UUID(user_id) if user_id else None,
        title,
        goal_text,
        (constraints.model_dump() if constraints else {}),
        start_date or date.today(),
    )


async def persist_plan(
    conn: asyncpg.Connection,
    *,
    project_id: uuid.UUID,
    title: str,
    constraints: Constraints,
    draft: PlanDraft,
    start_date: date | None = None,
) -> uuid.UUID:
    """검증된 초안을 기존 프로젝트 행 아래에 한 트랜잭션으로 저장한다."""
    start = start_date or await conn.fetchval(
        "select start_date from projects where id = $1", project_id
    ) or date.today()

    await conn.execute(
        "update projects set title = $2, constraints = $3 where id = $1",
        project_id,
        title,
        constraints.model_dump(),
    )

    # ── 주 (관리 단위이자 최상위) ──────────────────────────────
    goal_ids: dict[str, uuid.UUID] = {}
    goal_target: dict[str, date] = {}
    for g in sorted(draft.weekly_goals, key=lambda x: x.week_index):
        target = _week_end(start, g.week_index)
        goal_target[g.key] = target
        goal_ids[g.key] = await conn.fetchval(
            """
            insert into weekly_goals (project_id, week_index, title, target_date)
            values ($1, $2, $3, $4)
            returning id
            """,
            project_id,
            g.week_index,
            g.title,
            target,
        )

    # ── 태스크 ─────────────────────────────────────────────────
    # 번호는 프로젝트 안에서 전역으로 센다. 2 주에 17 번 태스크가 있을 수 있다.
    task_ids: dict[str, uuid.UUID] = {}
    task_goal: dict[str, str] = {}
    for k in sorted(draft.tasks, key=lambda x: x.task_number):
        goal_id = goal_ids.get(k.weekly_goal_key)
        if goal_id is None:
            continue  # critic 이 잡았어야 할 끊긴 참조. 저장 단계에서는 조용히 버린다.
        task_goal[k.key] = k.weekly_goal_key
        task_ids[k.key] = await conn.fetchval(
            """
            insert into tasks (project_id, weekly_goal_id, task_number, title, description)
            values ($1, $2, $3, $4, $5)
            returning id
            """,
            project_id,
            goal_id,
            k.task_number,
            k.title,
            k.description or None,
        )

    # ── 티켓 ───────────────────────────────────────────────────
    # 마감일은 티켓이 든 태스크가 사는 주에서 온다.
    ticket_ids: dict[str, uuid.UUID] = {}
    for t in sorted(draft.tickets, key=lambda x: (x.task_key, x.ticket_number)):
        task_id = task_ids.get(t.task_key)
        if task_id is None:
            continue
        ticket_ids[t.key] = await conn.fetchval(
            """
            insert into tickets
              (task_id, project_id, ticket_number, title, body, est_minutes, due_date)
            values ($1, $2, $3, $4, $5, $6, $7)
            returning id
            """,
            task_id,
            project_id,
            t.ticket_number,
            t.title,
            t.body,
            t.est_minutes,
            goal_target.get(task_goal.get(t.task_key, "")),
        )

    dep_rows = [
        (ticket_ids[t.key], ticket_ids[dep])
        for t in draft.tickets
        if t.key in ticket_ids
        for dep in t.depends_on
        if dep in ticket_ids and dep != t.key
    ]
    if dep_rows:
        await conn.executemany(
            "insert into ticket_dependencies (ticket_id, depends_on) values ($1, $2) "
            "on conflict do nothing",
            dep_rows,
        )

    # ── 아키텍처 ───────────────────────────────────────────────
    positions = layout_positions(draft)
    node_ids: dict[str, uuid.UUID] = {}
    for n in draft.nodes:
        node_ids[n.node_key] = await conn.fetchval(
            """
            insert into arch_nodes (project_id, node_key, label, node_type, layer, position)
            values ($1, $2, $3, $4, $5, $6)
            returning id
            """,
            project_id,
            n.node_key,
            n.label,
            n.node_type,
            n.layer,
            positions.get(n.node_key, {"x": 0, "y": 0}),
        )

    edge_rows = [
        (project_id, node_ids[e.from_key], node_ids[e.to_key], e.label or None)
        for e in draft.edges
        if e.from_key in node_ids and e.to_key in node_ids and e.from_key != e.to_key
    ]
    if edge_rows:
        await conn.executemany(
            "insert into arch_edges (project_id, from_node, to_node, label) "
            "values ($1, $2, $3, $4) on conflict do nothing",
            edge_rows,
        )

    link_rows = [
        (ticket_ids[link.ticket_key], node_ids[link.node_key])
        for link in draft.links
        if link.ticket_key in ticket_ids and link.node_key in node_ids
    ]
    if link_rows:
        await conn.executemany(
            "insert into ticket_node_links (ticket_id, node_id) values ($1, $2) "
            "on conflict do nothing",
            link_rows,
        )

    # ── created 이벤트 (SPEC §2.3) ─────────────────────────────
    node_of_ticket = {
        link.ticket_key: node_ids[link.node_key]
        for link in draft.links
        if link.node_key in node_ids
    }
    event_rows = [
        (project_id, tid, node_of_ticket.get(key), "created", None)
        for key, tid in ticket_ids.items()
    ]
    if event_rows:
        await conn.executemany(
            "insert into events (project_id, ticket_id, node_id, type, payload) "
            "values ($1, $2, $3, $4, $5)",
            event_rows,
        )

    return project_id


async def load_draft(conn: asyncpg.Connection, project_id: uuid.UUID) -> PlanDraft:
    """DB 에 저장된 계획을 PlanDraft 로 되읽는다.

    key 로 uuid 문자열을 그대로 쓴다. critic 은 key 가 서로 맞는지만 보므로
    생성 그래프의 초안이든 DB 에서 읽은 계획이든 같은 검증이 그대로 돈다.
    """
    from app.models.schemas import (
        DraftEdge,
        DraftLink,
        DraftNode,
        DraftTask,
        DraftTicket,
        DraftWeeklyGoal,
    )

    goals = await conn.fetch(
        "select * from weekly_goals where project_id = $1 order by week_index", project_id
    )
    tasks = await conn.fetch(
        "select * from tasks where project_id = $1 order by task_number", project_id
    )
    tickets = await conn.fetch(
        "select * from tickets where project_id = $1 order by ticket_number", project_id
    )
    deps = await conn.fetch(
        "select d.* from ticket_dependencies d join tickets t on t.id = d.ticket_id "
        "where t.project_id = $1",
        project_id,
    )
    nodes = await conn.fetch("select * from arch_nodes where project_id = $1", project_id)
    edges = await conn.fetch("select * from arch_edges where project_id = $1", project_id)
    links = await conn.fetch(
        "select l.* from ticket_node_links l join tickets t on t.id = l.ticket_id "
        "where t.project_id = $1",
        project_id,
    )

    node_key_by_id = {n["id"]: n["node_key"] for n in nodes}
    depends = {}
    for d in deps:
        depends.setdefault(str(d["ticket_id"]), []).append(str(d["depends_on"]))

    return PlanDraft(
        weekly_goals=[
            DraftWeeklyGoal(
                key=str(g["id"]),
                week_index=g["week_index"],
                title=g["title"],
            )
            for g in goals
            if g["week_index"] is not None
        ],
        tasks=[
            DraftTask(
                key=str(k["id"]),
                weekly_goal_key=str(k["weekly_goal_id"]),
                task_number=k["task_number"],
                title=k["title"],
                description=k["description"] or "",
            )
            for k in tasks
            if k["weekly_goal_id"] is not None and k["task_number"] is not None
        ],
        tickets=[
            DraftTicket(
                key=str(t["id"]),
                task_key=str(t["task_id"]),
                ticket_number=t["ticket_number"],
                title=t["title"],
                body=t["body"] or "",
                est_minutes=t["est_minutes"],
                depends_on=depends.get(str(t["id"]), []),
            )
            for t in tickets
            if t["task_id"] is not None and t["ticket_number"] is not None
        ],
        nodes=[
            DraftNode(
                node_key=n["node_key"],
                label=n["label"],
                node_type=n["node_type"] or "service",
                layer=n["layer"] or "backend",
            )
            for n in nodes
        ],
        edges=[
            DraftEdge(
                from_key=node_key_by_id[e["from_node"]],
                to_key=node_key_by_id[e["to_node"]],
                label=e["label"] or "",
            )
            for e in edges
            if e["from_node"] in node_key_by_id and e["to_node"] in node_key_by_id
        ],
        links=[
            DraftLink(ticket_key=str(link["ticket_id"]), node_key=node_key_by_id[link["node_id"]])
            for link in links
            if link["node_id"] in node_key_by_id
        ],
    )
