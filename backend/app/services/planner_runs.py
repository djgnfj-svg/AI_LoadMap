"""생성 그래프 실행 관리 (SPEC §3.5 /projects, /projects/{id}/stream, /projects/{id}/clarify).

APScheduler 를 프로세스 안에서 돌리는 구성(SPEC §3.1)이라 이미 단일 프로세스를 전제한다.
실행 상태도 같은 전제로 메모리에 둔다. 프로세스가 죽으면 진행 중이던 생성은 사라지고,
사용자는 다시 요청하면 된다 — 완성된 계획은 DB 에 있으므로 잃는 게 없다.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from app import db
from app.graphs.llm import Planner
from app.graphs.persist import persist_plan
from app.graphs.plan_graph import build_plan_graph
from app.models.schemas import ClarifyQuestion, Constraints, PlanDraft

log = logging.getLogger(__name__)

RunStatus = Literal["running", "awaiting_clarify", "done", "failed"]

# 그래프 노드 -> 사용자에게 보여줄 한 줄 (SPEC §5 "SSE로 단계별 표시")
NODE_LABELS = {
    "intake": "목표에서 제약을 읽는 중",
    "clarify": "빠진 정보를 확인하는 중",
    "decompose": "마일스톤 · 주차별 목표 · 티켓으로 쪼개는 중",
    "architect": "아키텍처를 그리는 중",
    "link": "티켓과 컴포넌트를 잇는 중",
    "critic": "검증하는 중",
    "repair": "검증에 걸린 부분을 고치는 중",
    "emit": "저장하는 중",
}


@dataclass
class PlanRun:
    project_id: uuid.UUID
    goal_text: str
    known: dict[str, Any]
    status: RunStatus = "running"
    questions: list[ClarifyQuestion] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)
    error: str | None = None
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    task: asyncio.Task | None = None


class PlanRunner:
    def __init__(self, planner: Planner, max_retries: int | None = None) -> None:
        self._graph = build_plan_graph(planner, max_retries=max_retries)
        self._runs: dict[uuid.UUID, PlanRun] = {}

    def get(self, project_id: uuid.UUID) -> PlanRun | None:
        return self._runs.get(project_id)

    def start(
        self,
        project_id: uuid.UUID,
        goal_text: str,
        known: dict[str, Any],
        clarify_answers: dict[str, str] | None = None,
    ) -> PlanRun:
        run = PlanRun(project_id=project_id, goal_text=goal_text, known=known)
        self._runs[project_id] = run
        run.task = asyncio.create_task(self._execute(run, clarify_answers or {}))
        return run

    async def _execute(self, run: PlanRun, clarify_answers: dict[str, str]) -> None:
        state: dict[str, Any] = {
            "goal_text": run.goal_text,
            "known": run.known,
            "clarify_answers": clarify_answers,
            "attempt": 0,
        }
        final: dict[str, Any] = dict(state)
        try:
            async for chunk in self._graph.astream(state, stream_mode="updates"):
                for node, update in chunk.items():
                    final.update(update)
                    await run.queue.put(self._node_event(node, update))

            if final.get("awaiting_clarify"):
                run.questions = final.get("clarify_questions") or []
                run.status = "awaiting_clarify"
                await run.queue.put(
                    {
                        "event": "clarify",
                        "questions": [q.model_dump() for q in run.questions],
                    }
                )
                return

            await self._persist(run, final)
            run.repairs = final.get("repairs") or []
            run.status = "done"
            await run.queue.put(
                {
                    "event": "done",
                    "project_id": str(run.project_id),
                    "repairs": run.repairs,
                }
            )
        except Exception as exc:  # noqa: BLE001 — 실패 사유를 그대로 사용자에게 전달한다
            log.exception("생성 그래프 실패: project_id=%s", run.project_id)
            run.status = "failed"
            run.error = str(exc)
            await run.queue.put({"event": "error", "message": str(exc)})
        finally:
            await run.queue.put({"event": "__eof__"})

    def _node_event(self, node: str, update: dict[str, Any]) -> dict[str, Any]:
        event: dict[str, Any] = {
            "event": "step",
            "node": node,
            "label": NODE_LABELS.get(node, node),
        }
        critic = update.get("critic")
        if node == "critic" and critic is not None:
            event["ok"] = critic.ok
            event["violations"] = [v.model_dump() for v in critic.violations]
        if node == "repair":
            event["repairs"] = update.get("repairs") or []
        draft = update.get("draft")
        if isinstance(draft, PlanDraft):
            event["counts"] = {
                "milestones": len(draft.milestones),
                "weekly_goals": len(draft.weekly_goals),
                "tickets": len(draft.tickets),
                "nodes": len(draft.nodes),
                "edges": len(draft.edges),
                "links": len(draft.links),
            }
        return event

    async def _persist(self, run: PlanRun, final: dict[str, Any]) -> None:
        constraints: Constraints | None = final.get("constraints")
        draft: PlanDraft | None = final.get("draft")
        if constraints is None or draft is None:
            raise RuntimeError("검증된 초안이 없다. 그래프가 emit 까지 가지 못했다.")
        async with db.transaction() as conn:
            await persist_plan(
                conn,
                project_id=run.project_id,
                title=final.get("title") or "제목 없음",
                constraints=constraints,
                draft=draft,
            )
