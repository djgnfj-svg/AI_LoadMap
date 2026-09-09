"""생성 그래프 (SPEC §3.3). critic 실패 -> decompose 재시도 루프가 이 그래프의 존재 이유다."""

import pytest

from app.graphs.interview import MAX_ROUNDS as INTERVIEW_ROUNDS
from app.graphs.plan_graph import build_plan_graph
from app.models.schemas import Constraints, PlanDraft
from tests.fakes import FakePlanner, make_decompose
from tests.helpers import drive_plan_graph

BASE = {"goal_text": "FastAPI 로 로드맵 도구 만들기", "known": {}, "attempt": 0}


async def step(planner: FakePlanner, max_retries: int = 3, **state) -> dict:
    """그래프를 한 번 돌린다. 인터뷰 대기에서 멈추면 멈춘 채로 돌려준다."""
    graph = build_plan_graph(planner, max_retries=max_retries)
    return await graph.ainvoke({**BASE, **state})


async def confirm(planner: FakePlanner, result: dict, max_retries: int = 3, **state) -> dict:
    """사용자가 청사진 초안을 그대로 확정한 뒤 이어서 돈다."""
    return await step(
        planner,
        max_retries,
        **{
            **state,
            "interview": result["interview"],
            "blueprint": result["blueprint"].model_copy(update={"confirmed": True}),
        },
    )


async def run(planner: FakePlanner, max_retries: int = 3, **state) -> dict:
    """인터뷰에 답해가며 끝까지 돌린다. API 가 하는 일과 같다."""
    graph = build_plan_graph(planner, max_retries=max_retries)
    return await drive_plan_graph(graph, {**BASE, **state}, rounds=INTERVIEW_ROUNDS + 1)


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


async def test_처음에는_청사진부터_묻고_멈춘다():
    """SPEC §3.3 인터뷰 — 목표만 받고 바로 쪼개지 않는다. 첫 질문은 청사진이다."""
    planner = FakePlanner()
    result = await step(planner)

    assert result["awaiting_clarify"] is True
    fields = [q.field for q in result["clarify_questions"]]
    assert fields[0] == "blueprint"
    assert fields[:4] == ["blueprint", "done_when", "starting_point", "deadline"]
    assert decompose_calls(planner) == 0  # 답을 받기 전에는 분해하지 않는다
    # 1라운드 질문은 LLM 이 만들지 않는다.
    assert "ClarifyResult" not in planner.calls


async def test_추측한_가용시간은_1라운드에_같이_묻는다():
    planner = FakePlanner(missing=["hours_per_week"])
    result = await step(planner)

    assert [q.field for q in result["clarify_questions"]][-1] == "hours_per_week"


async def test_답변_원문이_decompose_프롬프트에_들어간다():
    """이 테스트가 이 기능의 전부다 — 답이 계획에 닿지 않으면 인터뷰는 장식이다."""
    seen: list[str] = []

    class Recording(FakePlanner):
        async def structured(self, *, system, prompt, output_model):
            if output_model.__name__ == "DecomposeResult":
                seen.append(prompt)
            return await super().structured(system=system, prompt=prompt, output_model=output_model)

    planner = Recording()
    first = await step(planner)
    answers = {q.field: "" for q in first["clarify_questions"]}
    answers["blueprint"] = "친구 4명이 30분 세션을 끊김 없이 도는 전용 서버 코옵 게임"
    answered = await step(planner, interview=first["interview"], clarify_answers=answers)
    result = await confirm(planner, answered)

    assert not result.get("awaiting_clarify")
    assert len(seen) == 1
    assert "친구 4명이 30분 세션을 끊김 없이 도는 전용 서버 코옵 게임" in seen[0]


async def test_답에서_읽은_기간은_제약이_된다():
    # 가용시간은 intake 가 추측했다고 보고 1라운드에서 같이 묻게 한다.
    planner = FakePlanner(missing=["hours_per_week"])
    first = await step(planner)
    answered = await step(
        planner,
        interview=first["interview"],
        clarify_answers={"deadline": "3개월 안에", "hours_per_week": "주 20시간이요"},
    )
    result = await confirm(planner, answered)

    assert result["constraints"].duration_weeks == 13  # 3개월 = 13주
    assert result["constraints"].hours_per_week == 20
    assert result["critic"].ok


async def test_답이_모자라면_한_번_더_묻는다():
    """2라운드는 LLM 이 1라운드 답을 읽고 정한다."""
    planner = FakePlanner(followups=["audience"])
    first = await step(planner)
    second = await step(
        planner,
        interview=first["interview"],
        clarify_answers={q.field: "짧게" for q in first["clarify_questions"]},
    )

    assert second["awaiting_clarify"] is True
    assert [q.field for q in second["clarify_questions"]] == ["audience"]
    assert decompose_calls(planner) == 0


async def test_라운드_상한에_닿으면_더_묻지_않는다():
    """계획을 만들기도 전에 사람을 지치게 하지 않는다 (interview.MAX_ROUNDS)."""
    planner = FakePlanner(followups=["audience"])
    result = await run(planner)  # 매 라운드 답해가며 끝까지

    assert not result.get("awaiting_clarify")
    assert result["critic"].ok
    assert max(t.round for t in result["interview"]) == INTERVIEW_ROUNDS


