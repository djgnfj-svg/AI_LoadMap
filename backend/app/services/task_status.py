"""태스크 상태 동기화 (SPEC §2.1).

태스크는 티켓들의 집이다. 그 안의 티켓이 다 끝났는데 태스크가 open 으로
남아 있으면 보드가 거짓말을 한다. 그래서 태스크 상태는 사람이 따로 관리하는
값이 아니라 티켓에서 되읽는 값이다 — 한 사실은 한 곳에만 산다.

계산은 전부 SQL 이다. AI 는 개입하지 않는다 (R2).

낱말은 티켓과 같은 넷을 쓴다:
  - resolved : 티켓이 하나 이상이고 전부 끝났다
  - parked   : 남은 것이 전부 접혔다 (끝난 것과 접은 것만 있고, 접은 게 있다)
  - claimed  : 누군가 손을 댔다 (끝났거나 잡고 있는 티켓이 하나라도 있다)
  - open     : 아직 아무도 손대지 않았다
⚠ 「막힘」은 여기 없다. 막힘은 상태가 아니라 티켓의 blocked_reason 한 줄이다.
"""

import uuid

import asyncpg


async def sync_task_status(conn: asyncpg.Connection, project_id: uuid.UUID) -> list[dict]:
    """프로젝트의 모든 태스크 상태를 티켓에서 다시 읽어 저장하고, 바뀐 것을 돌려준다.

    티켓이 하나도 없는 태스크는 건드리지 않는다 — 아직 티켓을 안 쓴 것과
    아무도 손 안 댄 것은 다른 사실이라, 없는 근거로 상태를 지어내지 않는다.
    """
    changed = await conn.fetch(
        """
        update tasks k
        set status = s.status
        from (
            select
                t.task_id,
                case
                    when count(*) filter (where t.status = 'resolved') = count(*)
                        then 'resolved'
                    when count(*) filter (where t.status not in ('resolved', 'parked')) = 0
                        then 'parked'
                    when count(*) filter (where t.status <> 'open') > 0
                        then 'claimed'
                    else 'open'
                end as status
            from tickets t
            where t.task_id is not null
            group by t.task_id
        ) s
        where s.task_id = k.id
          and k.project_id = $1
          and k.status is distinct from s.status
        returning k.id, k.task_number, k.status
        """,
        project_id,
    )
    return [
        {"task_id": str(r["id"]), "task_number": r["task_number"], "status": r["status"]}
        for r in changed
    ]
