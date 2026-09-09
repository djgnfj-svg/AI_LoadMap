"""생성 그래프 (SPEC §3.3).

intake -> clarify -> decompose -> architect -> link -> critic -> emit
                                     ^                    |
                                     +---- 실패(최대 3회) --+

critic 이 이 그래프의 존재 이유다. 검증 없이 한 번 호출하고 끝나면 LLM 래퍼와 다르지 않다.
재시도가 소진되면 결정적 복구(app/graphs/repair.py)를 거쳐 emit 으로 간다.

clarify 의 "[사용자 응답 대기]"는 그래프를 두 번 실행해 처리한다.
1회차: intake -> clarify -> 질문을 들고 종료.
2회차: 같은 입력 + clarify_answers 로 재실행하면 clarify 를 통과해 decompose 로 간다.
체크포인터가 필요 없고, SPEC §0.3 의 "clarify 1회 고정" 축소와도 맞는다.
"""

from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.graphs import prompts
from app.graphs.critic import run_critic
from app.graphs.llm import Planner
from app.graphs.repair import repair_draft
from app.graphs.state import PlanState
from app.models.schemas import (
    ArchitectResult,
    ClarifyResult,
    Constraints,
    DecomposeResult,
    IntakeResult,
    LinkResult,
    PlanDraft,
)

MAX_CLARIFY_QUESTIONS = 5  # SPEC §3.3


