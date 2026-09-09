"""목업 Planner — API 키 없이 생성·재설계 그래프를 끝까지 돌린다.

용도는 두 가지다.
  1. 개발·데모: ANTHROPIC_API_KEY 없이 화면 전체를 굴려본다.
  2. 테스트: 그래프의 분기(critic 재시도, 진단별 처방)를 결정적으로 재현한다.

일부러 완벽하지 않게 만든다. 목업이 항상 critic 을 한 번에 통과하면
재시도 루프가 데모에서 절대 안 보인다. 첫 분해는 120분을 넘겨서 낸다.

이 파일은 LLM 을 흉내낼 뿐 부르지 않는다. 실제 호출은 app/graphs/llm.py 하나뿐이다.
"""

import math
import re
from typing import Any

from pydantic import BaseModel

from app.models.schemas import (
    ArchitectResult,
    BlueprintResult,
    ClarifyQuestion,
    ClarifyResult,
    Constraints,
    DecomposeResult,
    DiagnoseResult,
    DraftEdge,
    DraftLink,
    DraftNode,
    DraftTask,
    DraftTicket,
    DraftWeeklyGoal,
    IntakeResult,
    LinkResult,
    ProposedChange,
    ReplanProposal,
    SplitPart,
    SuccessCriterion,
)

_PHASES = [
    ("기반 세우기", "돌아가는 최소 골격을 만든다"),
    ("핵심 기능", "제품이라고 부를 수 있는 기능을 붙인다"),
    ("다듬기", "쓸 만해질 때까지 고친다"),
    ("내보내기", "배포하고 사람에게 보여준다"),
]

_TASKS = [
    ("환경 세팅과 저장소 초기화", 60),
    ("데이터 모델 설계", 90),
    ("저장 계층 붙이기", 90),
    ("핵심 로직 첫 버전", 120),
    ("입력 화면 만들기", 90),
    ("목록 화면 만들기", 90),
    ("상태 변경 흐름 연결", 90),
    ("에러 처리와 검증", 60),
    ("테스트 작성", 90),
    ("배포 파이프라인", 90),
]

_NODES = [
    ("ui", "화면", "client", "frontend"),
    ("api", "API 서버", "service", "backend"),
    ("core", "핵심 로직", "service", "backend"),
    ("worker", "백그라운드 작업", "service", "backend"),
    ("db", "데이터베이스", "store", "data"),
    ("cache", "캐시", "store", "data"),
    ("external", "외부 연동", "external", "infra"),
    ("deploy", "배포", "external", "infra"),
]

_EDGES = [
    ("ui", "api", "요청"),
    ("api", "core", "호출"),
    ("core", "db", "읽기/쓰기"),
    ("core", "cache", "캐싱"),
    ("worker", "db", "집계"),
    ("core", "external", "연동"),
    ("api", "deploy", "배포"),
]


def _int_from(text: str, pattern: str, fallback: int) -> int:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else fallback


