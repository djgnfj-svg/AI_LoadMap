"""재설계 그래프 (SPEC §3.4).

collect_signals -> diagnose -> replan_scope -> propose -> critic -> diff
                                                 ^          |
                                                 +-- 실패 --+

생성 그래프와 같은 critic 을 쓴다. 재설계 결과도 120분 규칙과 주간 가용시간을
그대로 지켜야 하기 때문이다. 다른 검증을 쓰면 규칙이 두 벌이 된다.

AI 가 등장하는 지점은 두 곳뿐이다 — diagnose 와 propose.
집계(collect_signals)와 검증(critic)에는 개입하지 않는다 (R2).
"""

import logging
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.graphs import prompts, replan
from app.graphs.critic import run_critic
from app.graphs.llm import Planner
from app.models.schemas import (
    Constraints,
    CriticResult,
    DiagnoseResult,
    PlanDraft,
    ReplanChange,
    ReplanDiff,
    ReplanProposal,
    ReplanSignals,
)
from app.services.replan_context import ReplanContext

log = logging.getLogger(__name__)


def _last(_old, new):  # noqa: ANN001
    return new


class ReplanState(TypedDict, total=False):
    context: ReplanContext
    signals: ReplanSignals
    diagnosis: str
    rationale: str
    scope_weekly_goal_id: str
    scope_weekly_goal_title: str
    scope_task_ids: list[str]
    downstream_weekly_goal_ids: list[str]
    ref_to_ticket: dict[str, dict]
    changes: list[ReplanChange]
    merged_draft: PlanDraft
    critic: CriticResult | None
    attempt: Annotated[int, _last]
    repairs: list[str]
    diff: ReplanDiff


