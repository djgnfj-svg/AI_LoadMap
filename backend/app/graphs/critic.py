"""critic — 생성 그래프의 검증 노드 (SPEC §3.3).

이 노드에는 LLM 이 개입하지 않는다. 검증은 전부 결정적 규칙이다.
"검증이 없으면 LLM 을 한 번 호출한 것과 다르지 않다" 는 게 이 그래프의 존재 이유다.

SPEC §3.3 이 명시한 4개 항목:
  1. 티켓 예상 소요 <= 120분          (R1)
  2. 의존성 순환 없음
  3. 주간 티켓 합계 <= 가용시간
  4. 고아 노드 없음 (모든 노드에 티켓 1개 이상)

여기에 두 가지를 더한다.
  5. 청사진 커버리지 — 사용자가 말한 완성 기준을 맡는 주가 있는가.
     AI 가 세운 기준을 AI 가 검사하는 게 아니다. 기준 key 와 주의 covers 를
     맞춰보는 집합 연산이라 LLM 이 없다 (R2).
  6. 자기 참조 무결성 (끊긴 참조/중복 키/미연결 티켓).
     깨지면 emit 에서 DB 제약으로 터지므로, 터지기 전에 잡아 재시도로 돌린다.
"""

from collections import Counter, defaultdict

from app.models.schemas import (
    MAX_TICKET_MINUTES,
    Constraints,
    CriticResult,
    PlanDraft,
    Violation,
)


