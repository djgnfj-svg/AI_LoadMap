"""알람 생성 (SPEC §2.3).

문구는 전부 SQL 집계 결과를 채운 템플릿이다. LLM 이 쓰지 않는다 (R2).

톤은 R5 — 책망이 아니라 진단.
  ✗ "3일째 완료하지 않았습니다"
  ✓ "netcode 쪽에서 세 번 멈췄어요. 이 구간을 다시 짤까요?"

실패 감지 제품은 실패하는 순간 가장 먼저 버려진다. 문구가 기능이다.
"""

import uuid
from datetime import date

import asyncpg

from app.services import detection


async def _put(
    conn: asyncpg.Connection,
    *,
    project_id: uuid.UUID,
    rule: str,
    severity: str,
    message: str,
    dedupe_key: str,
    ticket_id: uuid.UUID | None = None,
    node_id: uuid.UUID | None = None,
    review_day_id: uuid.UUID | None = None,
) -> bool:
    """알람을 넣는다. 이미 확인하지 않은 같은 알람이 있으면 넣지 않는다."""
    row = await conn.fetchrow(
        """
        insert into alerts
          (project_id, ticket_id, node_id, review_day_id, rule, severity, message, dedupe_key)
        values ($1, $2, $3, $4, $5, $6, $7, $8)
        on conflict do nothing
        returning id
        """,
        project_id,
        ticket_id,
        node_id,
        review_day_id,
        rule,
        severity,
        message,
        dedupe_key,
    )
    return row is not None


async def generate_alerts(
    conn: asyncpg.Connection, project_id: uuid.UUID, today: date | None = None
) -> int:
    """§2.3 알람 규칙 5종을 한 번에 돌린다. 새로 만든 알람 수를 돌려준다."""
    day = today or date.today()
    created = 0
    created += await _due_24h(conn, project_id, day)
    created += await _deferred_twice(conn, project_id)
    created += await _node_at_risk(conn, project_id, day)
    created += await _inactive(conn, project_id, day)
    return created


async def _due_24h(conn: asyncpg.Connection, project_id: uuid.UUID, day: date) -> int:
    """마감 24시간 경과 -> "어디서 막혔나요?" 한 줄 입력 요청. 강도 낮음."""
    rows = await conn.fetch(
        """
        select t.id, t.title, t.due_date
        from tickets t
        where t.project_id = $1
          -- 끝난 것과 접은 것은 묻지 않는다. 막힘 사유를 이미 적은 것도
          -- 다시 묻지 않는다 — 막힘은 상태가 아니라 blocked_reason 한 줄이다.
          and t.status not in ('resolved', 'parked')
          and t.blocked_reason is null
          and t.due_date is not null
          and t.due_date < $2
        """,
        project_id,
        day,
    )
    count = 0
    for r in rows:
        overdue = (day - r["due_date"]).days
        count += await _put(
            conn,
            project_id=project_id,
            ticket_id=r["id"],
            rule="due_24h",
            severity="low",
            message=(
                f"「{r['title']}」 마감이 {overdue}일 지났어요. 어디서 막혔나요?"
            ),
            dedupe_key=f"due_24h:{r['id']}:{r['due_date']}",
        )
    return count


async def _deferred_twice(conn: asyncpg.Connection, project_id: uuid.UUID) -> int:
    """동일 티켓 2회 연기 -> 재분할 제안. 강도 중간."""
    count = 0
    for r in await detection.tickets_deferred_twice(conn, project_id):
        count += await _put(
            conn,
            project_id=project_id,
            ticket_id=r["id"],
            rule="deferred_twice",
            severity="medium",
            message=(
                f"「{r['title']}」을 {r['defers']}번 미뤘어요. "
                f"{r['est_minutes']}분이 아직 큰 단위일 수 있어요. 더 쪼갤까요?"
            ),
            dedupe_key=f"deferred_twice:{r['id']}:{r['defers']}",
        )
    return count


async def _node_at_risk(conn: asyncpg.Connection, project_id: uuid.UUID, day: date) -> int:
    """동일 노드 지연 2건 이상 -> 재점검일이 잡혔음을 알린다. 강도 높음.

    재점검일 생성(00:20)과 알람 생성(09:00)이 다른 시각에 돌아도(§3.6) 어긋나지 않게,
    "새로 만든 것"이 아니라 "열려 있는 재점검일 전부"를 훑는다. 중복은 dedupe 인덱스가 막는다.
    """
    await detection.ensure_review_days(conn, project_id, day)

    node_delays = await detection.node_delays(conn, project_id, day)
    delays_by_node = {d.node_id: d.delays for d in node_delays}
    rows = await conn.fetch(
        """
        select r.id, r.node_id, r.scheduled_date, r.trigger_reason, n.label
        from review_days r
        join arch_nodes n on n.id = r.node_id
        where r.project_id = $1 and r.status = 'scheduled'
        """,
        project_id,
    )
    count = 0
    for r in rows:
        delays = delays_by_node.get(r["node_id"])
        stopped = f"{delays}번 멈췄어요" if delays else "여러 번 멈췄어요"
        count += await _put(
            conn,
            project_id=project_id,
            node_id=r["node_id"],
            review_day_id=r["id"],
            rule="node_at_risk",
            severity="high",
            message=(
                f"{r['label']} 쪽에서 {stopped}. "
                f"{r['scheduled_date']}에 이 구간을 다시 짤까요?"
            ),
            dedupe_key=f"node_at_risk:{r['id']}",
        )
    return count


async def _inactive(conn: asyncpg.Connection, project_id: uuid.UUID, day: date) -> int:
    """3일 연속 무활동 -> 체크인. 알람이 아니라 질문이다 (§2.3)."""
    days = await detection.days_since_activity(conn, project_id, day)
    if days is None or days < detection.INACTIVE_DAYS:
        return 0
    return await _put(
        conn,
        project_id=project_id,
        rule="inactive_3d",
        severity="low",
        message=f"{days}일째 조용하네요. 지금 뭐가 제일 걸리나요?",
        dedupe_key=f"inactive_3d:{day.isoformat()}",
    )


async def generate_weekly_review(
    conn: asyncpg.Connection, project_id: uuid.UUID, today: date | None = None
) -> int:
    """주간 완료율 50% 미만 -> 주간 리뷰 알람 (SPEC §3.6 매주 일 20:00). 강도 중간."""
    day = today or date.today()
    week = await detection.current_week_index(conn, project_id, day)
    result = await detection.weekly_completion(conn, project_id, week)
    if result.total == 0 or result.rate >= detection.WEEKLY_COMPLETION_THRESHOLD:
        return 0
    return await _put(
        conn,
        project_id=project_id,
        rule="weekly_low",
        severity="medium",
        message=(
            f"{week}주차는 {result.done}/{result.total}개 끝냈어요. "
            "이번 주 계획이 실제보다 컸는지 같이 볼까요?"
        ),
        dedupe_key=f"weekly_low:{week}",
    )
