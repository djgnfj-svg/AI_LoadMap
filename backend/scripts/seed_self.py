"""이 프로젝트 자신의 로드맵을 시드로 넣는다 (SPEC §6.2, D10 백필의 기반).

§1.7 이 "시드 데이터가 실제 프로젝트일 것 (가짜 데이터 금지)" 라고 못박았다.
그래서 가짜 프로젝트를 만들지 않고, docs/SPEC.md §6.1 의 실제 일정을 그대로 넣는다.
이미 끝난 일차는 완료 처리하고 이벤트도 실제 날짜로 남긴다.

사용:
    DATABASE_URL=... python scripts/seed_self.py
    DATABASE_URL=... python scripts/seed_self.py --reset   # 기존 시드를 지우고 다시
"""

import argparse
import asyncio
import os
import sys
from datetime import UTC, date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncpg  # noqa: E402

from app.graphs.critic import run_critic  # noqa: E402
from app.graphs.persist import create_project, persist_plan  # noqa: E402
from app.models.schemas import (  # noqa: E402
    Constraints,
    DraftEdge,
    DraftLink,
    DraftMilestone,
    DraftNode,
    DraftTicket,
    DraftWeeklyGoal,
    PlanDraft,
)

TITLE = "Roadmap Planner"
GOAL = (
    "목표를 넣으면 로드맵과 아키텍처가 함께 그려지고, 진행 기록에 따라 스스로 "
    "다시 그려지는 도구를 2주 안에 만들어 원티드 AI 챔피언십에 출품한다."
)
START = date(2026, 9, 7)  # D1
CONSTRAINTS = Constraints(
    duration_weeks=2,
    hours_per_week=40,
    level="advanced",
    stack=["fastapi", "langgraph", "supabase", "react", "react-flow"],
    team_size=1,
)

NODES = [
    ("goal_input", "목표 입력 화면", "client", "frontend"),
    ("board", "티켓 보드", "client", "frontend"),
    ("diagram", "React Flow 다이어그램", "client", "frontend"),
    ("api", "FastAPI 서버", "service", "backend"),
    ("plan_graph", "생성 그래프", "service", "backend"),
    ("critic", "critic 검증", "service", "backend"),
    ("replan_graph", "재설계 그래프", "service", "backend"),
    ("scheduler", "APScheduler", "service", "backend"),
    ("db", "Supabase Postgres", "store", "data"),
    ("events", "이벤트 로그", "store", "data"),
    ("claude", "Claude API", "external", "infra"),
    ("deploy", "배포", "external", "infra"),
]

EDGES = [
    ("goal_input", "api", "목표 · clarify"),
    ("board", "api", "티켓 상태"),
    ("diagram", "api", "노드 상태"),
    ("api", "plan_graph", "생성 실행"),
    ("api", "replan_graph", "재설계 실행"),
    ("plan_graph", "critic", "검증"),
    ("replan_graph", "critic", "검증"),
    ("plan_graph", "claude", "구조화 출력"),
    ("replan_graph", "claude", "진단"),
    ("api", "db", "읽기/쓰기"),
    ("scheduler", "events", "missed 기록"),
    ("events", "db", "집계"),
    ("api", "deploy", "공개 URL"),
]

