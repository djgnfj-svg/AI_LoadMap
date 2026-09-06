"""collect_signals — 재설계 그래프의 첫 단계 (SPEC §3.4).

전부 SQL 이다. AI 는 여기 개입하지 않는다 (R2).
재점검 세션이 숫자로 시작하는 이유는, 그 다음에 오는 AI 진단의 근거가
사용자의 실제 기록이어야 하기 때문이다 (§6.4).
"""

import uuid
from dataclasses import dataclass, field

import asyncpg

from app.graphs.persist import load_draft
from app.models.schemas import Constraints, PlanDraft, ReplanSignals


@dataclass
class ReplanContext:
    project_id: uuid.UUID
    node_id: uuid.UUID
    review_day_id: uuid.UUID
    signals: ReplanSignals
    constraints: Constraints
    base_draft: PlanDraft
    milestones: dict[str, dict] = field(default_factory=dict)
    tickets: dict[str, dict] = field(default_factory=dict)


async def load_replan_context(
    conn: asyncpg.Connection, review_day_id: uuid.UUID
) -> ReplanContext:
    review = await conn.fetchrow(
        "select * from review_days where id = $1", review_day_id
    )
    if review is None:
        raise LookupError("없는 재점검일이다.")
    project_id = review["project_id"]
    node_id = review["node_id"]

    project = await conn.fetchrow("select * from projects where id = $1", project_id)
    constraints = Constraints(**project["constraints"])

    node = await conn.fetchrow("select * from arch_nodes where id = $1", node_id)
    node_key = node["node_key"] if node else ""
    node_label = node["label"] if node else "(삭제된 컴포넌트)"

    # ── 숫자 (§2.4 1단계) ─────────────────────────────────────
    counts = await conn.fetchrow(
        """
        select
          count(*)                                            as total,
          count(*) filter (where t.status = 'done')           as done,
          count(*) filter (where t.delay_count >= 1)          as delayed
        from tickets t
        join ticket_node_links l on l.ticket_id = t.id
        where l.node_id = $1
        """,
        node_id,
    )
    event_counts = await conn.fetchrow(
        """
        select
          count(*) filter (where type = 'missed')   as missed,
          count(*) filter (where type = 'deferred') as deferred,
          coalesce(avg((payload ->> 'overdue_days')::numeric)
                   filter (where type = 'missed'), 0) as avg_delay
        from events
        where node_id = $1 and type in ('missed', 'deferred')
        """,
        node_id,
    )
    blocked = await conn.fetch(
        """
        select distinct t.blocked_reason
        from tickets t
        join ticket_node_links l on l.ticket_id = t.id
        where l.node_id = $1 and t.blocked_reason is not null
        """,
        node_id,
    )
    blocked_from_events = await conn.fetch(
        """
        select payload ->> 'reason' as reason
        from events
        where node_id = $1 and type = 'blocked' and payload ? 'reason'
        order by created_at desc
        limit 10
        """,
        node_id,
    )
    reasons = list(
        dict.fromkeys(
            [r["blocked_reason"] for r in blocked if r["blocked_reason"]]
            + [r["reason"] for r in blocked_from_events if r["reason"]]
        )
    )

    signals = ReplanSignals(
        node_key=node_key,
        node_label=node_label,
        total_tickets=counts["total"],
        done_tickets=counts["done"],
        delayed_tickets=counts["delayed"],
        missed_count=event_counts["missed"],
        deferred_count=event_counts["deferred"],
        avg_delay_days=round(float(event_counts["avg_delay"]), 1),
        blocked_reasons=reasons,
    )

    # ── 범위 후보 (replan_scope 가 고른다) ─────────────────────
    rows = await conn.fetch(
        """
        select
          t.id, t.title, t.body, t.est_minutes, t.status, t.delay_count, t.blocked_reason,
          t.order_index,
          t.weekly_goal_id, g.week_index, g.milestone_id,
          m.title as milestone_title, m.order_index as milestone_order,
          exists (
            select 1 from ticket_node_links l where l.ticket_id = t.id and l.node_id = $2
          ) as on_node
        from tickets t
        join weekly_goals g on g.id = t.weekly_goal_id
        join milestones m on m.id = g.milestone_id
        where t.project_id = $1
        order by m.order_index, g.week_index, t.order_index
        """,
        project_id,
        node_id,
    )
    deps = await conn.fetch(
        "select d.* from ticket_dependencies d join tickets t on t.id = d.ticket_id "
        "where t.project_id = $1",
        project_id,
    )
    depends_on: dict[str, list[str]] = {}
    for d in deps:
        depends_on.setdefault(str(d["ticket_id"]), []).append(str(d["depends_on"]))

    node_keys: dict[str, list[str]] = {}
    for r in await conn.fetch(
        "select l.ticket_id, n.node_key from ticket_node_links l "
        "join arch_nodes n on n.id = l.node_id where n.project_id = $1",
        project_id,
    ):
        node_keys.setdefault(str(r["ticket_id"]), []).append(r["node_key"])

    milestones: dict[str, dict] = {}
    tickets: dict[str, dict] = {}
    for r in rows:
        mid = str(r["milestone_id"])
        m = milestones.setdefault(
            mid,
            {
                "id": mid,
                "title": r["milestone_title"],
                "order_index": r["milestone_order"],
                "goal_ids": [],
                "on_node": 0,
                "delayed": 0,
                "open": 0,
            },
        )
        goal_id = str(r["weekly_goal_id"])
        if goal_id not in m["goal_ids"]:
            m["goal_ids"].append(goal_id)
        if r["on_node"]:
            m["on_node"] += 1
            if r["delay_count"] >= 1:
                m["delayed"] += 1
        if r["status"] != "done":
            m["open"] += 1

        tid = str(r["id"])
        tickets[tid] = {
            "id": tid,
            "title": r["title"],
            "body": r["body"] or "",
            "est_minutes": r["est_minutes"],
            "order_index": r["order_index"],
            "status": r["status"],
            "delay_count": r["delay_count"],
            "blocked_reason": r["blocked_reason"],
            "weekly_goal_id": goal_id,
            "week_index": r["week_index"],
            "milestone_id": mid,
            "on_node": bool(r["on_node"]),
            "depends_on": depends_on.get(tid, []),
            "node_keys": node_keys.get(tid, []),
        }

    return ReplanContext(
        project_id=project_id,
        node_id=node_id,
        review_day_id=review_day_id,
        signals=signals,
        constraints=constraints,
        base_draft=await load_draft(conn, project_id),
        milestones=milestones,
        tickets=tickets,
    )