class MockPlanner:
    """결정적 목업. 호출 횟수에 따라 결과가 달라진다 (재시도를 재현하려고)."""

    def __init__(self, *, always_valid: bool = False) -> None:
        self.always_valid = always_valid
        self.calls: list[str] = []

    async def structured(
        self, *, system: str, prompt: str, output_model: type[BaseModel]
    ) -> Any:
        name = output_model.__name__
        self.calls.append(name)
        handler = getattr(self, f"_{name}", None)
        if handler is None:
            raise AssertionError(f"목업이 모르는 출력 모델: {name}")
        return handler(prompt)

    # ── 생성 그래프 ───────────────────────────────────────────
    def _IntakeResult(self, prompt: str) -> IntakeResult:  # noqa: N802
        weeks = _int_from(prompt, r"(\d+)\s*주", 8)
        hours = _int_from(prompt, r"주당?\s*(\d+)\s*시간", 10)
        goal = prompt.split("목표:", 1)[-1].strip().splitlines()[0][:20] or "새 프로젝트"
        # 목업이라 판정할 수 없다. 낱말 몇 개로만 가른다 — 실제 판정은 LLM 이 한다.
        made = ("게임", "앱", "서비스", "웹", "봇", "도구", "사이트", "api")
        learned = ("배우", "공부", "자격", "시험", "점수", "합격", "익히")
        text = prompt.lower()
        domain = (
            "general"
            if any(w in text for w in learned) or not any(w in text for w in made)
            else "software"
        )
        return IntakeResult(
            title=goal,
            constraints=Constraints(
                duration_weeks=max(1, min(weeks, 52)),
                hours_per_week=max(1, min(hours, 60)),
                level="intermediate",
                stack=[],
                team_size=1,
            ),
            missing=[],
            domain=domain,
        )

    def _ClarifyResult(self, prompt: str) -> ClarifyResult:  # noqa: N802
        """2라운드 후속 질문 (1라운드는 LLM 을 부르지 않는다 — graphs/interview.py).

        목업이라 답을 읽고 판단할 수는 없다. 대신 **답의 길이**로 정한다:
        전부 한두 줄로 넘겼으면 한 번 더 묻고, 아니면 통과시킨다.
        키 없이 돌려도 「되묻는 인터뷰」가 화면에 보여야 하기 때문이다.
        """
        answers = re.findall(r"^A\. (.*)$", prompt, flags=re.MULTILINE)
        written = sum(len(a) for a in answers if a != "(답을 건너뛰었다)")
        if written >= 80:
            return ClarifyResult(questions=[])
        return ClarifyResult(
            questions=[
                ClarifyQuestion(
                    field="scope",
                    question=(
                        "적어주신 것만으로는 범위가 아직 넓습니다. "
                        "이번 기간에 **반드시** 있어야 하는 것 하나만 고른다면 무엇인가요?"
                    ),
                )
            ]
        )

    def _BlueprintResult(self, prompt: str) -> BlueprintResult:  # noqa: N802
        """답변에서 문장을 끊어 완성 기준으로 만든다. 지어내지 않는다."""
        answers = [
            a
            for a in re.findall(r"^A\. (.*)$", prompt, flags=re.MULTILINE)
            if a and a != "(답을 건너뛰었다)"
        ]
        sentences: list[str] = []
        for a in answers:
            sentences += [s.strip() for s in re.split(r"[.。\n]|,\s", a) if len(s.strip()) >= 6]
        picked = sentences[:3] or ["사용자가 말한 결과물이 돌아간다"]
        return BlueprintResult(
            summary=answers[0][:60] if answers else "",
            criteria=[
                SuccessCriterion(key=f"sc{i}", text=t) for i, t in enumerate(picked, start=1)
            ],
        )

    def _DecomposeResult(self, prompt: str) -> DecomposeResult:  # noqa: N802
        weeks = _int_from(prompt, r"기간 (\d+)주", 8)
        capacity = _int_from(prompt, r"주당 (\d+)분", 600)
        # 첫 호출은 일부러 120분을 넘겨 낸다 — critic 재시도가 데모에서 보여야 한다.
        first_try = self.calls.count("DecomposeResult") == 1 and not self.always_valid

        # 완성 기준은 주에 골고루 나눠 맡긴다 (critic 의 커버리지 검증을 통과해야 한다).
        criteria = re.findall(r"^- (sc\d+): ", prompt, flags=re.MULTILINE)
        goals, tasks, tickets = [], [], []
        weeks_per_phase = max(1, math.ceil(weeks / len(_PHASES)))
        week = 1
        ticket_no = 0
        task_no = 0

        for _i, (phase, desc) in enumerate(_PHASES, start=1):
            if week > weeks:
                break
            for _ in range(weeks_per_phase):
                if week > weeks:
                    break
                goal_key = f"w{week}"
                goals.append(
                    DraftWeeklyGoal(
                        key=goal_key,
                        week_index=week,
                        title=f"{week}주 - {phase}",
                        covers=[],
                    )
                )
                # 주마다 태스크 하나. 번호는 프로젝트 전체에서 이어 센다.
                task_no += 1
                task_key = f"k{task_no}"
                tasks.append(
                    DraftTask(
                        key=task_key,
                        weekly_goal_key=goal_key,
                        task_number=task_no,
                        title=f"{phase} ({week}주)",
                        description=desc,
                    )
                )
                used = 0
                number = 0
                while used < capacity * 0.7:
                    title, minutes = _TASKS[ticket_no % len(_TASKS)]
                    if first_try and ticket_no % 3 == 0:
                        minutes = 180  # R1 위반 — critic 이 잡아야 한다
                    if used + minutes > capacity:
                        break
                    ticket_no += 1
                    number += 1  # 태스크마다 1 부터 다시 센다
                    tickets.append(
                        DraftTicket(
                            key=f"t{ticket_no}",
                            task_key=task_key,
                            ticket_number=number,
                            title=f"{title} ({week}주)",
                            body=(
                                f"## 무엇을\n{title}\n\n"
                                "## 완료 조건\n- [ ] 테스트 통과\n- [ ] 리뷰 반영\n\n"
                                "## 참고\n- (목업 데이터)\n"
                            ),
                            est_minutes=minutes,
                            depends_on=[f"t{ticket_no - 1}"] if ticket_no > 1 else [],
                        )
                    )
                    used += minutes
                week += 1

        # 남는 기준이 없도록 라운드로빈으로 배분한다.
        for i, key in enumerate(criteria):
            goals[i % len(goals)].covers.append(key)
        return DecomposeResult(weekly_goals=goals, tasks=tasks, tickets=tickets)

    def _ArchitectResult(self, prompt: str) -> ArchitectResult:  # noqa: N802
        # 프롬프트가 허용한 유형·레이어만 쓴다 (도메인 프리셋, SPEC §1.5).
        types = re.findall(r"^  \* (\w+): ", prompt, flags=re.MULTILINE)
        node_types = types[:4] or ["service", "store", "client", "external"]
        layers = types[4:8] or ["frontend", "backend", "data", "infra"]
        return ArchitectResult(
            nodes=[
                DraftNode(
                    node_key=k,
                    label=lab,
                    node_type=node_types[i % len(node_types)],
                    layer=layers[i % len(layers)],
                )
                for i, (k, lab, _nt, _lay) in enumerate(_NODES)
            ],
            edges=[DraftEdge(from_key=f, to_key=t, label=lab) for f, t, lab in _EDGES],
        )

    def _LinkResult(self, prompt: str) -> LinkResult:  # noqa: N802
        ticket_keys = re.findall(r"^- (t\d+):", prompt, flags=re.MULTILINE)
        node_keys = re.findall(r"^- (\w+) \(", prompt, flags=re.MULTILINE)
        node_keys = [k for k in node_keys if k not in ticket_keys] or [n[0] for n in _NODES]
        # 모든 노드가 최소 하나는 받도록 라운드로빈으로 붙인다 (critic 의 고아 노드 방지).
        return LinkResult(
            links=[
                DraftLink(ticket_key=t, node_key=node_keys[i % len(node_keys)])
                for i, t in enumerate(ticket_keys)
            ]
        )

    # ── 재설계 그래프 ─────────────────────────────────────────
    def _DiagnoseResult(self, prompt: str) -> DiagnoseResult:  # noqa: N802
        """숫자를 보고 진단을 고른다. 목업이지만 근거는 프롬프트 안의 실제 숫자다."""
        has_reason = "- (없음)" not in prompt
        deferred = _int_from(prompt, r"미룬 것 (\d+)회", 0)
        missed = _int_from(prompt, r"마감 놓침 (\d+)회", 0)
        delayed = _int_from(prompt, r"(\d+)개 지연", 0)

        if has_reason:
            diagnosis, why = "지식부족", "막힘 사유가 방법을 몰라 멈춘 쪽을 가리킨다"
        elif deferred >= missed and deferred >= 2:
            diagnosis, why = "범위과다", "마감을 놓치기보다 스스로 미룬 횟수가 많다"
        elif missed >= 2:
            diagnosis, why = "의존성누락", "손도 못 대고 마감만 지나간 티켓이 반복된다"
        else:
            diagnosis, why = "외부요인", "지연이 특정 구간에 몰려 있지 않다"

        return DiagnoseResult(
            diagnosis=diagnosis,  # type: ignore[arg-type]
            rationale=f"지연 {delayed}건, 놓침 {missed}회, 미룸 {deferred}회. {why}.",
        )

    def _ReplanProposal(self, prompt: str) -> ReplanProposal:  # noqa: N802
        diagnosis = (re.search(r"진단: (\S+)", prompt) or [None, "범위과다"])[1]
        rows = re.findall(
            r"^(T\d+) \[(\d+)주차\] (.+?) \((\d+)분, (\w+)\)", prompt, flags=re.MULTILINE
        )
        open_rows = [r for r in rows if r[4] != "done"]
        if not open_rows:
            return ReplanProposal(changes=[])

        changes: list[ProposedChange] = []

        def blank(**kw) -> dict:
            base = dict(
                type="add_ticket", target_ref="", depends_on_ref="", reason="",
                title="", body="", est_minutes=0, parts=[], shift_days=0,
            )
            base.update(kw)
            return base

        if diagnosis == "지식부족":
            ref, _week, title, _min, _status = open_rows[0]
            changes.append(ProposedChange(**blank(
                type="add_ticket", target_ref=ref,
                title=f"{title} 전에 필요한 개념 정리",
                body=(
                    "## 무엇을\n막힌 구간에서 쓰이는 개념을 30분 안에 훑는다\n\n"
                    "## 완료 조건\n- [ ] 핵심 개념 3개를 한 줄로 설명할 수 있다\n"
                    "- [ ] 최소 예제 하나를 돌려봤다\n"
                ),
                est_minutes=60,
                reason="막힘 사유가 방법을 모르는 쪽을 가리킨다",
            )))
            if len(open_rows) > 1:
                ref2, _w, title2, minutes2, _s = open_rows[1]
                changes.append(ProposedChange(**blank(
                    type="add_dependency", target_ref=ref2, depends_on_ref=ref,
                    reason=f"「{title}」이 먼저 끝나야 {title2}에 손댈 수 있다",
                )))

        elif diagnosis == "범위과다":
            for ref, _week, title, minutes, _status in open_rows[:2]:
                total = int(minutes)
                parts = 2 if total <= 120 else math.ceil(total / 90)
                each = max(15, total // parts)
                changes.append(ProposedChange(**blank(
                    type="split_ticket", target_ref=ref,
                    parts=[
                        SplitPart(title=f"{title} ({i + 1}/{parts})", est_minutes=each)
                        for i in range(parts)
                    ],
                    reason=f"{total}분짜리를 한 번에 붙잡고 있어 어디서 막혔는지 특정이 안 된다",
                )))
            if len(open_rows) > 2:
                ref, _w, title, _m, _s = open_rows[-1]
                changes.append(ProposedChange(**blank(
                    type="drop_ticket", target_ref=ref,
                    reason="이번 주에 꼭 필요하지 않다. 뒤로 미룬다",
                )))

        elif diagnosis == "의존성누락":
            ref, _week, title, _min, _status = open_rows[0]
            changes.append(ProposedChange(**blank(
                type="add_ticket", target_ref=ref,
                title=f"{title}에 필요한 선행 작업",
                body=(
                    "## 무엇을\n먼저 끝나야 하는 것을 분리한다\n\n"
                    "## 완료 조건\n- [ ] 후속 티켓이 바로 시작 가능\n"
                ),
                est_minutes=90,
                reason="선행 조건이 티켓으로 잡혀 있지 않아 매번 막힌다",
            )))
            if len(open_rows) > 1:
                changes.append(ProposedChange(**blank(
                    type="add_dependency",
                    target_ref=open_rows[1][0], depends_on_ref=ref,
                    reason="순서를 명시해 두면 같은 지점에서 다시 막히지 않는다",
                )))

        else:  # 외부요인 — 일정만 이월, 내용 유지
            changes.append(ProposedChange(**blank(
                type="shift_week", shift_days=7,
                reason="계획 문제가 아니다. 내용은 그대로 두고 일정만 민다",
            )))

        return ReplanProposal(changes=changes)