def build_replan_graph(planner: Planner, max_retries: int | None = None):
    retries = max_retries if max_retries is not None else get_settings().critic_max_retries

    # ── collect_signals (AI 미개입, 순수 SQL 결과) ─────────────
    async def collect_signals(state: ReplanState) -> dict:
        return {"signals": state["context"].signals}

    # ── diagnose (AI) ─────────────────────────────────────────
    async def diagnose(state: ReplanState) -> dict:
        s = state["signals"]
        result: DiagnoseResult = await planner.structured(
            system=prompts.SYSTEM,
            prompt=prompts.DIAGNOSE.format(
                node_label=s.node_label,
                node_key=s.node_key,
                total=s.total_tickets,
                done=s.done_tickets,
                delayed=s.delayed_tickets,
                missed=s.missed_count,
                deferred=s.deferred_count,
                avg_delay=s.avg_delay_days,
                blocked="\n".join(f"- {r}" for r in s.blocked_reasons) or "- (없음)",
            ),
            output_model=DiagnoseResult,
        )
        return {"diagnosis": result.diagnosis, "rationale": result.rationale}

    # ── replan_scope (R3 — 최대 주 1개, AI 미개입) ─────────────
    # 주가 관리 단위다. 한 번에 다시 그리는 것은 주 하나다.
    async def replan_scope(state: ReplanState) -> dict:
        ctx = state["context"]
        candidates = [w for w in ctx.weeks.values() if w["open"] > 0] or list(
            ctx.weeks.values()
        )
        if not candidates:
            raise RuntimeError("재설계할 주가 없다.")
        # 이 노드에서 가장 많이 지연된 주. 동률이면 앞선 주.
        scope = max(candidates, key=lambda w: (w["delayed"], w["on_node"], -w["week_index"]))

        refs: dict[str, dict] = {}
        rows = [t for t in ctx.tickets.values() if t["weekly_goal_id"] == scope["id"]]
        # 계획의 실제 순서로 정렬한다. 제목순으로 매기면 T번호가 선후관계를 거꾸로 암시한다.
        rows.sort(key=lambda t: (t["task_number"], t["ticket_number"], t["title"]))
        id_to_ref = {}
        for i, ticket in enumerate(rows, start=1):
            ref = f"T{i}"
            id_to_ref[ticket["id"]] = ref
            refs[ref] = ticket
        for ticket in rows:
            ticket["depends_on_refs"] = [
                id_to_ref[d] for d in ticket["depends_on"] if d in id_to_ref
            ]

        downstream = [
            w["id"]
            for w in ctx.weeks.values()
            if w["week_index"] > scope["week_index"]
        ]
        return {
            "scope_weekly_goal_id": scope["id"],
            "scope_weekly_goal_title": scope["title"],
            "scope_task_ids": scope["task_ids"],
            "downstream_weekly_goal_ids": downstream,
            "ref_to_ticket": refs,
        }

    # ── propose (AI) — §3.4 의 "decompose (부분)" ──────────────
    async def propose(state: ReplanState) -> dict:
        ctx = state["context"]
        constraints: Constraints = ctx.constraints
        rows = [
            {**t, "ref": ref, "depends_on_refs": t.get("depends_on_refs", [])}
            for ref, t in state["ref_to_ticket"].items()
        ]
        rows.sort(key=lambda r: int(r["ref"][1:]))

        prompt = prompts.REPLAN.format(
            diagnosis=state["diagnosis"],
            rationale=state["rationale"],
            prescription=prompts.PRESCRIPTION.get(state["diagnosis"], ""),
            week_title=state["scope_weekly_goal_title"],
            tickets=prompts.format_scope_tickets(rows),
            hours_per_week=constraints.hours_per_week,
            capacity=constraints.weekly_capacity_minutes,
            max_min=120,
        )
        critic = state.get("critic")
        if critic and not critic.ok:
            prompt += "\n\n" + prompts.REPLAN_RETRY.format(
                violations=prompts.format_violations(critic), max_min=120
            )

        result: ReplanProposal = await planner.structured(
            system=prompts.SYSTEM, prompt=prompt, output_model=ReplanProposal
        )
        changes = replan.build_changes(
            result.changes,
            ref_to_ticket=state["ref_to_ticket"],
            scope_task_ids=state["scope_task_ids"],
            downstream_weekly_goal_ids=state["downstream_weekly_goal_ids"],
            dependency_map={t["id"]: t["depends_on"] for t in ctx.tickets.values()},
        )
        merged = replan.apply_to_draft(ctx.base_draft, changes)
        return {
            "changes": changes,
            "merged_draft": merged,
            "attempt": state.get("attempt", 0) + 1,
        }

    # ── critic (생성 그래프와 동일) ────────────────────────────
    async def critic_node(state: ReplanState) -> dict:
        # 본문 검증은 끈다 — 이 초안에는 규칙이 생기기 전에 쓰인 기존 티켓이 그대로
        # 실려 있고, 그건 이번 재설계가 고칠 대상이 아니다. 새로 만드는 티켓의
        # 본문 형식은 replan.py 가 맞춘다.
        return {
            "critic": run_critic(
                state["merged_draft"], state["context"].constraints, check_bodies=False
            )
        }

    def after_critic(state: ReplanState) -> str:
        critic = state.get("critic")
        if critic and critic.ok:
            return "diff"
        if state.get("attempt", 0) <= retries:
            return "propose"
        return "diff"  # 남은 위반은 diff 에 그대로 실어 사용자에게 보여준다

    # ── diff (§2.4 4단계 — 항목별 승인 대기) ───────────────────
    async def diff(state: ReplanState) -> dict:
        critic = state.get("critic")
        residual = list(critic.violations) if critic and not critic.ok else []
        return {
            "diff": ReplanDiff(
                signals=state["signals"],
                diagnosis=state["diagnosis"],  # type: ignore[arg-type]
                rationale=state["rationale"],
                scope_weekly_goal_id=state["scope_weekly_goal_id"],
                scope_weekly_goal_title=state["scope_weekly_goal_title"],
                changes=state.get("changes") or [],
                residual_violations=residual,
                repairs=state.get("repairs") or [],
            )
        }

    graph = StateGraph(ReplanState)
    graph.add_node("collect_signals", collect_signals)
    graph.add_node("diagnose", diagnose)
    graph.add_node("replan_scope", replan_scope)
    graph.add_node("propose", propose)
    graph.add_node("critic", critic_node)
    graph.add_node("diff", diff)

    graph.add_edge(START, "collect_signals")
    graph.add_edge("collect_signals", "diagnose")
    graph.add_edge("diagnose", "replan_scope")
    graph.add_edge("replan_scope", "propose")
    graph.add_edge("propose", "critic")
    graph.add_conditional_edges("critic", after_critic, {"propose": "propose", "diff": "diff"})
    graph.add_edge("diff", END)

    return graph.compile()


__all__ = ["build_replan_graph", "ReplanState"]