# (key, 마일스톤, 주차, 제목, 예상분, 노드들, 선행, 완료여부, 완료일차)
TICKETS = [
    ("t01", "m1", 1, "Supabase 스키마 11개 테이블 작성", 90, ["db"], [], True, 1),
    ("t02", "m1", 1, "노드 상태 계산 뷰(v_node_status) 작성", 45, ["db"], ["t01"], True, 1),
    ("t03", "m1", 1, "FastAPI 뼈대 + asyncpg 풀", 60, ["api"], ["t01"], True, 1),
    ("t04", "m1", 1, "POST /projects 동작", 60, ["api"], ["t03"], True, 1),
    ("t05", "m1", 1, "생성 그래프 노드 6개 뼈대", 120, ["plan_graph"], ["t04"], True, 2),
    ("t06", "m1", 1, "Claude 구조화 출력 경계면", 90, ["plan_graph", "claude"], ["t05"], True, 2),
    ("t07", "m1", 1, "emit — 초안을 DB 트리로 저장", 120, ["plan_graph", "db"], ["t05"], True, 2),
    ("t08", "m1", 1, "critic 검증 4종 구현", 120, ["critic"], ["t05"], True, 3),
    ("t09", "m1", 1, "critic 실패 → decompose 재시도 루프", 90, ["critic", "plan_graph"], ["t08"], True, 3),
    ("t10", "m1", 1, "재시도 소진 시 결정적 재분할", 120, ["critic"], ["t09"], True, 3),
    ("t11", "m2", 1, "Vite + React 스캐폴딩, API 클라이언트", 60, ["board"], ["t04"], True, 4),
    ("t12", "m2", 1, "목표 입력 화면 + SSE 진행 표시", 120, ["goal_input"], ["t11"], True, 4),
    ("t13", "m2", 1, "티켓 보드 (마일스톤 > 주차 > 티켓)", 120, ["board"], ["t11"], True, 4),
    ("t14", "m2", 1, "React Flow 커스텀 노드 상태 4종", 120, ["diagram"], ["t11"], True, 5),
    ("t15", "m2", 1, "티켓 완료 → 노드 상태 갱신", 90, ["diagram", "api"], ["t13", "t14"], True, 6),
    ("t16", "m2", 1, "티켓↔노드 양방향 하이라이트", 90, ["diagram", "board"], ["t15"], True, 6),
    ("t17", "m3", 2, "APScheduler 붙이고 missed 자동 기록", 90, ["scheduler", "events"], ["t07"], False, None),
    ("t18", "m3", 2, "실제 이력 백필 스크립트", 90, ["events"], ["t17"], False, None),
    ("t19", "m3", 2, "알람 규칙 5종 (§2.3)", 120, ["scheduler", "events"], ["t17"], False, None),
    ("t20", "m3", 2, "재점검일 자동 생성 (§4.5 SQL)", 90, ["scheduler", "db"], ["t19"], False, None),
    ("t21", "m3", 2, "재설계 그래프 collect_signals → diff", 120, ["replan_graph"], ["t20"], False, None),
    ("t22", "m3", 2, "diff 항목별 승인 UI", 120, ["board", "replan_graph"], ["t21"], False, None),
    ("t23", "m4", 2, "실제 프로젝트로 시드 + 검증", 90, ["events"], ["t18"], False, None),
    ("t24", "m4", 2, "배포 (공개 URL)", 120, ["deploy"], ["t22"], False, None),
    ("t25", "m4", 2, "데모 영상 3분 촬영·편집", 120, ["deploy"], ["t24"], False, None),
]

MILESTONES = [
    ("m1", 1, "동작하는 백엔드", "스키마 · 생성 그래프 · critic 루프 (D1~D3)"),
    ("m2", 2, "보이는 제품", "티켓 보드 · 다이어그램 · 연동 (D4~D6)"),
    ("m3", 3, "감지와 재설계", "이벤트 · 알람 · 재점검 · 재설계 (D7~D9)"),
    ("m4", 4, "제출", "시드 · 배포 · 영상 (D10~D14)"),
]

WEEKLY_GOALS = [
    ("w1", "m1", 1, "1주차 - 백엔드가 목표를 계획으로 바꾼다"),
    ("w2", "m2", 1, "1주차 - 계획이 화면에서 보인다"),
    ("w3", "m3", 2, "2주차 - 막힌 지점을 감지하고 다시 짠다"),
    ("w4", "m4", 2, "2주차 - 내보내고 제출한다"),
]

GOAL_OF = {"m1": "w1", "m2": "w2", "m3": "w3", "m4": "w4"}


