"""critic — 생성 그래프의 검증 노드 (SPEC §3.3).

이 노드에는 LLM 이 개입하지 않는다. 검증은 전부 결정적 규칙이다.
"검증이 없으면 LLM 을 한 번 호출한 것과 다르지 않다" 는 게 이 그래프의 존재 이유다.

SPEC §3.3 이 명시한 4개 항목:
  1. 티켓 예상 소요 <= 120분          (R1)
  2. 의존성 순환 없음
  3. 주간 티켓 합계 <= 가용시간
  4. 고아 노드 없음 (모든 노드에 티켓 1개 이상)

여기에 세 가지를 더한다.
  5. 청사진 커버리지 — 사용자가 말한 완성 기준을 맡는 주가 있는가.
     AI 가 세운 기준을 AI 가 검사하는 게 아니다. 기준 key 와 주의 covers 를
     맞춰보는 집합 연산이라 LLM 이 없다 (R2).
  6. 본문 — 주 · 태스크 · 티켓 셋 다 확인 항목이 있고, 확인할 수 있는 말로 쓰였는가.
     검사하지 않는 요구는 지켜지지 않는다. 끝났는지를 사용자가 판단할 수 없으면
     실패 감지(§2.3)의 입력 자체가 흐려진다 — 이건 세 층에 똑같이 해당한다.
  7. 자기 참조 무결성 (끊긴 참조/중복 키/미연결 티켓).
     깨지면 emit 에서 DB 제약으로 터지므로, 터지기 전에 잡아 재시도로 돌린다.
"""

import re
from collections import Counter, defaultdict

from app.models.schemas import (
    MAX_TICKET_MINUTES,
    MIN_ACCEPTANCE_CRITERIA,
    MIN_TASK_CHECKS,
    MIN_WEEK_CHECKS,
    Constraints,
    CriticResult,
    PlanDraft,
    Violation,
)

# 세 층이 같은 체크박스 문법을 쓴다. 제목만 다르다 (티켓은 「완료 조건」,
# 주·태스크는 「확인」) — 파서는 하나로 두고 제목만 둘 다 받는다.
CRITERIA_HEADING = re.compile(r"^\s*#{1,4}\s*(?:완료\s*조건|확인)\s*$")
NEXT_HEADING = re.compile(r"^\s*#{1,4}\s")
_CHECKBOX = re.compile(r"^\s*[-*]\s*\[[ xX]\]\s*(.+?)\s*$")

# 항목 **전체**가 이 표현뿐이면 확인할 수 없는 조건이다.
# 넓게 잡지 않는다 — 멀쩡한 조건을 걸러 재시도만 태우는 게 더 나쁘다.
_VAGUE = re.compile(
    r"^(잘\s*(동작|작동|된다|되는지)?(한다|하는지|합니다)?"
    r"|제대로\s*(동작|작동|된다|한다)?"
    r"|문제\s*없(다|음|는지|이)?"
    r"|정상\s*(동작|작동)?(한다|확인)?"
    r"|깔끔(하다|하게|히)?"
    r"|완성(한다|됨|되었다)?"
    r"|구현(한다|됨|완료)?"
    r"|확인(한다|함|하기)?"
    r"|테스트(한다|하기)?"
    r"|동작\s*확인)[.!]?$"
)
# 너무 짧으면 무엇을 확인해야 하는지 알 수 없다. "빌드 성공"(5)은 통과해야 한다.
MIN_CRITERION_LENGTH = 4


def acceptance_criteria(body: str) -> list[str]:
    """본문의 「완료 조건」·「확인」 섹션에서 체크 항목을 뽑는다 (SPEC §2.2).

    주 · 태스크 · 티켓 셋이 이 파서를 함께 쓴다. 제목만 다르고 문법은 같다.
    """
    items: list[str] = []
    inside = False
    for line in (body or "").splitlines():
        if CRITERIA_HEADING.match(line):
            inside = True
            continue
        if inside and NEXT_HEADING.match(line):
            break
        if inside and (m := _CHECKBOX.match(line)):
            items.append(m.group(1).strip())
    return items


def weak_criteria(body: str) -> list[str]:
    """확인할 수 없는 완료 조건만 골라 돌려준다."""
    return [
        item
        for item in acceptance_criteria(body)
        if len(item) < MIN_CRITERION_LENGTH or _VAGUE.match(item)
    ]


def _weak_bodies(
    items: list[tuple[str, str]], minimum: int
) -> tuple[list[str], list[str]]:
    """(key, 본문) 목록에서 확인 항목이 모자라거나 흐린 것을 갈라 낸다.

    주 · 태스크 · 티켓이 같은 검사를 받는다. 층마다 최소 개수만 다르다.
    """
    missing: list[str] = []
    vague: list[str] = []
    for key, body in items:
        found = acceptance_criteria(body)
        if len(found) < minimum:
            missing.append(f"{key}({len(found)}개)")
            continue
        if weak := weak_criteria(body):
            vague.append(f"{key}: {weak[0]}")
    return missing, vague


def _body_violation(
    code: str, missing: list[str], vague: list[str], minimum: int, fmt: str
) -> Violation | None:
    """_weak_bodies 의 결과를 위반 하나로 접는다. 셋 다 같은 모양으로 낸다."""
    if not missing and not vague:
        return None
    detail = []
    if missing:
        detail.append(f"확인 항목이 {minimum}개 미만: " + ", ".join(missing[:8]))
    if vague:
        detail.append("확인할 수 없는 항목: " + "; ".join(vague[:5]))
    return Violation(
        code=code,
        message=(
            "; ".join(detail)
            + f". 본문은 「{fmt}」 형식이고, 확인 항목은 눈으로 확인할 수 있어야 한다 "
            '("적 3종이 추격한다", "빌드 성공", "응답 200").'
        ),
        targets=[d.split("(")[0].split(":")[0] for d in [*missing, *vague]],
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


def run_critic(
    draft: PlanDraft, constraints: Constraints, *, check_bodies: bool = True
) -> CriticResult:
    """초안을 검증한다.

    check_bodies 는 재설계 그래프가 끈다. 재설계의 초안에는 이 규칙이 생기기 전에
    쓰인 기존 티켓이 그대로 실려 있고, 그건 이번 재설계가 고칠 대상이 아니다.
    (새로 만드는 티켓의 본문은 replan.py 가 형식을 갖춰 넣는다.)
    """
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

    # ── 6. 본문 — 세 층 모두 확인 항목이 있고 확인할 수 있는가 (§2.2) ──
    # 셋을 한 자리에서 검사한다. 층마다 최소 개수와 형식 문구만 다르다.
    if check_bodies:
        for code, rows, minimum, fmt in (
            (
                "weak_week_body",
                [(g.key, g.body) for g in draft.weekly_goals],
                MIN_WEEK_CHECKS,
                "## 확인 / ## 안 하는 것",
            ),
            (
                "weak_task_body",
                [(k.key, k.description) for k in draft.tasks],
                MIN_TASK_CHECKS,
                "## 무엇을 / ## 확인",
            ),
            (
                "weak_ticket_body",
                [(t.key, t.body) for t in draft.tickets],
                MIN_ACCEPTANCE_CRITERIA,
                "## 무엇을 / ## 완료 조건 / ## 참고",
            ),
        ):
            missing, vague = _weak_bodies(rows, minimum)
            if v := _body_violation(code, missing, vague, minimum, fmt):
                violations.append(v)

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
