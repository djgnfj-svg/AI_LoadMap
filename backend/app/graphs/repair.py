"""결정적 복구 — critic 재시도가 소진됐을 때 마지막으로 도는 순수 파이썬 단계.

SPEC §3.3 은 `critic 실패 -> decompose` 재시도만 명시한다. 이 모듈은 그 재시도가
3회(설정값) 모두 실패했을 때를 위한 것이다. 이유:

  * D3 의 완료 기준은 "위반 시 재분할이 실제 동작"이다. LLM 이 세 번 다 120분을
    못 지키면 그 기준이 무너진다.
  * est_minutes <= 120 은 DB CHECK 제약이라, 위반한 초안은 emit 에서 그냥 터진다.
    데모 도중 터지는 것보다 결정적으로 고쳐 넣는 게 낫다.

AI 는 여기 개입하지 않는다. 무엇을 고쳤는지는 전부 문자열로 남겨 사용자에게 보인다.

⚠ 이월 단위는 태스크다. 한 태스크는 한 주에만 살기 때문에, 티켓 하나만 다음 주로
밀면 그 티켓이 든 태스크가 두 주에 걸치게 된다. 그건 계층이 금지한다.
"""

import math
from collections import Counter, defaultdict

from app.models.schemas import (
    MAX_TICKET_MINUTES,
    Constraints,
    DraftLink,
    DraftTask,
    DraftTicket,
    DraftWeeklyGoal,
    PlanDraft,
)


def repair_draft(draft: PlanDraft, constraints: Constraints) -> tuple[PlanDraft, list[str]]:
    """초안을 critic 이 통과할 수 있는 형태로 고친다. (고친 초안, 수정 내역) 반환."""
    notes: list[str] = []
    d = draft.model_copy(deep=True)

    d, n = _dedupe_keys(d)
    notes += n
    d, n = _drop_dangling(d)
    notes += n
    d, n = _break_cycles(d)
    notes += n
    d, n = _split_oversized_tickets(d)
    notes += n
    d, n = _spill_overloaded_weeks(d, constraints)
    notes += n
    d, n = _drop_orphan_nodes(d)
    notes += n
    d, n = _link_unlinked_tickets(d)
    notes += n
    _renumber(d)

    return d, notes


# ─────────────────────────────────────────────────────────────
def _dedupe_keys(d: PlanDraft) -> tuple[PlanDraft, list[str]]:
    notes: list[str] = []
    for label, attr, key_attr in (
        ("주", "weekly_goals", "key"),
        ("태스크", "tasks", "key"),
        ("티켓", "tickets", "key"),
        ("아키텍처 노드", "nodes", "node_key"),
    ):
        items = getattr(d, attr)
        counts = Counter(getattr(i, key_attr) for i in items)
        if not any(n > 1 for n in counts.values()):
            continue
        seen: set[str] = set()
        kept = []
        dropped = []
        for item in items:
            k = getattr(item, key_attr)
            if k in seen:
                dropped.append(k)
                continue
            seen.add(k)
            kept.append(item)
        setattr(d, attr, kept)
        notes.append(f"{label} 중복 키 {len(dropped)}개 제거: {', '.join(sorted(set(dropped)))}")
    return d, notes


def _drop_dangling(d: PlanDraft) -> tuple[PlanDraft, list[str]]:
    notes: list[str] = []
    goal_keys = {g.key for g in d.weekly_goals}
    before = len(d.tasks)
    d.tasks = [k for k in d.tasks if k.weekly_goal_key in goal_keys]
    if before != len(d.tasks):
        notes.append(f"주가 없는 태스크 {before - len(d.tasks)}개 제거")

    task_keys = {k.key for k in d.tasks}
    before = len(d.tickets)
    d.tickets = [t for t in d.tickets if t.task_key in task_keys]
    if before != len(d.tickets):
        notes.append(f"태스크가 없는 티켓 {before - len(d.tickets)}개 제거")

    ticket_keys = {t.key for t in d.tickets}
    for t in d.tickets:
        t.depends_on = [dep for dep in t.depends_on if dep in ticket_keys and dep != t.key]

    node_keys = {n.node_key for n in d.nodes}
    d.edges = [e for e in d.edges if e.from_key in node_keys and e.to_key in node_keys]
    d.links = [
        link
        for link in d.links
        if link.ticket_key in ticket_keys and link.node_key in node_keys
    ]
    return d, notes