def build_draft() -> PlanDraft:
    return PlanDraft(
        milestones=[
            DraftMilestone(key=k, order_index=i, title=t, description=d)
            for k, i, t, d in MILESTONES
        ],
        weekly_goals=[
            DraftWeeklyGoal(key=k, milestone_key=m, week_index=w, title=t)
            for k, m, w, t in WEEKLY_GOALS
        ],
        tickets=[
            DraftTicket(
                key=key,
                weekly_goal_key=GOAL_OF[milestone],
                order_index=i,
                title=title,
                body=(
                    f"## 무엇을\n{title}\n\n"
                    "## 완료 조건\n- [ ] 테스트 통과\n- [ ] 스펙(docs/SPEC.md)과 어긋나지 않음\n\n"
                    f"## 참고\n- 연결 컴포넌트: {', '.join(nodes)}\n"
                ),
                est_minutes=minutes,
                depends_on=list(deps),
            )
            for i, (key, milestone, _w, title, minutes, nodes, deps, _done, _day) in enumerate(
                TICKETS, start=1
            )
        ],
        nodes=[
            DraftNode(node_key=k, label=lab, node_type=nt, layer=lay) for k, lab, nt, lay in NODES
        ],
        edges=[DraftEdge(from_key=f, to_key=t, label=lab) for f, t, lab in EDGES],
        links=[
            DraftLink(ticket_key=key, node_key=node)
            for key, _m, _w, _t, _min, nodes, _d, _done, _day in TICKETS
            for node in nodes
        ],
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="같은 제목의 기존 시드를 지운다")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL 이 필요하다.")

    draft = build_draft()
    result = run_critic(draft, CONSTRAINTS)
    if not result.ok:
        for v in result.violations:
            print(f"  [{v.code}] {v.message}")
        raise SystemExit("시드 데이터가 critic 을 통과하지 못한다. 위를 고쳐라.")

    import json

    conn = await asyncpg.connect(dsn)
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    try:
        async with conn.transaction():
            if args.reset:
                deleted = await conn.execute("delete from projects where title = $1", TITLE)
                print(f"기존 시드 삭제: {deleted}")

            project_id = await create_project(
                conn, user_id=None, goal_text=GOAL, title=TITLE, start_date=START
            )
            await persist_plan(
                conn,
                project_id=project_id,
                title=TITLE,
                constraints=CONSTRAINTS,
                draft=draft,
                start_date=START,
            )
            await _backfill_progress(conn, project_id)
    finally:
        await conn.close()

    print(f"시드 완료: project_id={project_id}")
    print(f"  티켓 {len(draft.tickets)}개 / 노드 {len(draft.nodes)}개 / 엣지 {len(draft.edges)}개")
    print(f"  http://localhost:5173/#/{project_id}")


async def _backfill_progress(conn: asyncpg.Connection, project_id) -> None:
    """이미 끝난 일차를 실제 날짜로 완료 처리한다 (SPEC §6.2 백필)."""
    rows = await conn.fetch(
        "select id, title from tickets where project_id = $1", project_id
    )
    id_by_title = {r["title"]: r["id"] for r in rows}
    node_rows = await conn.fetch(
        "select l.ticket_id, l.node_id from ticket_node_links l "
        "join tickets t on t.id = l.ticket_id where t.project_id = $1",
        project_id,
    )
    nodes_of: dict = {}
    for r in node_rows:
        nodes_of.setdefault(r["ticket_id"], []).append(r["node_id"])

    completed = 0
    for _key, _m, _w, title, _min, _nodes, _deps, done, day in TICKETS:
        if not done or day is None:
            continue
        ticket_id = id_by_title.get(title)
        if ticket_id is None:
            continue
        finished = datetime.combine(
            START + timedelta(days=day - 1), datetime.min.time(), tzinfo=UTC
        ) + timedelta(hours=21)
        await conn.execute(
            "update tickets set status = 'done', completed_at = $2 where id = $1",
            ticket_id,
            finished,
        )
        for node_id in nodes_of.get(ticket_id, [None]):
            await conn.execute(
                "insert into events (project_id, ticket_id, node_id, type, created_at) "
                "values ($1, $2, $3, 'completed', $4)",
                project_id,
                ticket_id,
                node_id,
                finished,
            )
        completed += 1

    await conn.execute(
        """
        update arch_nodes n set status = s.status
        from v_node_status s where s.node_id = n.id and n.project_id = $1
        """,
        project_id,
    )
    print(f"  완료 백필: {completed}개 티켓")


if __name__ == "__main__":
    asyncio.run(main())
