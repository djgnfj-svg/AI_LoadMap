"""재설계 제안을 실제 변경으로 옮기는 층 (SPEC §2.4, §3.4 diff).

LLM 이 내는 제안(ProposedChange)은 T1, T2 같은 참조만 안다.
여기서 참조를 실제 uuid 로 바꾸고, 새로 생기는 티켓의 uuid 도 지금 확정한다.

uuid 를 diff 단계에서 확정하는 이유: 그래야 초안 위에서 미리 적용해 critic 을 돌린
결과와, 사용자가 승인한 뒤 DB 에 들어가는 결과가 같은 것이 된다.
"""

import uuid
from collections import defaultdict

from app.models.schemas import (
    MAX_TICKET_MINUTES,
    DraftLink,
    DraftTicket,
    PlanDraft,
    ProposedChange,
    ReplanChange,
)

# 적용 순서. 쪼개고 줄이고 지운 뒤에 더하고, 마지막에 일정을 민다.
_ORDER = {
    "split_ticket": 0,
    "reduce_ticket": 1,
    "drop_ticket": 2,
    "add_ticket": 3,
    "add_dependency": 4,
    "shift_week": 5,
}


def _reaches(graph: dict[str, list[str]], start: str, target: str) -> bool:
    """start 가 depends_on 을 따라가 target 에 닿는가."""
    seen: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, []))
    return False


def build_changes(
    proposals: list[ProposedChange],
    *,
    ref_to_ticket: dict[str, dict],
    scope_task_ids: list[str],
    downstream_weekly_goal_ids: list[str],
    dependency_map: dict[str, list[str]] | None = None,
) -> list[ReplanChange]:
    """제안을 승인 단위(ReplanChange)로 바꾼다. 말이 안 되는 제안은 조용히 버린다.

    critic 이 잡을 수 있는 위반이라도, 여기서 걸러낼 수 있는 건 여기서 걸러낸다.
    diff 에 남으면 사용자가 승인할 수 있게 되고, 승인하면 계획이 깨진다.
    """
    changes: list[ReplanChange] = []
    deps: dict[str, list[str]] = {
        k: list(v) for k, v in (dependency_map or {}).items()
    }
    counter = 0

    for p in sorted(proposals, key=lambda c: _ORDER.get(c.type, 9)):
        target = ref_to_ticket.get(p.target_ref)
        depends = ref_to_ticket.get(p.depends_on_ref)
        counter += 1
        cid = f"c{counter}"

        # 이미 끝난 티켓은 건드리지 않는다. 한 일을 되돌리는 제안은 받지 않는다.
        if target is not None and target["status"] == "resolved" and p.type != "add_dependency":
            counter -= 1
            continue

        if p.type == "split_ticket":
            parts = [x for x in p.parts if x.est_minutes > 0]
            if target is None or len(parts) < 2:
                counter -= 1
                continue
            if any(x.est_minutes > MAX_TICKET_MINUTES for x in parts):
                counter -= 1
                continue
            extra_ids = [str(uuid.uuid4()) for _ in parts[1:]]
            changes.append(
                ReplanChange(
                    id=cid,
                    type=p.type,
                    label=f"「{target['title']}」을 {len(parts)}개로 쪼갬",
                    reason=p.reason,
                    before=f"{target['title']} ({target['est_minutes']}분)",
                    after=" / ".join(f"{x.title} ({x.est_minutes}분)" for x in parts),
                    op={
                        "ticket_id": target["id"],
                        "new_ticket_ids": extra_ids,
                        "parts": [x.model_dump() for x in parts],
                    },
                )
            )

        elif p.type == "reduce_ticket":
            if target is None or not p.title or p.est_minutes <= 0:
                counter -= 1
                continue
            if p.est_minutes > MAX_TICKET_MINUTES:
                counter -= 1
                continue
            changes.append(
                ReplanChange(
                    id=cid,
                    type=p.type,
                    label=f"「{target['title']}」 범위 축소",
                    reason=p.reason,
                    before=f"{target['title']} ({target['est_minutes']}분)",
                    after=f"{p.title} ({p.est_minutes}분)",
                    op={
                        "ticket_id": target["id"],
                        "title": p.title,
                        "body": p.body,
                        "est_minutes": p.est_minutes,
                    },
                )
            )

        elif p.type == "drop_ticket":
            if target is None or target["status"] != "open":
                counter -= 1
                continue
            changes.append(
                ReplanChange(
                    id=cid,
                    type=p.type,
                    label=f"「{target['title']}」을 이번 범위에서 제외",
                    reason=p.reason,
                    before=f"{target['title']} ({target['est_minutes']}분)",
                    after=None,
                    op={"ticket_id": target["id"]},
                )
            )

        elif p.type == "add_ticket":
            if not p.title or p.est_minutes <= 0 or p.est_minutes > MAX_TICKET_MINUTES:
                counter -= 1
                continue
            # 새 티켓은 태스크 아래에 선다 — 태스크 없는 티켓은 번호도 못 받는다.
            anchor = target or depends
            fallback_task = scope_task_ids[0] if scope_task_ids else None
            task_id = anchor["task_id"] if anchor else fallback_task
            if task_id is None:
                counter -= 1
                continue
            new_id = str(uuid.uuid4())
            changes.append(
                ReplanChange(
                    id=cid,
                    type=p.type,
                    label=f"티켓 추가: 「{p.title}」",
                    reason=p.reason,
                    before=None,
                    after=f"{p.title} ({p.est_minutes}분)",
                    op={
                        "new_ticket_id": new_id,
                        "task_id": task_id,
                        "title": p.title,
                        "body": p.body or f"## 무엇을\n{p.title}\n",
                        "est_minutes": p.est_minutes,
                        # 추가한 티켓은 원래 막힌 티켓 앞에 온다.
                        "blocks_ticket_id": target["id"] if target else None,
                        "node_keys": (target or {}).get("node_keys", []),
                    },
                )
            )

        elif p.type == "add_dependency":
            if target is None or depends is None or target["id"] == depends["id"]:
                counter -= 1
                continue
            # 이미 depends 쪽이 target 을 기다리고 있으면 반대 방향을 더할 수 없다.
            if _reaches(deps, depends["id"], target["id"]):
                counter -= 1
                continue
            deps.setdefault(target["id"], []).append(depends["id"])
            changes.append(
                ReplanChange(
                    id=cid,
                    type=p.type,
                    label=f"「{target['title']}」 앞에 「{depends['title']}」을 둠",
                    reason=p.reason,
                    before=None,
                    after=f"{depends['title']} → {target['title']}",
                    op={"ticket_id": target["id"], "depends_on": depends["id"]},
                )
            )

        elif p.type == "shift_week":
            days = max(1, min(p.shift_days, 90))
            if not downstream_weekly_goal_ids:
                counter -= 1
                continue
            changes.append(
                ReplanChange(
                    id=cid,
                    type=p.type,
                    label=f"후속 주 {len(downstream_weekly_goal_ids)}개 일정을 {days}일 이월",
                    reason=p.reason,
                    before="현재 일정",
                    after=f"{days}일 뒤로",
                    op={"weekly_goal_ids": downstream_weekly_goal_ids, "days": days},
                )
            )
        else:
            counter -= 1

    return changes