def _task_week(d: PlanDraft) -> dict[str, int]:
    """태스크 key -> 그 태스크가 사는 주차."""
    goal_week = {g.key: g.week_index for g in d.weekly_goals}
    return {k.key: goal_week.get(k.weekly_goal_key, 0) for k in d.tasks}


def _break_cycles(d: PlanDraft) -> tuple[PlanDraft, list[str]]:
    """티켓을 (주차, 태스크 번호, 티켓 번호) 순서로 보고, 뒤를 가리키는 의존을 끊는다."""
    task_week = _task_week(d)
    task_number = {k.key: k.task_number for k in d.tasks}
    rank = {
        t.key: (
            task_week.get(t.task_key, 0),
            task_number.get(t.task_key, 0),
            t.ticket_number,
            t.key,
        )
        for t in d.tickets
    }
    removed = 0
    for t in d.tickets:
        kept = []
        for dep in t.depends_on:
            if dep in rank and rank[dep] < rank[t.key]:
                kept.append(dep)
            else:
                removed += 1
        t.depends_on = kept
    notes = []
    if removed:
        notes.append(f"순환을 만드는 선행 의존 {removed}개 제거 (뒤 순서를 가리키던 참조)")
    return d, notes


def _split_oversized_tickets(d: PlanDraft) -> tuple[PlanDraft, list[str]]:
    """R1 위반 티켓을 120분 이내 조각으로 균등 분할한다."""
    oversized = [t for t in d.tickets if t.est_minutes > MAX_TICKET_MINUTES]
    if not oversized:
        return d, []

    # 원래 티켓 key -> 마지막 조각 key. 이 티켓에 의존하던 티켓은 마지막 조각을 기다려야 한다.
    tail_of: dict[str, str] = {}
    new_tickets: list[DraftTicket] = []

    for t in d.tickets:
        if t.est_minutes <= MAX_TICKET_MINUTES:
            new_tickets.append(t)
            continue
        parts = math.ceil(t.est_minutes / MAX_TICKET_MINUTES)
        base = t.est_minutes // parts
        remainder = t.est_minutes % parts
        prev_key: str | None = None
        for i in range(parts):
            minutes = base + (1 if i < remainder else 0)
            key = f"{t.key}__{i + 1}"
            new_tickets.append(
                DraftTicket(
                    key=key,
                    task_key=t.task_key,
                    # 임시 번호. 마지막에 _renumber 가 태스크 안에서 1부터 다시 맨다.
                    ticket_number=t.ticket_number * 100 + i,
                    title=f"{t.title} ({i + 1}/{parts})",
                    body=t.body,
                    est_minutes=minutes,
                    depends_on=list(t.depends_on) if prev_key is None else [prev_key],
                )
            )
            prev_key = key
        tail_of[t.key] = prev_key  # type: ignore[assignment]

    # 분할된 티켓을 가리키던 의존은 마지막 조각으로 옮긴다.
    for t in new_tickets:
        t.depends_on = [tail_of.get(dep, dep) for dep in t.depends_on]

    # 노드 연결은 모든 조각이 승계한다 (어느 조각에서 막혔는지도 같은 노드의 신호다).
    new_links: list[DraftLink] = []
    parts_of: dict[str, list[str]] = defaultdict(list)
    for t in new_tickets:
        if "__" in t.key:
            parts_of[t.key.rsplit("__", 1)[0]].append(t.key)
    for link in d.links:
        if link.ticket_key in parts_of:
            for part_key in parts_of[link.ticket_key]:
                new_links.append(DraftLink(ticket_key=part_key, node_key=link.node_key))
        else:
            new_links.append(link)

    d.tickets = new_tickets
    d.links = new_links
    detail = ", ".join(f"{t.key}({t.est_minutes}분)" for t in oversized[:5])
    return d, [f"120분을 넘는 티켓 {len(oversized)}개를 분할: {detail}"]


