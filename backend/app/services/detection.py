"""실패 감지 (SPEC §2.3, §4.5).

이 파일에는 LLM 호출이 하나도 없다. 전부 SQL 집계다 (R2).
"AI가 알아서 판단한다"는 제품은 신뢰를 얻지 못하는데, 이 구조는 판단의 입력이
사용자의 실제 기록이다. 그 분리가 여기서 지켜진다.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

import asyncpg

# §2.3 — 동일 아키텍처 노드에서 지연 2건 이상이면 재점검일
NODE_DELAY_THRESHOLD = 2
# §4.5 — 최근 14일 창
DELAY_WINDOW_DAYS = 14
# §2.4 — "다음 가용일". 가용일 모델이 없으므로 이틀 뒤로 잡는다.
#        §1.6 시나리오도 감지(Day 9) -> 재점검(Day 11) 간격이다.
REVIEW_LEAD_DAYS = 2
# §2.3 — 동일 티켓 2회 연기면 재분할 제안
TICKET_DEFER_THRESHOLD = 2
# §2.3 — 주간 완료율 50% 미만
WEEKLY_COMPLETION_THRESHOLD = 0.5
# §2.3 — 3일 연속 무활동
INACTIVE_DAYS = 3


@dataclass
class NodeDelay:
    node_id: uuid.UUID
    node_key: str
    label: str
    delays: int


@dataclass
class WeeklyCompletion:
    week_index: int
    total: int
    done: int

    @property
    def rate(self) -> float:
        return self.done / self.total if self.total else 1.0


async def record_missed_tickets(
    conn: asyncpg.Connection,
    today: date | None = None,
    project_id: uuid.UUID | None = None,
) -> int:
    """마감이 지난 티켓에 missed 이벤트를 남기고 delay_count 를 올린다 (SPEC §3.6 00:10).

    project_id 를 주면 그 프로젝트만 본다. 스케줄러는 전체를 돌고,
    한 프로젝트의 감지를 즉시 돌리는 엔드포인트는 그 프로젝트만 봐야 한다.

    `missed` 는 상태가 아니라 이벤트다 (R4). status 는 건드리지 않는다.

    같은 마감일에 대해서는 한 번만 기록한다. 스케줄러가 매일 도는데 5일 밀린 티켓에
    missed 를 5번 남기면 "몇 번 미뤘는가"가 "며칠 밀렸는가"로 바뀌어 신호가 망가진다.
    사용자가 기한을 옮기면 새 마감일에 대해 다시 한 번 기록될 수 있다.
    """
    day = today or date.today()
    rows = await conn.fetch(
        """
        select t.id, t.project_id, t.due_date
        from tickets t
        where t.status <> 'done'
          and t.due_date is not null
          and t.due_date < $1
          and ($2::uuid is null or t.project_id = $2)
          and not exists (
            select 1 from events e
            where e.ticket_id = t.id
              and e.type = 'missed'
              and (e.payload ->> 'due_date') = t.due_date::text
          )
        """,
        day,
        project_id,
    )
    if not rows:
        return 0

    for row in rows:
        await conn.execute(
            "update tickets set delay_count = delay_count + 1 where id = $1", row["id"]
        )
        node_ids = [
            r["node_id"]
            for r in await conn.fetch(
                "select node_id from ticket_node_links where ticket_id = $1", row["id"]
            )
        ] or [None]
        for node_id in node_ids:
            await conn.execute(
                "insert into events (project_id, ticket_id, node_id, type, payload) "
                "values ($1, $2, $3, 'missed', $4)",
                row["project_id"],
                row["id"],
                node_id,
                {
                    "due_date": row["due_date"].isoformat(),
                    "overdue_days": (day - row["due_date"]).days,
                },
            )
    return len(rows)


async def node_delays(
    conn: asyncpg.Connection, project_id: uuid.UUID, today: date | None = None
) -> list[NodeDelay]:
    """SPEC §4.5 — 동일 노드에서 지연 2건 이상. AI 는 이 판단에 개입하지 않는다."""
    rows = await conn.fetch(
        """
        select e.node_id, n.node_key, n.label, count(*) as delays
        from events e
        join arch_nodes n on n.id = e.node_id
        where e.project_id = $1
          and e.type in ('missed', 'deferred')
          and e.created_at > $2
        group by e.node_id, n.node_key, n.label
        having count(*) >= $3
        order by count(*) desc
        """,
        project_id,
        (today or date.today()) - timedelta(days=DELAY_WINDOW_DAYS),
        NODE_DELAY_THRESHOLD,
    )
    return [
        NodeDelay(r["node_id"], r["node_key"], r["label"], r["delays"]) for r in rows
    ]


async def ensure_review_days(
    conn: asyncpg.Connection, project_id: uuid.UUID, today: date | None = None
) -> list[dict]:
    """임계를 넘은 노드에 재점검일을 잡는다 (SPEC §3.6 00:20, §2.4).

    사용자는 날짜만 바꿀 수 있고 삭제할 수 없다. 미해결 재점검일이 이미 있으면
    부분 유니크 인덱스가 중복 생성을 막는다.
    """
    day = today or date.today()
    created: list[dict] = []
    for delay in await node_delays(conn, project_id, day):
        row = await conn.fetchrow(
            """
            insert into review_days (project_id, node_id, scheduled_date, trigger_reason)
            values ($1, $2, $3, $4)
            on conflict do nothing
            returning id, scheduled_date, trigger_reason
            """,
            project_id,
            delay.node_id,
            day + timedelta(days=REVIEW_LEAD_DAYS),
            f"{delay.label} 관련 지연 {delay.delays}건",
        )
        if row is not None:
            created.append(
                {
                    "review_day_id": row["id"],
                    "node_id": delay.node_id,
                    "node_key": delay.node_key,
                    "label": delay.label,
                    "delays": delay.delays,
                    "scheduled_date": row["scheduled_date"],
                    "trigger_reason": row["trigger_reason"],
                }
            )
    return created


async def tickets_deferred_twice(
    conn: asyncpg.Connection, project_id: uuid.UUID
) -> list[asyncpg.Record]:
    """SPEC §2.3 — 동일 티켓 2회 연기. 티켓이 아직 크다는 신호다."""
    return await conn.fetch(
        """
        select t.id, t.title, t.est_minutes, count(e.id) as defers
        from tickets t
        join events e on e.ticket_id = t.id and e.type = 'deferred'
        where t.project_id = $1 and t.status <> 'done'
        group by t.id, t.title, t.est_minutes
        having count(e.id) >= $2
        """,
        project_id,
        TICKET_DEFER_THRESHOLD,
    )


async def weekly_completion(
    conn: asyncpg.Connection, project_id: uuid.UUID, week_index: int
) -> WeeklyCompletion:
    """SPEC §2.3 — 주간 완료율."""
    row = await conn.fetchrow(
        """
        select count(*) as total, count(*) filter (where t.status = 'done') as done
        from tickets t
        join weekly_goals g on g.id = t.weekly_goal_id
        where t.project_id = $1 and g.week_index = $2
        """,
        project_id,
        week_index,
    )
    return WeeklyCompletion(week_index, row["total"], row["done"])


async def current_week_index(
    conn: asyncpg.Connection, project_id: uuid.UUID, today: date | None = None
) -> int:
    start = await conn.fetchval("select start_date from projects where id = $1", project_id)
    if start is None:
        return 1
    return max(1, ((today or date.today()) - start).days // 7 + 1)


async def days_since_activity(
    conn: asyncpg.Connection, project_id: uuid.UUID, today: date | None = None
) -> int | None:
    """SPEC §2.3 — 무활동 일수. 사용자가 직접 남긴 이벤트만 센다.

    스케줄러가 남기는 missed 는 활동이 아니다. 그걸 활동으로 치면
    아무것도 안 해도 무활동 알람이 영원히 안 뜬다.
    """
    last = await conn.fetchval(
        """
        select max(created_at)::date from events
        where project_id = $1 and type in ('started', 'completed', 'deferred', 'blocked')
        """,
        project_id,
    )
    if last is None:
        return None
    return ((today or date.today()) - last).days