async def test_전부_건너뛰어도_계획은_나온다():
    """빈 답도 답이다. 같은 질문을 영원히 다시 받지 않는다."""
    planner = FakePlanner()
    first = await step(planner)
    answered = await step(
        planner,
        interview=first["interview"],
        clarify_answers={q.field: "" for q in first["clarify_questions"]},
    )
    result = await confirm(planner, answered)

    assert not result.get("awaiting_clarify")
    assert result["critic"].ok


async def test_답을_안_보내면_같은_질문을_그대로_다시_준다():
    """새로고침 뒤 재실행되는 경우다. 질문을 새로 만들지 않는다."""
    planner = FakePlanner()
    first = await step(planner)
    again = await step(planner, interview=first["interview"])

    assert again["awaiting_clarify"] is True
    assert [q.field for q in again["clarify_questions"]] == [
        q.field for q in first["clarify_questions"]
    ]
    assert len(again["interview"]) == len(first["interview"])


async def test_사용자가_직접_준_제약은_LLM_추론을_이긴다():
    planner = FakePlanner(missing=["hours_per_week"])
    result = await run(planner, known={"hours_per_week": 25})

    assert result["constraints"].hours_per_week == 25


async def test_그래프는_SPEC_3_3_의_노드를_전부_가진다():
    graph = build_plan_graph(FakePlanner())
    nodes = set(graph.get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {
        "intake", "interview", "blueprint", "decompose",
        "architect", "link", "critic", "repair", "emit",
    }


@pytest.mark.parametrize("stream_mode", ["updates"])
async def test_노드별_진행상황을_스트리밍한다(stream_mode):
    """SPEC §5 — SSE 로 단계별 표시."""
    planner = FakePlanner()
    graph = build_plan_graph(planner, max_retries=3)
    # 인터뷰와 청사진 확정을 먼저 끝낸다 — 그 뒤 한 번에 계획까지 간다.
    first = await step(planner)
    answered = await step(
        planner,
        interview=first["interview"],
        clarify_answers={q.field: "답" for q in first["clarify_questions"]},
    )
    seen = []
    async for chunk in graph.astream(
        {
            **BASE,
            "interview": answered["interview"],
            "blueprint": answered["blueprint"].model_copy(update={"confirmed": True}),
        },
        stream_mode=stream_mode,
    ):
        seen.extend(chunk.keys())

    assert seen == [
        "intake", "interview", "blueprint", "decompose", "architect", "link", "critic", "emit"
    ]


async def test_draft_는_단계마다_누적된다():
    planner = FakePlanner()
    result = await run(planner)
    draft: PlanDraft = result["draft"]

    assert draft.weekly_goals and draft.tasks and draft.tickets
    assert draft.nodes and draft.edges and draft.links
    assert isinstance(result["constraints"], Constraints)


# ── 완성 청사진 (§3.3) ─────────────────────────────────────────
async def test_인터뷰_답에서_완성_기준을_세운다():
    planner = FakePlanner()
    result = await run(planner)

    assert "BlueprintResult" in planner.calls
    assert [c.key for c in result["draft"].blueprint.criteria] == ["sc1", "sc2"]


async def test_전부_건너뛰면_기준을_지어내지_않는다():
    """없는 것도 사실이다. AI 가 완성 조건을 대신 정하지 않는다."""
    planner = FakePlanner()
    first = await step(planner)
    answered = await step(
        planner,
        interview=first["interview"],
        clarify_answers={q.field: "" for q in first["clarify_questions"]},
    )
    result = await confirm(planner, answered)

    assert "BlueprintResult" not in planner.calls
    assert result["draft"].blueprint.criteria == []
    assert result["critic"].ok  # 기준이 없으면 커버리지도 따지지 않는다


async def test_기준을_안_맡은_계획은_다시_쪼갠다():
    """critic 이 커버리지를 잡고 decompose 로 되돌린다 (LLM 미개입 검증)."""
    planner = FakePlanner(
        decompose_results=[
            make_decompose(covers=[[], []]),           # 아무 주도 안 맡았다
            make_decompose(covers=[["sc1"], ["sc2"]]),  # 고쳐서 다시 냄
        ]
    )
    result = await run(planner)

    assert decompose_calls(planner) == 2
    assert result["critic"].ok


async def test_기준을_끝내_못_맡으면_복구가_마지막_주로_모은다():
    planner = FakePlanner(decompose_results=[make_decompose(covers=[[], []])])
    result = await run(planner, max_retries=1)

    assert result["critic"].ok
    assert any("확인이 필요하다" in n for n in result["repairs"])


async def test_완료_조건이_부실하면_다시_쪼갠다():
    """§2.2 본문 형식을 프롬프트만 요구하고 검사하지 않으면 지켜지지 않는다."""
    weak = make_decompose()
    for t in weak.tickets:
        t.body = "## 무엇을\n한 문장\n"
    planner = FakePlanner(decompose_results=[weak, make_decompose()])
    result = await run(planner)

    assert decompose_calls(planner) == 2
    assert result["critic"].ok