def _spill_overloaded_weeks(
    d: PlanDraft, constraints: Constraints
) -> tuple[PlanDraft, list[str]]:
    """주간 합계가 가용시간을 넘으면 뒤쪽 **태스크**를 다음 주로 넘긴다.

    ⚠ 티켓 하나만 옮기지 않는다. 한 태스크는 한 주에만 살기 때문이다.
    주에 태스크가 하나뿐인데도 넘치면 그 태스크를 둘로 쪼개 뒷부분을 다음 주로
    보낸다 — 태스크를 쪼개는 것은 주를 걸치는 것과 다르다.

    넘길 주가 없으면 새 주를 만든다. 그 결과 계획 기간이 늘어날 수 있고,
    그건 숨기지 않고 수정 내역으로 남긴다.
    """
    capacity = constraints.weekly_capacity_minutes
    if capacity <= 0 or not d.tickets:
        return d, []

    goal_by_key = {g.key: g for g in d.weekly_goals}
    task_by_key = {k.key: k for k in d.tasks}
    moved = 0
    split = 0
    max_week = max((g.week_index for g in d.weekly_goals), default=1)
    extended_to = max_week
    unfixable: set[int] = set()
    guard = 0

    while guard < 1000:
        guard += 1
        minutes_of_task: dict[str, int] = defaultdict(int)
        for t in d.tickets:
            minutes_of_task[t.task_key] += t.est_minutes

        per_week: dict[int, list[DraftTask]] = defaultdict(list)
        for k in d.tasks:
            g = goal_by_key.get(k.weekly_goal_key)
            if g:
                per_week[g.week_index].append(k)

        over = sorted(
            w
            for w, ks in per_week.items()
            if w not in unfixable and sum(minutes_of_task[k.key] for k in ks) > capacity
        )
        if not over:
            break

        week = over[0]
        tasks = sorted(per_week[week], key=lambda k: k.task_number)

        if len(tasks) > 1:
            # 뒤쪽 태스크를 통째로 다음 주로 넘긴다.
            victim = tasks[-1]
            target = _goal_for_week(d, goal_by_key, week + 1)
            victim.weekly_goal_key = target.key
            moved += 1
            extended_to = max(extended_to, target.week_index)
            continue

        # 태스크가 하나뿐이다. 티켓이 둘 이상이면 태스크를 쪼갠다.
        only = tasks[0]
        own = sorted(
            (t for t in d.tickets if t.task_key == only.key),
            key=lambda t: t.ticket_number,
        )
        if len(own) <= 1:
            unfixable.add(week)
            continue

        # 가용시간에 들어가는 만큼만 남기고 나머지를 새 태스크로 뗀다.
        head: list[DraftTicket] = []
        used = 0
        for t in own:
            if head and used + t.est_minutes > capacity:
                break
            head.append(t)
            used += t.est_minutes
        tail = own[len(head) :]
        if not tail:
            unfixable.add(week)
            continue

        target = _goal_for_week(d, goal_by_key, week + 1)
        next_number = max((k.task_number for k in d.tasks), default=0) + 1
        spun = DraftTask(
            key=f"{only.key}__w{target.week_index}",
            weekly_goal_key=target.key,
            task_number=next_number,
            title=f"{only.title} (이어서)",
            description=only.description,
        )
        d.tasks.append(spun)
        task_by_key[spun.key] = spun
        for t in tail:
            t.task_key = spun.key
        split += 1
        extended_to = max(extended_to, target.week_index)

    notes: list[str] = []
    if moved:
        notes.append(f"주당 가용시간({capacity}분)을 넘긴 태스크 {moved}개를 다음 주로 이월")
    if split:
        notes.append(
            f"태스크 {split}개를 둘로 쪼개 뒷부분을 다음 주로 이월 "
            "(그 주에 태스크가 하나뿐이라 통째로는 못 옮겼다)"
        )
    if unfixable:
        weeks = ", ".join(f"{w}주차" for w in sorted(unfixable))
        notes.append(
            f"{weeks}는 티켓 하나가 이미 주당 가용시간을 넘어 이월로 해소되지 않는다 "
            "(주당 시간을 늘리거나 목표 범위를 줄여야 한다)"
        )
    if extended_to > constraints.duration_weeks:
        notes.append(
            f"이월 결과 계획이 {extended_to}주차까지 늘어났다 "
            f"(입력한 기간 {constraints.duration_weeks}주)"
        )
    return d, notes


