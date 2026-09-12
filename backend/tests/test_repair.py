"""결정적 복구 (app/graphs/repair.py). critic 재시도 소진 후 마지막 방어선."""

from app.graphs.critic import run_critic
from app.graphs.repair import repair_draft
from app.models.schemas import (
    MAX_TICKET_MINUTES,
    Blueprint,
    Constraints,
    DraftEdge,
    DraftLink,
    DraftTask,
    DraftNode,
    DraftTicket,
    DraftWeeklyGoal,
    PlanDraft,
    SuccessCriterion,
)

# 완료 조건 2개짜리 최소 본문 (§2.2). critic 이 본문도 보기 때문에 필요하다.
BODY = "## 무엇을\n한 문장\n\n## 완료 조건\n- [ ] 테스트 3개 통과\n- [ ] 빌드 성공\n"

CONSTRAINTS = Constraints(
    duration_weeks=4, hours_per_week=10, level="intermediate", stack=["fastapi"], team_size=1
)


def broken_draft() -> PlanDraft:
    """critic 이 잡는 모든 항목을 한 번에 위반하는 초안."""
    return PlanDraft(
        tasks=[DraftTask(key="k1", weekly_goal_key="w1", task_number=1, title="태스크", description="")],
        weekly_goals=[DraftWeeklyGoal(key="w1", week_index=1, title="1주")],
        tickets=[
            DraftTicket(key="t1", task_key="k1", ticket_number=1, title="인증 구현",
                        body=BODY, est_minutes=300, depends_on=["t2"]),
            DraftTicket(key="t2", task_key="k1", ticket_number=2, title="DB 설계",
                        body=BODY, est_minutes=200, depends_on=["t1"]),
            DraftTicket(key="t3", task_key="k1", ticket_number=3, title="라우터",
                        body=BODY, est_minutes=90, depends_on=["없는티켓"]),
        ],
        nodes=[
            DraftNode(node_key="auth", label="Auth", node_type="service", layer="backend"),
            DraftNode(node_key="db", label="DB", node_type="store", layer="data"),
            DraftNode(node_key="ghost", label="안 쓰는 것", node_type="external", layer="infra"),
        ],
        edges=[DraftEdge(from_key="auth", to_key="db", label="reads")],
        links=[
            DraftLink(ticket_key="t1", node_key="auth"),
            DraftLink(ticket_key="t2", node_key="db"),
        ],
    )


def test_복구하면_critic_을_통과한다():
    before = run_critic(broken_draft(), CONSTRAINTS)
    assert not before.ok and len(before.violations) >= 4

    fixed, notes = repair_draft(broken_draft(), CONSTRAINTS)

    assert run_critic(fixed, CONSTRAINTS).ok
    assert notes  # 무엇을 고쳤는지 반드시 남는다


def test_R1_위반_티켓을_실제로_재분할한다():
    fixed, _ = repair_draft(broken_draft(), CONSTRAINTS)
    assert all(t.est_minutes <= MAX_TICKET_MINUTES for t in fixed.tickets)
    # 300분 티켓 -> 100분 x 3
    parts = sorted(t.est_minutes for t in fixed.tickets if t.key.startswith("t1__"))
    assert parts == [100, 100, 100]


def test_분할해도_총_예상시간은_보존된다():
    original = broken_draft()
    fixed, _ = repair_draft(original, CONSTRAINTS)
    assert sum(t.est_minutes for t in fixed.tickets) == sum(t.est_minutes for t in original.tickets)


def test_분할된_조각은_순서대로_의존한다():
    fixed, _ = repair_draft(broken_draft(), CONSTRAINTS)
    by_key = {t.key: t for t in fixed.tickets}
    assert by_key["t1__2"].depends_on == ["t1__1"]
    assert by_key["t1__3"].depends_on == ["t1__2"]


def test_분할된_조각은_원래_노드를_모두_승계한다():
    fixed, _ = repair_draft(broken_draft(), CONSTRAINTS)
    linked = {link.ticket_key for link in fixed.links if link.node_key == "auth"}
    assert {"t1__1", "t1__2", "t1__3"} <= linked


