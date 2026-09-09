"""재설계 제안 -> 변경 항목 변환 (app/graphs/replan.py).

critic 이 잡을 수 있는 위반이라도 여기서 걸러낼 수 있는 건 걸러낸다.
diff 에 남으면 사용자가 승인할 수 있게 되고, 승인하면 계획이 깨진다.
"""

from app.graphs.critic import run_critic
from app.graphs.replan import apply_to_draft, build_changes
from app.models.schemas import ProposedChange, SplitPart
from tests.helpers import CONSTRAINTS, sample_draft


def ticket(tid: str, **kw) -> dict:
    base = dict(
        id=tid, title=f"티켓 {tid}", est_minutes=90, status="open",
        task_id="k1", node_keys=["node_a"], depends_on=[],
    )
    base.update(kw)
    return base


def proposal(**kw) -> ProposedChange:
    base = dict(
        type="add_ticket", target_ref="", depends_on_ref="", reason="이유",
        title="", body="", est_minutes=0, parts=[], shift_days=0,
    )
    base.update(kw)
    return ProposedChange(**base)


def build(props, refs, **kw):
    return build_changes(
        props,
        ref_to_ticket=refs,
        scope_task_ids=kw.get("task_ids", ["k1"]),
        downstream_weekly_goal_ids=kw.get("downstream", ["w2"]),
        dependency_map=kw.get("deps"),
    )


def test_순환을_만드는_선행관계는_diff_에_넣지_않는다():
    """t2 가 이미 t1 을 기다리는데 t1 -> t2 를 더하면 순환이다."""
    refs = {"T1": ticket("t1"), "T2": ticket("t2", depends_on=["t1"])}
    changes = build(
        [proposal(type="add_dependency", target_ref="T1", depends_on_ref="T2")],
        refs,
        deps={"t2": ["t1"]},
    )
    assert changes == []


def test_정상_방향_선행관계는_통과한다():
    refs = {"T1": ticket("t1"), "T2": ticket("t2")}
    changes = build(
        [proposal(type="add_dependency", target_ref="T2", depends_on_ref="T1")],
        refs,
        deps={},
    )
    assert [c.type for c in changes] == ["add_dependency"]
    assert changes[0].op == {"ticket_id": "t2", "depends_on": "t1"}


def test_한_번에_들어온_두_제안이_서로_순환을_만들면_뒤엣것을_버린다():
    refs = {"T1": ticket("t1"), "T2": ticket("t2")}
    changes = build(
        [
            proposal(type="add_dependency", target_ref="T2", depends_on_ref="T1"),
            proposal(type="add_dependency", target_ref="T1", depends_on_ref="T2"),
        ],
        refs,
        deps={},
    )
    assert len(changes) == 1


def test_완료된_티켓은_건드리지_않는다():
    """한 일을 되돌리는 제안은 받지 않는다."""
    refs = {"T1": ticket("t1", status="resolved")}
    changes = build(
        [proposal(type="drop_ticket", target_ref="T1"),
         proposal(type="reduce_ticket", target_ref="T1", title="줄임", est_minutes=30)],
        refs,
    )
    assert changes == []


def test_120분을_넘는_조각은_거절한다():
    """R1 은 재설계에서도 예외가 없다."""
    refs = {"T1": ticket("t1", est_minutes=200)}
    changes = build(
        [proposal(
            type="split_ticket", target_ref="T1",
            parts=[SplitPart(title="a", est_minutes=130), SplitPart(title="b", est_minutes=70)],
        )],
        refs,
    )
    assert changes == []


def test_조각이_하나뿐이면_분할이_아니다():
    refs = {"T1": ticket("t1")}
    changes = build(
        [proposal(
            type="split_ticket", target_ref="T1",
            parts=[SplitPart(title="a", est_minutes=90)],
        )],
        refs,
    )
    assert changes == []


def test_이미_시작한_티켓은_지우지_않는다():
    refs = {"T1": ticket("t1", status="doing")}
    assert build([proposal(type="drop_ticket", target_ref="T1")], refs) == []


def test_후속_주가_없으면_이월할_게_없다():
    assert build([proposal(type="shift_week", shift_days=7)], {}, downstream=[]) == []


def test_분할을_초안에_적용하면_critic_을_통과한다():
    draft = sample_draft()
    tid = draft.tickets[0].key
    refs = {"T1": ticket(tid, est_minutes=60)}
    changes = build(
        [proposal(
            type="split_ticket", target_ref="T1",
            parts=[SplitPart(title="앞", est_minutes=30), SplitPart(title="뒤", est_minutes=30)],
        )],
        refs,
    )
    merged = apply_to_draft(draft, changes)

    assert len(merged.tickets) == len(draft.tickets) + 1
    assert run_critic(merged, CONSTRAINTS, check_bodies=False).ok
    # 조각은 원래 티켓의 노드를 승계한다
    new_key = changes[0].op["new_ticket_ids"][0]
    assert any(link.ticket_key == new_key and link.node_key == "node_a" for link in merged.links)


def test_티켓_추가는_막힌_티켓_앞에_놓인다():
    draft = sample_draft()
    target = draft.tickets[1]
    refs = {"T1": ticket(target.key, task_id=target.task_key)}
    changes = build(
        [proposal(type="add_ticket", target_ref="T1", title="선행 학습", est_minutes=60)],
        refs,
    )
    merged = apply_to_draft(draft, changes)

    new_key = changes[0].op["new_ticket_id"]
    blocked = next(t for t in merged.tickets if t.key == target.key)
    assert new_key in blocked.depends_on
    assert run_critic(merged, CONSTRAINTS, check_bodies=False).ok


def test_티켓_제거는_그를_가리키던_의존도_함께_지운다():
    draft = sample_draft()
    dropped = draft.tickets[0]
    refs = {"T1": ticket(dropped.key)}
    changes = build([proposal(type="drop_ticket", target_ref="T1")], refs)
    merged = apply_to_draft(draft, changes)

    assert all(t.key != dropped.key for t in merged.tickets)
    assert all(dropped.key not in t.depends_on for t in merged.tickets)
    assert run_critic(merged, CONSTRAINTS, check_bodies=False).ok