def _goal_for_week(
    d: PlanDraft,
    goal_by_key: dict[str, DraftWeeklyGoal],
    week: int,
) -> DraftWeeklyGoal:
    """해당 주차의 목표를 찾고, 없으면 만든다."""
    for g in d.weekly_goals:
        if g.week_index == week:
            return g
    new_goal = DraftWeeklyGoal(
        key=f"__w{week}",
        week_index=week,
        title=f"{week}주차 - 이월분",
    )
    d.weekly_goals.append(new_goal)
    goal_by_key[new_goal.key] = new_goal
    return new_goal


def _drop_orphan_nodes(d: PlanDraft) -> tuple[PlanDraft, list[str]]:
    """티켓이 하나도 안 붙는 노드는 이 로드맵이 실제로 만들지 않는 컴포넌트다."""
    linked = {link.node_key for link in d.links}
    orphans = [n.node_key for n in d.nodes if n.node_key not in linked]
    if not orphans:
        return d, []
    keep = set(linked)
    d.nodes = [n for n in d.nodes if n.node_key in keep]
    d.edges = [e for e in d.edges if e.from_key in keep and e.to_key in keep]
    return d, [f"연결된 티켓이 없는 노드 {len(orphans)}개 제거: {', '.join(sorted(orphans)[:5])}"]


def _link_unlinked_tickets(d: PlanDraft) -> tuple[PlanDraft, list[str]]:
    """노드에 안 붙은 티켓을 같은 태스크 -> 같은 주 -> 첫 노드 순으로 연결한다."""
    if not d.nodes:
        return d, []
    linked_tickets = {link.ticket_key for link in d.links}
    unlinked = [t for t in d.tickets if t.key not in linked_tickets]
    if not unlinked:
        return d, []

    task_goal = {k.key: k.weekly_goal_key for k in d.tasks}
    node_by_task: dict[str, str] = {}
    node_by_goal: dict[str, str] = {}
    ticket_task = {t.key: t.task_key for t in d.tickets}
    for link in d.links:
        tk = ticket_task.get(link.ticket_key)
        if tk:
            node_by_task.setdefault(tk, link.node_key)
            gk = task_goal.get(tk)
            if gk:
                node_by_goal.setdefault(gk, link.node_key)

    fallback = d.nodes[0].node_key
    for t in unlinked:
        tk = t.task_key
        node_key = (
            node_by_task.get(tk)
            or node_by_goal.get(task_goal.get(tk, ""))
            or fallback
        )
        d.links.append(DraftLink(ticket_key=t.key, node_key=node_key))
    return d, [f"노드에 연결되지 않은 티켓 {len(unlinked)}개를 인접 노드에 연결"]


def _renumber(d: PlanDraft) -> None:
    """태스크 번호는 프로젝트 전역으로, 티켓 번호는 태스크마다 1 부터 다시 맨다."""
    goal_week = {g.key: g.week_index for g in d.weekly_goals}
    for i, k in enumerate(
        sorted(d.tasks, key=lambda x: (goal_week.get(x.weekly_goal_key, 0), x.task_number)),
        start=1,
    ):
        k.task_number = i

    by_task: dict[str, list[DraftTicket]] = defaultdict(list)
    for t in d.tickets:
        by_task[t.task_key].append(t)
    for tickets in by_task.values():
        for i, t in enumerate(sorted(tickets, key=lambda x: x.ticket_number), start=1):
            t.ticket_number = i
