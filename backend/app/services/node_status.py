"""노드 상태 동기화 (SPEC §2.5, §4.4).

계산 자체는 v_node_status 뷰가 한다 (순수 SQL, R2). 여기서는 계산 결과를
arch_nodes.status 에 반영하기만 한다. 프론트가 뷰를 몰라도 노드만 읽으면 되게.
"""

import uuid

import asyncpg


async def sync_node_status(conn: asyncpg.Connection, project_id: uuid.UUID) -> list[dict]:
    """프로젝트의 모든 노드 상태를 다시 계산해 저장하고, 바뀐 노드를 돌려준다."""
    changed = await conn.fetch(
        """
        update arch_nodes n
        set status = s.status
        from v_node_status s
        where s.node_id = n.id
          and n.project_id = $1
          and n.status is distinct from s.status
        returning n.id, n.node_key, n.status
        """,
        project_id,
    )
    return [
        {"node_id": str(r["id"]), "node_key": r["node_key"], "status": r["status"]}
        for r in changed
    ]