def _find_cycle(edges: dict[str, list[str]]) -> list[str] | None:
    """의존 그래프에서 순환 하나를 찾아 경로로 돌려준다. 없으면 None."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(int)
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = GRAY
        stack.append(node)
        for nxt in edges.get(node, []):
            if color[nxt] == GRAY:
                return stack[stack.index(nxt) :] + [nxt]
            if color[nxt] == WHITE:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in list(edges.keys()):
        if color[node] == WHITE:
            found = visit(node)
            if found:
                return found
    return None


def run_critic(draft: PlanDraft, constraints: Constraints) -> CriticResult:
    violations: list[Violation] = []

    if not draft.tickets or not draft.weekly_goals or not draft.tasks:
        violations.append(
            Violation(
                code="empty_plan",
                message="주, 태스크, 티켓 중 비어 있는 것이 있다.",
            )
        )
        return CriticResult(ok=False, violations=violations)

    goal_keys = {g.key for g in draft.weekly_goals}
    task_keys = {k.key for k in draft.tasks}
    ticket_keys = {t.key for t in draft.tickets}
    node_keys = {n.node_key for n in draft.nodes}

    # ── 중복 키 ────────────────────────────────────────────────
    # 번호도 키다. 겹치면 emit 에서 unique 제약으로 터진다 — 터지기 전에 잡는다.
    ticket_numbers = [f"{t.task_key}-{t.ticket_number}" for t in draft.tickets]
    for label, items in (
        ("weekly_goal", [g.key for g in draft.weekly_goals]),
        ("task", [k.key for k in draft.tasks]),
        ("ticket", [t.key for t in draft.tickets]),
        ("arch_node", [n.node_key for n in draft.nodes]),
        ("task_number", [str(k.task_number) for k in draft.tasks]),
        ("ticket_number", ticket_numbers),
    ):
        counts = Counter(items)
        dupes = sorted(k for k, n in counts.items() if n > 1)
        if dupes:
            violations.append(
                Violation(
                    code="duplicate_key",
                    message=f"{label} key 가 중복됐다: {', '.join(dupes)}",
                    targets=dupes,
                )
            )

    # ── 1. R1: 티켓 예상 소요 <= 120분 ─────────────────────────
    oversized = [t for t in draft.tickets if t.est_minutes > MAX_TICKET_MINUTES]
    if oversized:
        violations.append(
            Violation(
                code="ticket_over_120min",
                message=(
                    f"{len(oversized)}개 티켓이 {MAX_TICKET_MINUTES}분을 넘는다. "
                    "각각을 120분 이내 단위로 다시 쪼개라: "
                    + ", ".join(f"{t.key}({t.est_minutes}분)" for t in oversized[:10])
                ),
                targets=[t.key for t in oversized],
            )
        )

    # ── 끊긴 참조 ──────────────────────────────────────────────
    dangling: list[str] = []
    for k in draft.tasks:
        if k.weekly_goal_key not in goal_keys:
            dangling.append(f"task {k.key} -> weekly_goal {k.weekly_goal_key}")
    for t in draft.tickets:
        if t.task_key not in task_keys:
            dangling.append(f"ticket {t.key} -> task {t.task_key}")
        for dep in t.depends_on:
            if dep not in ticket_keys:
                dangling.append(f"ticket {t.key} -> depends_on {dep}")
    for e in draft.edges:
        if e.from_key not in node_keys or e.to_key not in node_keys:
            dangling.append(f"arch_edge {e.from_key} -> {e.to_key}")
    for link in draft.links:
        if link.ticket_key not in ticket_keys or link.node_key not in node_keys:
            dangling.append(f"link {link.ticket_key} -> {link.node_key}")
    if dangling:
        violations.append(
            Violation(
                code="dangling_reference",
                message="존재하지 않는 대상을 가리키는 참조가 있다: " + "; ".join(dangling[:10]),
                targets=dangling,
            )
        )

    # ── 2. 의존성 순환 없음 ────────────────────────────────────
    dep_edges = {t.key: [d for d in t.depends_on if d in ticket_keys] for t in draft.tickets}
    cycle = _find_cycle(dep_edges)
    if cycle:
        violations.append(
            Violation(
                code="dependency_cycle",
                message="티켓 의존성에 순환이 있다: " + " -> ".join(cycle),
                targets=cycle,
            )
        )

    # ── 3. 주간 티켓 합계 <= 가용시간 ──────────────────────────
    # 티켓이 사는 주는 티켓이 든 태스크가 말한다 — 한 태스크는 한 주에만 산다.
    goal_week = {g.key: g.week_index for g in draft.weekly_goals}
    task_week = {k.key: goal_week.get(k.weekly_goal_key) for k in draft.tasks}
    week_minutes: dict[int, int] = defaultdict(int)
    for t in draft.tickets:
        week = task_week.get(t.task_key)
        if week is not None:
            week_minutes[week] += t.est_minutes

    capacity = constraints.weekly_capacity_minutes
    overloaded = sorted(w for w, m in week_minutes.items() if m > capacity)
    if overloaded:
        detail = ", ".join(
            f"{w}주차 {week_minutes[w]}분(가용 {capacity}분)" for w in overloaded[:10]
        )
        violations.append(
            Violation(
                code="weekly_overload",
                message=f"주당 가용시간을 넘긴 주가 있다: {detail}",
                targets=[str(w) for w in overloaded],
            )
        )

    # ── 4. 고아 노드 없음 (모든 노드에 티켓 1개 이상) ──────────
    linked_nodes = {link.node_key for link in draft.links}
    orphans = sorted(k for k in node_keys if k not in linked_nodes)
    if orphans:
        violations.append(
            Violation(
                code="orphan_node",
                message=(
                    "연결된 티켓이 없는 아키텍처 노드가 있다: "
                    + ", ".join(orphans[:10])
                    + ". 노드를 지우거나 해당 노드를 만드는 티켓을 연결하라."
                ),
                targets=orphans,
            )
        )

    # ── 5. 청사진 커버리지 (사용자가 말한 완성 기준을 맡는 주가 있는가) ──
    # 기준이 없으면(인터뷰를 전부 건너뛴 경우) 검사할 것도 없다.
    criteria = {c.key: c.text for c in draft.blueprint.criteria}
    if criteria:
        covered = {key for g in draft.weekly_goals for key in g.covers}
        unknown = sorted(covered - set(criteria))
        if unknown:
            violations.append(
                Violation(
                    code="dangling_reference",
                    message="없는 완성 기준을 가리키는 주가 있다: " + ", ".join(unknown[:10]),
                    targets=unknown,
                )
            )
        uncovered = [k for k in criteria if k not in covered]
        if uncovered:
            violations.append(
                Violation(
                    code="uncovered_criterion",
                    message=(
                        "어느 주도 맡지 않는 완성 기준이 있다: "
                        + "; ".join(f"{k}({criteria[k]})" for k in uncovered[:5])
                        + ". 그 기준을 끝내는 주의 covers 에 key 를 넣거나, "
                        "그 주의 티켓을 그쪽으로 바꿔라."
                    ),
                    targets=uncovered,
                )
            )

    # ── 미연결 티켓 (§2.2 — 티켓은 노드를 물고 있어야 한다) ────
    linked_tickets = {link.ticket_key for link in draft.links}
    unlinked = sorted(k for k in ticket_keys if k not in linked_tickets)
    if unlinked:
        violations.append(
            Violation(
                code="unlinked_ticket",
                message=(
                    "아키텍처 노드에 연결되지 않은 티켓이 있다: "
                    + ", ".join(unlinked[:10])
                    + ". 완료해도 다이어그램이 채워지지 않는다."
                ),
                targets=unlinked,
            )
        )

    return CriticResult(ok=not violations, violations=violations)