def apply_to_draft(draft: PlanDraft, changes: list[ReplanChange]) -> PlanDraft:
    """승인 여부와 무관하게, 주어진 변경을 초안 위에 적용한다.

    critic 은 이 결과를 본다. DB 에 실제로 넣기 전에 같은 결과를 검증하는 게 목적이다.
    (shift_week 은 날짜만 바꾸므로 초안 구조에 영향이 없어 여기서는 무시한다.)
    """
    d = draft.model_copy(deep=True)
    by_key = {t.key: t for t in d.tickets}
    links_by_ticket: dict[str, list[str]] = defaultdict(list)
    for link in d.links:
        links_by_ticket[link.ticket_key].append(link.node_key)

    for change in changes:
        op = change.op
        if change.type == "split_ticket":
            original = by_key.get(op["ticket_id"])
            if original is None:
                continue
            parts = op["parts"]
            original.title = parts[0]["title"]
            original.est_minutes = parts[0]["est_minutes"]
            prev = original.key
            # 조각은 원래 티켓과 같은 태스크에 선다. 번호는 뒤에 이어 붙인다.
            tail = max(
                (t.ticket_number for t in d.tickets if t.task_key == original.task_key),
                default=original.ticket_number,
            )
            for i, (new_id, part) in enumerate(
                zip(op["new_ticket_ids"], parts[1:], strict=True), start=1
            ):
                ticket = DraftTicket(
                    key=new_id,
                    task_key=original.task_key,
                    ticket_number=tail + i,
                    title=part["title"],
                    body=original.body,
                    est_minutes=part["est_minutes"],
                    depends_on=[prev],
                )
                d.tickets.append(ticket)
                by_key[new_id] = ticket
                for node_key in links_by_ticket.get(original.key, []):
                    d.links.append(DraftLink(ticket_key=new_id, node_key=node_key))
                prev = new_id

        elif change.type == "reduce_ticket":
            ticket = by_key.get(op["ticket_id"])
            if ticket:
                ticket.title = op["title"]
                ticket.est_minutes = op["est_minutes"]

        elif change.type == "drop_ticket":
            ticket_id = op["ticket_id"]
            d.tickets = [t for t in d.tickets if t.key != ticket_id]
            d.links = [link for link in d.links if link.ticket_key != ticket_id]
            by_key.pop(ticket_id, None)
            for t in d.tickets:
                t.depends_on = [x for x in t.depends_on if x != ticket_id]

        elif change.type == "add_ticket":
            task_key = op["task_id"]
            if not any(k.key == task_key for k in d.tasks):
                continue
            next_number = max(
                (t.ticket_number for t in d.tickets if t.task_key == task_key), default=0
            ) + 1
            ticket = DraftTicket(
                key=op["new_ticket_id"],
                task_key=task_key,
                ticket_number=next_number,
                title=op["title"],
                body=op["body"],
                est_minutes=op["est_minutes"],
                depends_on=[],
            )
            d.tickets.append(ticket)
            by_key[ticket.key] = ticket
            for node_key in op.get("node_keys") or []:
                d.links.append(DraftLink(ticket_key=ticket.key, node_key=node_key))
            blocked = by_key.get(op.get("blocks_ticket_id") or "")
            if blocked is not None:
                blocked.depends_on = [*blocked.depends_on, ticket.key]

        elif change.type == "add_dependency":
            ticket = by_key.get(op["ticket_id"])
            if ticket and op["depends_on"] in by_key and op["depends_on"] not in ticket.depends_on:
                ticket.depends_on = [*ticket.depends_on, op["depends_on"]]

    # 노드 연결이 하나도 없는 새 티켓은 첫 노드에 붙여 둔다 (critic 의 unlinked_ticket 방지).
    linked = {link.ticket_key for link in d.links}
    if d.nodes:
        for t in d.tickets:
            if t.key not in linked:
                d.links.append(DraftLink(ticket_key=t.key, node_key=d.nodes[0].node_key))
    return d
