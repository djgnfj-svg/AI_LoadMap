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
    scope_milestone_id: str
    scope_milestone_title: str
    scope_goal_ids: list[str]
    downstream_milestone_ids: list[str]
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

    # ── replan_scope (R3 — 최대 마일스톤 1개, AI 미개입) ───────
    async def replan_scope(state: ReplanState) -> dict:
        ctx = state["context"]
        candidates = [m for m in ctx.milestones.values() if m["open"] > 0] or list(
            ctx.milestones.values()
        )
        if not candidates:
            raise RuntimeError("재설계할 마일스톤이 없다.")
        # 이 노드에서 가장 많이 지연된 마일스톤. 동률이면 앞선 마일스톤.
        scope = max(candidates, key=lambda m: (m["delayed"], m["on_node"], -m["order_index"]))

        refs: dict[str, dict] = {}
        rows = [t for t in ctx.tickets.values() if t["milestone_id"] == scope["id"]]
        # 계획의 실제 순서로 정렬한다. 제목순으로 매기면 T번호가 선후관계를 거꾸로 암시한다.
        rows.sort(key=lambda t: (t["week_index"], t["order_index"], t["title"]))
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
            m["id"]
            for m in ctx.milestones.values()
            if m["order_index"] > scope["order_index"]
        ]
        return {
            "scope_milestone_id": scope["id"],
            "scope_milestone_title": scope["title"],
            "scope_goal_ids": scope["goal_ids"],
            "downstream_milestone_ids": downstream,
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
            milestone_title=state["scope_milestone_title"],
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
            scope_goal_ids=state["scope_goal_ids"],
            downstream_milestone_ids=state["downstream_milestone_ids"],
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
        return {"critic": run_critic(state["merged_draft"], state["context"].constraints)}

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
                scope_milestone_id=state["scope_milestone_id"],
                scope_milestone_title=state["scope_milestone_title"],
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