def test_고아_노드와_그_엣지를_함께_제거한다():
    fixed, _ = repair_draft(broken_draft(), CONSTRAINTS)
    keys = {n.node_key for n in fixed.nodes}
    assert "ghost" not in keys
    assert all(e.from_key in keys and e.to_key in keys for e in fixed.edges)


def test_가용시간_초과분은_다음_주차로_이월된다():
    tight = Constraints(
        duration_weeks=1, hours_per_week=2, level="beginner", stack=[], team_size=1
    )  # 주당 120분
    d = PlanDraft(
        tasks=[DraftTask(key="k1", weekly_goal_key="w1", task_number=1, title="태스크", description="")],
        weekly_goals=[DraftWeeklyGoal(key="w1", week_index=1, title="1주")],
        tickets=[
            DraftTicket(key=f"t{i}", task_key="k1", ticket_number=i, title=f"T{i}",
                        body=BODY, est_minutes=60, depends_on=[])
            for i in range(1, 5)
        ],
        nodes=[DraftNode(node_key="api", label="API", node_type="service", layer="backend")],
        links=[DraftLink(ticket_key=f"t{i}", node_key="api") for i in range(1, 5)],
    )
    fixed, notes = repair_draft(d, tight)

    assert run_critic(fixed, tight).ok
    assert max(g.week_index for g in fixed.weekly_goals) > 1
    # 기간이 늘어난 사실을 숨기지 않는다
    assert any("늘어났다" in n for n in notes)


def test_해소_불가능한_주차는_포기하고_사유를_남긴다():
    """티켓 하나가 이미 주당 가용시간을 넘으면 이월로 못 고친다. 무한루프에 빠지지 않아야 한다."""
    tiny = Constraints(
        duration_weeks=2, hours_per_week=1, level="beginner", stack=[], team_size=1
    )  # 주당 60분
    d = PlanDraft(
        tasks=[DraftTask(key="k1", weekly_goal_key="w1", task_number=1, title="태스크", description="")],
        weekly_goals=[DraftWeeklyGoal(key="w1", week_index=1, title="1주")],
        tickets=[
            DraftTicket(key="t1", task_key="k1", ticket_number=1, title="T",
                        body=BODY, est_minutes=120, depends_on=[])
        ],
        nodes=[DraftNode(node_key="api", label="API", node_type="service", layer="backend")],
        links=[DraftLink(ticket_key="t1", node_key="api")],
    )
    fixed, notes = repair_draft(d, tiny)

    assert all(t.est_minutes <= MAX_TICKET_MINUTES for t in fixed.tickets)  # R1 은 지켜진다
    assert any("해소되지 않는다" in n for n in notes)


def test_복구는_멱등이다():
    fixed, _ = repair_draft(broken_draft(), CONSTRAINTS)
    again, notes = repair_draft(fixed, CONSTRAINTS)
    assert notes == []
    assert {t.key for t in again.tickets} == {t.key for t in fixed.tickets}


# ── 청사진 커버리지 복구 (§3.3) ────────────────────────────────
def _with_blueprint() -> PlanDraft:
    return PlanDraft(
        blueprint=Blueprint(
            criteria=[
                SuccessCriterion(key="sc1", text="첫 화면이 뜬다"),
                SuccessCriterion(key="sc2", text="검색이 된다"),
            ]
        ),
        weekly_goals=[
            DraftWeeklyGoal(key="w1", week_index=1, title="1주", covers=["sc1"]),
            DraftWeeklyGoal(key="w2", week_index=2, title="2주", covers=["sc9"]),
        ],
        tasks=[
            DraftTask(key="k1", weekly_goal_key="w1", task_number=1, title="A", description=""),
            DraftTask(key="k2", weekly_goal_key="w2", task_number=2, title="B", description=""),
        ],
        tickets=[
            DraftTicket(key="t1", task_key="k1", ticket_number=1, title="T1",
                        body=BODY, est_minutes=60, depends_on=[]),
            DraftTicket(key="t2", task_key="k2", ticket_number=1, title="T2",
                        body=BODY, est_minutes=60, depends_on=[]),
        ],
        nodes=[DraftNode(node_key="api", label="API", node_type="service", layer="backend")],
        links=[DraftLink(ticket_key="t1", node_key="api"),
               DraftLink(ticket_key="t2", node_key="api")],
    )


