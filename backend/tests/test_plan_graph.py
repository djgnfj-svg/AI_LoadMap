"""생성 그래프 (SPEC §3.3). critic 실패 -> decompose 재시도 루프가 이 그래프의 존재 이유다."""

import pytest

from app.graphs.plan_graph import build_plan_graph
from app.models.schemas import Constraints, PlanDraft
from tests.fakes import FakePlanner, make_decompose


async def run(planner: FakePlanner, max_retries: int = 3, **state) -> dict:
    graph = build_plan_graph(planner, max_retries=max_retries)
    base = {"goal_text": "FastAPI 로 로드맵 도구 만들기", "known": {}, "attempt": 0}
    base.update(state)
    return await graph.ainvoke(base)


def decompose_calls(planner: FakePlanner) -> int:
    return planner.calls.count("DecomposeResult")


async def test_한번에_통과하면_재시도하지_않는다():
    planner = FakePlanner()
    result = await run(planner)

    assert result["critic"].ok
    assert decompose_calls(planner) == 1
    assert result["attempt"] == 1
    assert not result.get("repairs")


async def test_120분_위반이면_decompose_로_되돌아간다():
    """D3 완료 기준 — 위반 시 재분할이 실제로 동작한다."""
    planner = FakePlanner(
        decompose_results=[
            make_decompose(est_minutes=200),  # R1 위반
            make_decompose(est_minutes=90),   # 고쳐서 다시 냄
        ]
    )
    result = await run(planner)

    assert decompose_calls(planner) == 2
    assert result["critic"].ok
    assert all(t.est_minutes <= 120 for t in result["draft"].tickets)


async def test_재시도_상한을_넘으면_결정적_복구로_간다():
    planner = FakePlanner(decompose_results=[make_decompose(est_minutes=200)])  # 계속 위반
    result = await run(planner, max_retries=3)

    # 최초 1회 + 재시도 3회
    assert decompose_calls(planner) == 4
    assert result["repairs"]
    assert result["critic"].ok
    assert all(t.est_minutes <= 120 for t in result["draft"].tickets)


async def test_재시도_0회면_바로_복구로_간다():
    planner = FakePlanner(decompose_results=[make_decompose(est_minutes=200)])
    result = await run(planner, max_retries=0)

    assert decompose_calls(planner) == 1
    assert result["repairs"]
    assert result["critic"].ok


async def test_재시도_프롬프트에_위반_내용이_들어간다():
    seen: list[str] = []

    class Recording(FakePlanner):
        async def structured(self, *, system, prompt, output_model):
            if output_model.__name__ == "DecomposeResult":
                seen.append(prompt)
            return await super().structured(system=system, prompt=prompt, output_model=output_model)

    planner = Recording(
        decompose_results=[make_decompose(est_minutes=200), make_decompose(est_minutes=90)]
    )
    await run(planner)

    assert len(seen) == 2
    assert "ticket_over_120min" not in seen[0]     # 첫 호출엔 위반이 없다
    assert "ticket_over_120min" in seen[1]         # 재시도엔 무엇이 걸렸는지 들어간다
    assert "t1" in seen[1]                         # 이전 초안도 같이 준다


async def test_부족한_정보가_있으면_clarify_에서_멈춘다():
    planner = FakePlanner(missing=["hours_per_week", "level"])
    result = await run(planner)

    assert result["awaiting_clarify"] is True
    assert [q.field for q in result["clarify_questions"]] == ["hours_per_week", "level"]
    assert decompose_calls(planner) == 0  # 답을 받기 전에는 분해하지 않는다


async def test_clarify_답변을_주면_이어서_진행한다():
    planner = FakePlanner(missing=["hours_per_week"])
    result = await run(planner, clarify_answers={"hours_per_week": "주 20시간이요"})

    assert not result.get("awaiting_clarify")
    assert result["constraints"].hours_per_week == 20
    assert result["critic"].ok


async def test_사용자가_직접_준_제약은_LLM_추론을_이긴다():
    planner = FakePlanner(missing=["hours_per_week"])
    result = await run(planner, known={"hours_per_week": 25})

    assert result["constraints"].hours_per_week == 25
    assert not result.get("awaiting_clarify")  # 사용자가 이미 준 값은 되묻지 않는다


async def test_그래프는_SPEC_3_3_의_노드를_전부_가진다():
    graph = build_plan_graph(FakePlanner())
    nodes = set(graph.get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {
        "intake", "clarify", "decompose", "architect", "link", "critic", "repair", "emit"
    }


@pytest.mark.parametrize("stream_mode", ["updates"])
async def test_노드별_진행상황을_스트리밍한다(stream_mode):
    """SPEC §5 — SSE 로 단계별 표시."""
    graph = build_plan_graph(FakePlanner(), max_retries=3)
    seen = []
    async for chunk in graph.astream(
        {"goal_text": "목표", "known": {}, "attempt": 0}, stream_mode=stream_mode
    ):
        seen.extend(chunk.keys())

    assert seen == ["intake", "clarify", "decompose", "architect", "link", "critic", "emit"]


async def test_draft_는_단계마다_누적된다():
    planner = FakePlanner()
    result = await run(planner)
    draft: PlanDraft = result["draft"]

    assert draft.milestones and draft.weekly_goals and draft.tickets
    assert draft.nodes and draft.edges and draft.links
    assert isinstance(result["constraints"], Constraints)
