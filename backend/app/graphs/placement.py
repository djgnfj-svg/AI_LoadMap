"""배치 제안을 승인 단위(ReplanChange)로 옮기는 층 (SPEC §3.7).

재설계와 **같은 변경 타입**만 낸다 — `add_ticket` 하나와 `add_dependency` 몇 개다.
그래야 적용(`services/replan_apply.py`)과 초안 미리보기(`replan.apply_to_draft`),
critic 검증까지 이미 있는 것을 그대로 쓴다. 새 일이 들어오는 문만 새로 낸다.

⚠ 순서가 중요하다. `replan._ORDER` 가 add_ticket(3) 을 add_dependency(4) 보다
먼저 적용한다. 그래서 새 티켓을 가리키는 선행 관계가 성립한다. 사용자가 add_ticket
을 거절하면 add_dependency 는 대상이 없어 조용히 건너뛴다(`_add_dependency` 가
두 티켓이 다 있는지 본다).
"""

import uuid

from app.graphs.replan import _reaches, _stub_body
from app.models.schemas import (
    MAX_TICKET_MINUTES,
    PlacementResult,
    ReplanChange,
)

# 배치가 손대는 것은 이 둘뿐이다.
MAX_DEPENDENCIES = 5


def build_placement_changes(
    result: PlacementResult,
    *,
    fallback_title: str,
    ref_to_ticket: dict[str, dict],
    ref_to_task: dict[str, dict],
    node_keys: set[str],
    dependency_map: dict[str, list[str]],
) -> tuple[list[ReplanChange], str]:
    """제안을 승인 단위로 바꾸고, 사람이 읽는 자리 한 줄을 함께 돌려준다.

    말이 안 되는 제안은 조용히 버린다 — diff 에 남으면 승인할 수 있게 되고,
    승인하면 계획이 깨진다. 태스크를 못 고른 것만은 버릴 수 없어서 예외를 낸다.
    """
    task = ref_to_task.get(result.task_ref)
    if task is None:
        raise ValueError(f"모르는 태스크 참조: {result.task_ref}")

    title = (result.title or fallback_title).strip() or fallback_title
    est = min(max(int(result.est_minutes or 30), 1), MAX_TICKET_MINUTES)
    new_id = str(uuid.uuid4())

    deps = dict(dependency_map)
    deps[new_id] = []

    # 이 일보다 먼저 끝나야 하는 것. 이미 끝난 티켓은 선행으로 세지 않는다.
    before: list[dict] = []
    for ref in result.depends_on_refs[:MAX_DEPENDENCIES]:
        ticket = ref_to_ticket.get(ref)
        if ticket is None or ticket["status"] == "resolved":
            continue
        if ticket["id"] in [t["id"] for t in before]:
            continue
        before.append(ticket)
        deps[new_id].append(ticket["id"])

    # 이 일 때문에 밀리는 것. 방금 세운 선행을 거슬러 올라가면 순환이다.
    after: list[dict] = []
    for ref in result.blocks_refs[:MAX_DEPENDENCIES]:
        ticket = ref_to_ticket.get(ref)
        if ticket is None or ticket["status"] == "resolved":
            continue
        if ticket["id"] in [t["id"] for t in before + after]:
            continue
        if _reaches(deps, new_id, ticket["id"]):
            continue
        deps.setdefault(ticket["id"], []).append(new_id)
        after.append(ticket)

    keys = [k for k in result.node_keys if k in node_keys]

    changes: list[ReplanChange] = [
        ReplanChange(
            id="c1",
            type="add_ticket",
            # 어디에 넣는지는 자리 한 줄(_placement_line)이 이미 말한다.
            label=f"{title} ({est}분)",
            reason=result.reason,
            before=None,
            after=f"{title} ({est}분)",
            op={
                "task_id": task["id"],
                "new_ticket_id": new_id,
                "title": title,
                "body": result.body.strip() or _stub_body(title),
                "est_minutes": est,
                "node_keys": keys,
                # 첫 하나는 add_ticket 이 함께 넣는다. 나머지는 아래에서 따로 낸다.
                "blocks_ticket_id": after[0]["id"] if after else None,
            },
        )
    ]

    counter = 1
    for ticket in before:
        counter += 1
        changes.append(
            ReplanChange(
                id=f"c{counter}",
                type="add_dependency",
                label=f"「{ticket['title']}」을 먼저 끝냄",
                reason=f"{title} 은(는) 이것 다음이다.",
                before=None,
                after=f"{ticket['title']} → {title}",
                op={"ticket_id": new_id, "depends_on": ticket["id"]},
            )
        )
    for ticket in after[1:]:
        counter += 1
        changes.append(
            ReplanChange(
                id=f"c{counter}",
                type="add_dependency",
                label=f"「{ticket['title']}」을 이 뒤로 미룸",
                reason=f"{ticket['title']} 은(는) {title} 다음이다.",
                before=None,
                after=f"{title} → {ticket['title']}",
                op={"ticket_id": ticket["id"], "depends_on": new_id},
            )
        )

    return changes, _placement_line(task, before, after)


def _placement_line(task: dict, before: list[dict], after: list[dict]) -> str:
    """「2주차 · 넷코드 붙이기 · T3 다음」 — 승인 화면의 첫 줄이다."""
    parts = [f"{task['week_index']}주차", task["title"]]
    if before:
        parts.append("「" + "」·「".join(t["title"] for t in before) + "」 다음")
    if after:
        parts.append("「" + "」·「".join(t["title"] for t in after) + "」 앞")
    return " · ".join(parts)
