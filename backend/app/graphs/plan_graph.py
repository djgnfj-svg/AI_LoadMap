"""생성 그래프 (SPEC §3.3).

intake -> interview -> decompose -> architect -> link -> critic -> emit
                                     ^                    |
                                     +---- 실패(최대 3회) --+

critic 이 이 그래프의 존재 이유다. 검증 없이 한 번 호출하고 끝나면 LLM 래퍼와 다르지 않다.
재시도가 소진되면 결정적 복구(app/graphs/repair.py)를 거쳐 emit 으로 간다.

interview 의 "[사용자 응답 대기]"는 그래프를 여러 번 실행해 처리한다.
1회차: intake -> interview -> 1라운드 질문(고정)을 들고 종료.
2회차: 같은 입력 + interview(지금까지 문답) + clarify_answers 로 재실행.
       답을 채우고, 아직 모르는 게 있으면 2라운드 질문을 들고 다시 종료.
3회차: 라운드 상한에 닿으면 통과해 decompose 로 간다.

체크포인터가 필요 없다 — 이어가는 데 필요한 것이 전부 `interview`(문답 전문) 하나이고,
그것은 DB(`projects.interview`)에 있다. 프로세스가 죽어도 인터뷰가 이어진다.
"""

from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.graphs import interview as interview_rules
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
    InterviewTurn,
    LinkResult,
    PlanDraft,
)


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

    # ── interview ─────────────────────────────────────────────
    async def interview(state: PlanState) -> dict:
        """청사진을 묻고, 받은 답을 원문 그대로 들고 간다.

        1라운드 질문은 고정이다(LLM 미개입). 2라운드부터 LLM 이 1라운드 답을 읽고
        아직 모르는 것만 되묻는다. 상한은 interview.MAX_ROUNDS.
        """
        turns: list[InterviewTurn] = list(state.get("interview") or [])
        answers = state.get("clarify_answers") or {}

        turns = interview_rules.record_answers(turns, answers)
        constraints = interview_rules.apply_answers(state["constraints"], answers)
        round_no = interview_rules.current_round(turns)

        def wait(questions: list, next_turns: list[InterviewTurn]) -> dict:
            return {
                "constraints": constraints,
                "interview": next_turns,
                "clarify_questions": questions,
                "awaiting_clarify": True,
            }

        def proceed(next_turns: list[InterviewTurn]) -> dict:
            return {
                "constraints": constraints,
                "interview": next_turns,
                "clarify_questions": [],
                "awaiting_clarify": False,
            }

        # 아직 아무것도 안 물었다 — 1라운드.
        if round_no == 0:
            questions = interview_rules.first_round(state.get("missing") or [], constraints)
            turns += [
                InterviewTurn(round=1, field=q.field, question=q.question) for q in questions
            ]
            return wait(questions, turns)

        # 이번 라운드 답이 아직 안 들어왔다 — 같은 질문을 그대로 들고 기다린다.
        # (새로고침 뒤 재실행되는 경우다. 질문을 다시 만들지 않는다.)
        if not interview_rules.answered_current_round(turns, answers):
            return wait(interview_rules.pending(turns), turns)

        if round_no >= interview_rules.MAX_ROUNDS:
            return proceed(turns)

        result: ClarifyResult = await planner.structured(
            system=prompts.SYSTEM,
            prompt=prompts.FOLLOWUP.format(
                goal_text=state["goal_text"],
                transcript=prompts.format_transcript(turns),
                constraints=constraints.model_dump_json(),
            ),
            output_model=ClarifyResult,
        )
        asked = {t.field for t in turns}
        questions = [q for q in result.questions if q.field not in asked][
            : interview_rules.MAX_QUESTIONS_PER_ROUND
        ]
        if not questions:
            return proceed(turns)

        turns += [
            InterviewTurn(round=round_no + 1, field=q.field, question=q.question)
            for q in questions
        ]
        return wait(questions, turns)

    def after_interview(state: PlanState) -> str:
        return "wait" if state.get("awaiting_clarify") else "decompose"

    # ── decompose ─────────────────────────────────────────────
    async def decompose(state: PlanState) -> dict:
        constraints: Constraints = state["constraints"]
        attempt = state.get("attempt", 0)
        prompt = prompts.decompose_prompt(
            state["goal_text"], constraints, state.get("interview") or []
        )

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
    graph.add_node("interview", interview)
    graph.add_node("decompose", decompose)
    graph.add_node("architect", architect)
    graph.add_node("link", link)
    graph.add_node("critic", critic_node)
    graph.add_node("repair", repair)
    graph.add_node("emit", emit)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "interview")
    graph.add_conditional_edges(
        "interview", after_interview, {"wait": END, "decompose": "decompose"}
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