def build_plan_graph(planner: Planner, max_retries: int | None = None):
    """생성 그래프를 컴파일해 돌려준다. planner 를 주입받으므로 테스트에서 가짜를 끼울 수 있다."""

    retries = max_retries if max_retries is not None else get_settings().critic_max_retries

    # ── intake ────────────────────────────────────────────────
    async def intake(state: PlanState) -> dict:
        known = state.get("known") or {}
        known_text = (
            "\n".join(f"- {k}: {v}" for k, v in known.items() if v is not None) or "(없음)"
        )
        result: IntakeResult = await planner.structured(
            system=prompts.SYSTEM,
            prompt=prompts.INTAKE.format(goal_text=state["goal_text"], known=known_text),
            output_model=IntakeResult,
        )
        # 사용자가 직접 준 값이 LLM 추론보다 항상 우선한다.
        merged = result.constraints.model_dump()
        for field, value in known.items():
            if value is not None and field in merged:
                merged[field] = value
        constraints = Constraints(**merged)
        missing = [m for m in result.missing if known.get(m) is None]
        return {"title": result.title, "constraints": constraints, "missing": missing}

    # ── clarify ───────────────────────────────────────────────
    async def clarify(state: PlanState) -> dict:
        missing = state.get("missing") or []
        answers = state.get("clarify_answers") or {}

        # 이미 답을 받았거나 물을 게 없으면 통과한다.
        if not missing or answers:
            constraints = _apply_answers(state["constraints"], answers)
            return {
                "constraints": constraints,
                "awaiting_clarify": False,
                "clarify_questions": [],
            }

        result: ClarifyResult = await planner.structured(
            system=prompts.SYSTEM,
            prompt=prompts.CLARIFY.format(
                missing=", ".join(missing),
                constraints=state["constraints"].model_dump_json(),
            ),
            output_model=ClarifyResult,
        )
        questions = result.questions[:MAX_CLARIFY_QUESTIONS]
        return {"clarify_questions": questions, "awaiting_clarify": bool(questions)}

    def after_clarify(state: PlanState) -> str:
        return "wait" if state.get("awaiting_clarify") else "decompose"

    # ── decompose ─────────────────────────────────────────────
    async def decompose(state: PlanState) -> dict:
        constraints: Constraints = state["constraints"]
        attempt = state.get("attempt", 0)
        prompt = prompts.decompose_prompt(state["goal_text"], constraints)

        critic = state.get("critic")
        if critic and not critic.ok:
            previous = state.get("draft") or PlanDraft()
            prompt += "\n\n" + prompts.DECOMPOSE_RETRY.format(
                violations=prompts.format_violations(critic),
                previous=prompts.format_previous(previous),
                n_ms=len(previous.tasks),
                n_wg=len(previous.weekly_goals),
                n_tk=len(previous.tickets),
            )

        result: DecomposeResult = await planner.structured(
            system=prompts.SYSTEM, prompt=prompt, output_model=DecomposeResult
        )
        draft = state.get("draft") or PlanDraft()
        draft = draft.model_copy(
            update={
                "weekly_goals": result.weekly_goals,
                "tasks": result.tasks,
                "tickets": result.tickets,
            }
        )
        return {"draft": draft, "attempt": attempt + 1}

    # ── architect ─────────────────────────────────────────────
    async def architect(state: PlanState) -> dict:
        constraints: Constraints = state["constraints"]
        draft: PlanDraft = state["draft"]
        plan_text = prompts.format_previous(draft)
        result: ArchitectResult = await planner.structured(
            system=prompts.SYSTEM,
            prompt=prompts.ARCHITECT.format(
                goal_text=state["goal_text"],
                stack=", ".join(constraints.stack) or "미정",
                plan=plan_text,
            ),
            output_model=ArchitectResult,
        )
        return {"draft": draft.model_copy(update={"nodes": result.nodes, "edges": result.edges})}

    # ── link ──────────────────────────────────────────────────
    async def link(state: PlanState) -> dict:
        draft: PlanDraft = state["draft"]
        nodes_text = "\n".join(f"- {n.node_key} ({n.layer}): {n.label}" for n in draft.nodes)
        tickets_text = "\n".join(f"- {t.key}: {t.title}" for t in draft.tickets)
        result: LinkResult = await planner.structured(
            system=prompts.SYSTEM,
            prompt=prompts.LINK.format(nodes=nodes_text, tickets=tickets_text),
            output_model=LinkResult,
        )
        return {"draft": draft.model_copy(update={"links": result.links})}

    # ── critic (LLM 미개입) ────────────────────────────────────
    async def critic_node(state: PlanState) -> dict:
        return {"critic": run_critic(state["draft"], state["constraints"])}

    def after_critic(state: PlanState) -> str:
        critic = state.get("critic")
        if critic and critic.ok:
            return "emit"
        # attempt 는 decompose 호출 횟수다. 첫 호출은 재시도가 아니므로
        # 재시도 가능 횟수는 attempt - 1. "최대 3회 재시도" = decompose 최대 4회.
        if state.get("attempt", 0) <= retries:
            return "decompose"
        return "repair"

    # ── repair (LLM 미개입) ────────────────────────────────────
    async def repair(state: PlanState) -> dict:
        fixed, notes = repair_draft(state["draft"], state["constraints"])
        return {
            "draft": fixed,
            "repairs": (state.get("repairs") or []) + notes,
            "critic": run_critic(fixed, state["constraints"]),
        }

    # ── emit ──────────────────────────────────────────────────
    async def emit(state: PlanState) -> dict:
        # DB 저장은 그래프 밖(app/graphs/persist.py)에서 한다.
        # 그래프는 검증된 초안까지만 책임진다 — 트랜잭션 경계를 그래프 안에 두지 않는다.
        return {"awaiting_clarify": False}

    graph = StateGraph(PlanState)
    graph.add_node("intake", intake)
    graph.add_node("clarify", clarify)
    graph.add_node("decompose", decompose)
    graph.add_node("architect", architect)
    graph.add_node("link", link)
    graph.add_node("critic", critic_node)
    graph.add_node("repair", repair)
    graph.add_node("emit", emit)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "clarify")
    graph.add_conditional_edges(
        "clarify", after_clarify, {"wait": END, "decompose": "decompose"}
    )
    graph.add_edge("decompose", "architect")
    graph.add_edge("architect", "link")
    graph.add_edge("link", "critic")
    graph.add_conditional_edges(
        "critic",
        after_critic,
        {"decompose": "decompose", "repair": "repair", "emit": "emit"},
    )
    graph.add_edge("repair", "emit")
    graph.add_edge("emit", END)

    return graph.compile()


def _apply_answers(constraints: Constraints, answers: dict[str, str]) -> Constraints:
    """clarify 답변을 제약에 반영한다. 숫자로 안 읽히는 답은 무시하고 추론값을 유지한다."""
    if not answers:
        return constraints
    data = constraints.model_dump()
    for field in ("duration_weeks", "hours_per_week", "team_size"):
        raw = answers.get(field)
        if raw is None:
            continue
        digits = "".join(ch for ch in str(raw) if ch.isdigit())
        if digits:
            data[field] = int(digits)
    if answers.get("level") in ("beginner", "intermediate", "advanced"):
        data["level"] = answers["level"]
    if answers.get("stack"):
        data["stack"] = [s.strip() for s in str(answers["stack"]).split(",") if s.strip()]
    return Constraints(**data)
