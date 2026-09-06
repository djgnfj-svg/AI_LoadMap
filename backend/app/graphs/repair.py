"""결정적 복구 — critic 재시도가 소진됐을 때 마지막으로 도는 순수 파이썬 단계.

SPEC §3.3 은 `critic 실패 -> decompose` 재시도만 명시한다. 이 모듈은 그 재시도가
3회(설정값) 모두 실패했을 때를 위한 것이다. 이유:

  * D3 의 완료 기준은 "위반 시 재분할이 실제 동작"이다. LLM 이 세 번 다 120분을
    못 지키면 그 기준이 무너진다.
  * est_minutes <= 120 은 DB CHECK 제약이라, 위반한 초안은 emit 에서 그냥 터진다.
    데모 도중 터지는 것보다 결정적으로 고쳐 넣는 게 낫다.

AI 는 여기 개입하지 않는다. 무엇을 고쳤는지는 전부 문자열로 남겨 사용자에게 보인다.
"""

import math
from collections import Counter, defaultdict

from app.models.schemas import (
    MAX_TICKET_MINUTES,
    Constraints,
    DraftLink,
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
    _renumber_order(d)

    return d, notes


# ─────────────────────────────────────────────────────────────
def _dedupe_keys(d: PlanDraft) -> tuple[PlanDraft, list[str]]:
    notes: list[str] = []
    for label, attr, key_attr in (
        ("마일스톤", "milestones", "key"),
        ("주차별 목표", "weekly_goals", "key"),
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
    milestone_keys = {m.key for m in d.milestones}
    before = len(d.weekly_goals)
    d.weekly_goals = [g for g in d.weekly_goals if g.milestone_key in milestone_keys]
    if before != len(d.weekly_goals):
        notes.append(f"마일스톤이 없는 주차별 목표 {before - len(d.weekly_goals)}개 제거")

    goal_keys = {g.key for g in d.weekly_goals}
    before = len(d.tickets)
    d.tickets = [t for t in d.tickets if t.weekly_goal_key in goal_keys]
    if before != len(d.tickets):
        notes.append(f"주차별 목표가 없는 티켓 {before - len(d.tickets)}개 제거")

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


def _break_cycles(d: PlanDraft) -> tuple[PlanDraft, list[str]]:
    """티켓을 (week_index, order_index) 순서로 보고, 뒤를 가리키는 의존을 끊는다."""
    goal_week = {g.key: g.week_index for g in d.weekly_goals}
    rank = {
        t.key: (goal_week.get(t.weekly_goal_key, 0), t.order_index, t.key)
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
    link_map: dict[str, str] = {}  # 원래 key -> 첫 조각 key (노드 연결 승계용)

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
                    weekly_goal_key=t.weekly_goal_key,
                    order_index=t.order_index * 100 + i,
                    title=f"{t.title} ({i + 1}/{parts})",
                    body=t.body,
                    est_minutes=minutes,
                    depends_on=list(t.depends_on) if prev_key is None else [prev_key],
                )
            )
            prev_key = key
        tail_of[t.key] = prev_key  # type: ignore[assignment]
        link_map[t.key] = f"{t.key}__1"

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
    """주간 합계가 가용시간을 넘으면 뒤쪽 티켓을 다음 주차로 넘긴다.

    넘길 주차가 없으면 새 주차별 목표를 만든다. 그 결과 계획 기간이 늘어날 수 있고,
    그건 숨기지 않고 수정 내역으로 남긴다.
    """
    capacity = constraints.weekly_capacity_minutes
    if capacity <= 0 or not d.tickets:
        return d, []

    goal_by_key = {g.key: g for g in d.weekly_goals}
    moved = 0
    max_week = max((g.week_index for g in d.weekly_goals), default=1)
    extended_to = max_week
    unfixable: set[int] = set()
    guard = 0

    while guard < 1000:
        guard += 1
        per_week: dict[int, list[DraftTicket]] = defaultdict(list)
        for t in d.tickets:
            g = goal_by_key.get(t.weekly_goal_key)
            if g:
                per_week[g.week_index].append(t)

        over = sorted(
            w
            for w, ts in per_week.items()
            if w not in unfixable and sum(t.est_minutes for t in ts) > capacity
        )
        if not over:
            break

        week = over[0]
        tickets = sorted(per_week[week], key=lambda t: t.order_index)
        # 티켓 하나만으로 가용시간을 넘으면 옮겨도 소용없다. 이 주차는 포기하고 다음으로.
        if len(tickets) <= 1:
            unfixable.add(week)
            continue

        victim = tickets[-1]
        src_goal = goal_by_key[victim.weekly_goal_key]
        target = _goal_for_week(d, goal_by_key, src_goal, week + 1)
        victim.weekly_goal_key = target.key
        victim.order_index = 0
        moved += 1
        extended_to = max(extended_to, target.week_index)

    notes: list[str] = []
    if moved:
        notes.append(f"주당 가용시간({capacity}분)을 넘긴 티켓 {moved}개를 다음 주차로 이월")
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
    src: DraftWeeklyGoal,
    week: int,
) -> DraftWeeklyGoal:
    """같은 마일스톤의 해당 주차 목표를 찾고, 없으면 만든다."""
    for g in d.weekly_goals:
        if g.milestone_key == src.milestone_key and g.week_index == week:
            return g
    new_goal = DraftWeeklyGoal(
        key=f"{src.key}__w{week}",
        milestone_key=src.milestone_key,
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
    """노드에 안 붙은 티켓을 같은 주차 -> 같은 마일스톤 -> 첫 노드 순으로 연결한다."""
    if not d.nodes:
        return d, []
    linked_tickets = {link.ticket_key for link in d.links}
    unlinked = [t for t in d.tickets if t.key not in linked_tickets]
    if not unlinked:
        return d, []

    goal_milestone = {g.key: g.milestone_key for g in d.weekly_goals}
    node_by_goal: dict[str, str] = {}
    node_by_milestone: dict[str, str] = {}
    ticket_goal = {t.key: t.weekly_goal_key for t in d.tickets}
    for link in d.links:
        gk = ticket_goal.get(link.ticket_key)
        if gk:
            node_by_goal.setdefault(gk, link.node_key)
            mk = goal_milestone.get(gk)
            if mk:
                node_by_milestone.setdefault(mk, link.node_key)

    fallback = d.nodes[0].node_key
    for t in unlinked:
        gk = t.weekly_goal_key
        node_key = (
            node_by_goal.get(gk)
            or node_by_milestone.get(goal_milestone.get(gk, ""))
            or fallback
        )
        d.links.append(DraftLink(ticket_key=t.key, node_key=node_key))
    return d, [f"노드에 연결되지 않은 티켓 {len(unlinked)}개를 인접 노드에 연결"]


def _renumber_order(d: PlanDraft) -> None:
    """주차별 목표 안에서 order_index 를 1부터 다시 매긴다."""
    by_goal: dict[str, list[DraftTicket]] = defaultdict(list)
    for t in d.tickets:
        by_goal[t.weekly_goal_key].append(t)
    for tickets in by_goal.values():
        for i, t in enumerate(sorted(tickets, key=lambda x: x.order_index), start=1):
            t.order_index = i
    for i, m in enumerate(sorted(d.milestones, key=lambda x: x.order_index), start=1):
        m.order_index = i
