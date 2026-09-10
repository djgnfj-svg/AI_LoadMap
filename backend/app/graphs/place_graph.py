"""티켓 투입 그래프 (SPEC §3.7).

propose -> critic -> diff
   ^         |
   +- 실패 --+

만들다 「아 이것도 해야 하네」가 떠올랐을 때, 그 일 하나를 받아 **어디에 놓이고
무엇 다음인지**를 정한다. 계획을 세워 주는 도구는 많다. 계획대로 안 될 때 얽힌 것을
풀어 주는 것이 이 제품의 주장이고, 그 주장이 사는 자리가 여기다.

생성·재설계 그래프와 **같은 critic** 을 쓴다. 새로 들어온 티켓도 120분 규칙과 주간
가용시간을 그대로 지켜야 한다. 다른 검증을 쓰면 규칙이 두 벌이 된다.

AI 가 등장하는 지점은 propose 하나뿐이다. 자리를 검증하는 것은 결정적 규칙이다 (R2).
"""

import logging
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.graphs import placement, prompts, replan
from app.graphs.critic import run_critic
from app.graphs.llm import Planner
from app.models.schemas import (
    CriticResult,
    PlacementDiff,
    PlacementResult,
    PlanDraft,
    ReplanChange,
)
from app.services.placement_context import PlacementContext

log = logging.getLogger(__name__)


def _last(_old, new):  # noqa: ANN001
    return new


class PlaceState(TypedDict, total=False):
    context: PlacementContext
    domain: str | None
    title: str
    body: str
    changes: list[ReplanChange]
    placement_line: str
    reason: str
    merged_draft: PlanDraft
    critic: CriticResult | None
    attempt: Annotated[int, _last]
    diff: PlacementDiff


def build_place_graph(planner: Planner, max_retries: int | None = None):
    retries = max_retries if max_retries is not None else get_settings().critic_max_retries

    # ── propose (AI) ──────────────────────────────────────────
    async def propose(state: PlaceState) -> dict:
        ctx = state["context"]
        tickets = [
            {**t, "ref": ref} for ref, t in ctx.ref_to_ticket.items()
        ]
        tasks = [{**k, "ref": ref} for ref, k in ctx.ref_to_task.items()]

        prompt = prompts.place_prompt(
            state["title"],
            state.get("body") or "",
            plan=prompts.format_plan_for_place(tasks, tickets),
            nodes=ctx.nodes,
            constraints=ctx.constraints,
            domain=state.get("domain"),
        )
        critic = state.get("critic")
        if critic and not critic.ok:
            prompt += "\n\n" + prompts.PLACE_RETRY.format(
                violations=prompts.format_violations(critic),
                max_min=120,
            )

        result: PlacementResult = await planner.structured(
            system=prompts.system(state.get("domain")),
            prompt=prompt,
            output_model=PlacementResult,
        )
        changes, line = placement.build_placement_changes(
            result,
            fallback_title=state["title"],
            ref_to_ticket=ctx.ref_to_ticket,
            ref_to_task=ctx.ref_to_task,
            node_keys={n["node_key"] for n in ctx.nodes},
            dependency_map=ctx.dependency_map,
        )
        return {
            "changes": changes,
            "placement_line": line,
            "reason": result.reason,
            "merged_draft": replan.apply_to_draft(ctx.base_draft, changes),
            "attempt": state.get("attempt", 0) + 1,
        }

    # ── critic (생성·재설계 그래프와 동일) ─────────────────────
    async def critic_node(state: PlaceState) -> dict:
        # 본문 검증은 끈다 — 이 초안에는 규칙이 생기기 전에 쓰인 기존 티켓이 그대로
        # 실려 있고, 그건 이번 투입이 고칠 대상이 아니다.
        return {
            "critic": run_critic(
                state["merged_draft"], state["context"].constraints, check_bodies=False
            )
        }

    def after_critic(state: PlaceState) -> str:
        critic = state.get("critic")
        if critic and critic.ok:
            return "diff"
        if state.get("attempt", 0) <= retries:
            return "propose"
        return "diff"  # 남은 위반은 diff 에 실어 사용자에게 보여준다

    # ── diff (승인 대기) ──────────────────────────────────────
    async def diff(state: PlaceState) -> dict:
        critic = state.get("critic")
        return {
            "diff": PlacementDiff(
                title=state["title"],
                placement=state.get("placement_line") or "",
                reason=state.get("reason") or "",
                changes=state.get("changes") or [],
                residual_violations=list(critic.violations)
                if critic and not critic.ok
                else [],
            )
        }

    graph = StateGraph(PlaceState)
    graph.add_node("propose", propose)
    graph.add_node("critic", critic_node)
    graph.add_node("diff", diff)

    graph.add_edge(START, "propose")
    graph.add_edge("propose", "critic")
    graph.add_conditional_edges("critic", after_critic, {"propose": "propose", "diff": "diff"})
    graph.add_edge("diff", END)

    return graph.compile()