def test_안_맡은_완성_기준은_마지막_주로_모으고_밝힌다():
    """조용히 지우지 않는다 — 사용자가 말한 완성 조건이다."""
    fixed, notes = repair_draft(_with_blueprint(), CONSTRAINTS)

    last = max(fixed.weekly_goals, key=lambda g: g.week_index)
    assert "sc2" in last.covers
    assert "sc9" not in last.covers  # 없는 기준을 가리키던 참조는 털어낸다
    assert any("확인이 필요하다" in n for n in notes)
    assert run_critic(fixed, CONSTRAINTS).ok


def test_완료_조건이_없으면_확인_항목을_채우고_밝힌다():
    """지어낸 조건임을 숨기지 않는다 — 사용자가 고쳐 쓸 자리를 남긴다."""
    d = draft_of(body="## 무엇을\n로그인을 붙인다\n")
    fixed, notes = repair_draft(d, CONSTRAINTS)

    assert run_critic(fixed, CONSTRAINTS).ok
    assert "(확인 필요)" in fixed.tickets[0].body
    assert "로그인을 붙인다" in fixed.tickets[0].body  # 원래 쓴 것은 지우지 않는다
    assert any("확인 항목을 채웠다" in n for n in notes)


def test_쓸_만한_조건은_남기고_모자란_것만_채운다():
    d = draft_of(body="## 무엇을\n한 문장\n\n## 완료 조건\n- [ ] 테스트 3개 통과\n")
    fixed, _ = repair_draft(d, CONSTRAINTS)

    assert "테스트 3개 통과" in fixed.tickets[0].body
    assert run_critic(fixed, CONSTRAINTS).ok


def draft_of(*, body: str) -> PlanDraft:
    return PlanDraft(
        weekly_goals=[DraftWeeklyGoal(key="w1", week_index=1, title="1주")],
        tasks=[DraftTask(key="k1", weekly_goal_key="w1", task_number=1, title="A", description="")],
        tickets=[
            DraftTicket(key="t1", task_key="k1", ticket_number=1, title="로그인",
                        body=body, est_minutes=60, depends_on=[])
        ],
        nodes=[DraftNode(node_key="api", label="API", node_type="service", layer="backend")],
        links=[DraftLink(ticket_key="t1", node_key="api")],
    )


# ── 주·태스크 본문도 채운다 (§2.2) ─────────────────────────────
def test_주와_태스크_본문도_채운다():
    """LLM 이 세 번 다 못 쓴 자리다. 비워 두면 끝났는지를 판단할 수 없다."""
    fixed, notes = repair_draft(draft_of(body=BODY), CONSTRAINTS)

    assert "## 확인" in fixed.weekly_goals[0].body
    assert "## 확인" in fixed.tasks[0].description
    assert run_critic(fixed, CONSTRAINTS).ok
    # 지어낸 티를 지우지 않는다 — 사용자가 고쳐 쓸 수 있어야 한다.
    assert all("(확인 필요)" in n or "확인 필요" in n for n in notes if "채웠다" in n)


def test_주의_안_하는_것은_지우지_않는다():
    """확인 절만 손본다. 나머지 절은 LLM 이 쓴 그대로 남는다."""
    d = draft_of(body=BODY)
    d.weekly_goals[0].body = "## 안 하는 것\n- 배포는 다음 주\n"
    fixed, _ = repair_draft(d, CONSTRAINTS)

    assert "배포는 다음 주" in fixed.weekly_goals[0].body
    assert "## 확인" in fixed.weekly_goals[0].body
    assert run_critic(fixed, CONSTRAINTS).ok


def test_쓸_만한_주_확인은_남긴다():
    d = draft_of(body=BODY)
    d.weekly_goals[0].body = "## 확인\n- [ ] 화면에 목록이 뜬다\n"
    fixed, _ = repair_draft(d, CONSTRAINTS)

    assert "화면에 목록이 뜬다" in fixed.weekly_goals[0].body
    assert run_critic(fixed, CONSTRAINTS).ok
