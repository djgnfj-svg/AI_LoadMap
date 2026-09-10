"""만들다 생긴 일 하나를 놓기 위해 계획 전체를 읽어 온다 (SPEC §3.7).

재설계(`replan_context.py`)와 다른 점은 **범위가 계획 전체**라는 것이다.
재설계는 지연이 쌓인 노드에서 시작해 주 하나만 다시 그린다(R3). 여기서는
어디에 놓일지를 아직 모르므로 주를 미리 고를 수 없다.

전부 SQL 이다. AI 는 여기 개입하지 않는다 (R2).
"""

import uuid
from dataclasses import dataclass, field

import asyncpg

from app.graphs.persist import load_draft
from app.models.schemas import Constraints, PlanDraft


@dataclass
class PlacementContext:
    project_id: uuid.UUID
    constraints: Constraints
    base_draft: PlanDraft
    # T1, T2... -> 티켓 행. LLM 은 uuid 대신 이 참조로 말한다.
    ref_to_ticket: dict[str, dict] = field(default_factory=dict)
    # K1, K2... -> 태스크 행. 새 티켓이 살 집이다.
    ref_to_task: dict[str, dict] = field(default_factory=dict)
    nodes: list[dict] = field(default_factory=list)

    @property
    def dependency_map(self) -> dict[str, list[str]]:
        return {t["id"]: list(t["depends_on"]) for t in self.ref_to_ticket.values()}


async def load_placement_context(
    conn: asyncpg.Connection, project_id: uuid.UUID
) -> PlacementContext:
    project = await conn.fetchrow("select * from projects where id = $1", project_id)
    if project is None:
        raise LookupError("없는 프로젝트다.")

    rows = await conn.fetch(
        """
        select t.id, t.title, t.status, t.est_minutes, t.task_id,
               k.task_number, k.title as task_title,
               g.week_index, g.title as week_title
        from tickets t
        join tasks k on k.id = t.task_id
        left join weekly_goals g on g.id = k.weekly_goal_id
        where t.project_id = $1
        order by g.week_index nulls last, k.task_number, t.ticket_number
        """,
        project_id,
    )
    deps = await conn.fetch(
        "select d.* from ticket_dependencies d join tickets t on t.id = d.ticket_id "
        "where t.project_id = $1",
        project_id,
    )
    depends: dict[str, list[str]] = {}
    for d in deps:
        depends.setdefault(str(d["ticket_id"]), []).append(str(d["depends_on"]))

    ref_to_ticket: dict[str, dict] = {}
    id_to_ref: dict[str, str] = {}
    for i, row in enumerate(rows, start=1):
        ref = f"T{i}"
        ticket = {
            **dict(row),
            "id": str(row["id"]),
            "task_id": str(row["task_id"]),
            "depends_on": depends.get(str(row["id"]), []),
        }
        ref_to_ticket[ref] = ticket
        id_to_ref[ticket["id"]] = ref
    # 선후관계도 참조로 바꿔 둔다 — 프롬프트에 uuid 를 흘리지 않기 위해서다.
    for ticket in ref_to_ticket.values():
        ticket["depends_on_refs"] = [
            id_to_ref[d] for d in ticket["depends_on"] if d in id_to_ref
        ]

    task_rows = await conn.fetch(
        """
        select k.id, k.task_number, k.title, k.weekly_goal_id,
               g.week_index, g.title as week_title
        from tasks k
        left join weekly_goals g on g.id = k.weekly_goal_id
        where k.project_id = $1
        order by g.week_index nulls last, k.task_number
        """,
        project_id,
    )
    ref_to_task = {
        f"K{i}": {**dict(r), "id": str(r["id"]), "weekly_goal_id": str(r["weekly_goal_id"])}
        for i, r in enumerate(task_rows, start=1)
    }

    node_rows = await conn.fetch(
        "select node_key, label, layer from arch_nodes where project_id = $1 order by layer",
        project_id,
    )

    return PlacementContext(
        project_id=project_id,
        constraints=Constraints(**project["constraints"]),
        base_draft=await load_draft(conn, project_id),
        ref_to_ticket=ref_to_ticket,
        ref_to_task=ref_to_task,
        nodes=[dict(n) for n in node_rows],
    )
