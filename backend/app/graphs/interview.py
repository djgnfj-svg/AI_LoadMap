"""인터뷰 — 계획을 짜기 전에 사람에게 묻는 단계 (SPEC §3.3).

1라운드 질문은 LLM 이 만들지 않는다. 무엇을 먼저 물어야 하는지는 프로젝트마다
다르지 않고, 첫 질문이 이 제품의 첫인상이기 때문이다. API 키가 없어도(목업 Planner)
같은 질문이 같은 순서로 뜬다.

2라운드부터가 LLM 이다 — 1라운드 답을 읽고 아직 모르는 것만 되묻는다.

답변에서 숫자는 뽑아 제약에 반영하고, **원문은 그대로 남긴다.** 원문이 decompose
프롬프트로 들어간다(`prompts.format_interview`). 숫자만 뽑고 문장을 버리면
사용자가 무슨 말을 해도 계획이 달라지지 않는다.
"""

import math
import re
from datetime import date

from app.models.schemas import ClarifyQuestion, Constraints, InterviewTurn

# 한 라운드에 묻는 질문 수 상한 (SPEC §3.3)
MAX_QUESTIONS_PER_ROUND = 5
# 인터뷰 라운드 상한. 1라운드는 고정 질문, 2라운드는 LLM 후속 질문.
# 더 늘리면 계획을 만들기도 전에 사람이 지친다.
MAX_ROUNDS = 2

# 1라운드 고정 질문. 순서가 중요하다 — 청사진이 먼저다.
# 「목표가 뭐예요」가 아니라 「끝났을 때 무엇이 있나요」로 묻는다. 앞의 질문에는
# 하고 싶은 것을 적고, 뒤의 질문에는 만들 것을 적기 때문이다.
FIXED_QUESTIONS: list[tuple[str, str]] = [
    (
        "blueprint",
        "당신의 목표의 정확한 청사진은 무엇인가요? "
        "다 만들어졌을 때 화면에 무엇이 있고, 그것으로 무엇을 할 수 있는지 적어주세요.",
    ),
    (
        "done_when",
        "무엇이 되면 「끝났다」고 할 수 있나요? "
        "눈으로 확인할 수 있는 것으로 두세 개 적어주세요.",
    ),
    (
        "starting_point",
        "지금 어디까지 돼 있나요? 이미 있는 것 · 해본 것 · 자신 없는 것을 적어주세요.",
    ),
    (
        "deadline",
        "언제까지 이루고 싶나요? 날짜나 기간으로 적어주세요.",
    ),
]

# intake 가 추측으로 채운 것 중, 답이 없으면 계획 자체가 어긋나는 필드.
# 나머지 추측 필드(level, stack, team_size)는 2라운드에서 LLM 이 필요하면 묻는다.
_CRITICAL_FIELDS: dict[str, str] = {
    "hours_per_week": "여기에 주당 몇 시간 정도 쓸 수 있나요? (지금은 {value}시간으로 잡아뒀어요)",
}


def first_round(missing: list[str], constraints: Constraints) -> list[ClarifyQuestion]:
    """1라운드 질문. 고정 질문 + 답이 없으면 계획이 어긋나는 추측 필드."""
    questions = [ClarifyQuestion(field=f, question=q) for f, q in FIXED_QUESTIONS]
    values = constraints.model_dump()
    for field, template in _CRITICAL_FIELDS.items():
        if field in missing:
            questions.append(
                ClarifyQuestion(field=field, question=template.format(value=values.get(field)))
            )
    return questions[:MAX_QUESTIONS_PER_ROUND]


def pending(turns: list[InterviewTurn]) -> list[ClarifyQuestion]:
    """아직 답을 못 받은 질문. 새로고침 뒤 인터뷰를 이어서 그릴 때 쓴다."""
    return [
        ClarifyQuestion(field=t.field, question=t.question) for t in turns if not t.answer.strip()
    ]


def current_round(turns: list[InterviewTurn]) -> int:
    """지금까지 진행한 라운드 수. 아무것도 안 물었으면 0."""
    return max((t.round for t in turns), default=0)


def record_answers(turns: list[InterviewTurn], answers: dict[str, str]) -> list[InterviewTurn]:
    """받은 답을 해당 질문에 채운다. 빈 답은 「건너뜀」이고, 그것도 사실이라 남긴다."""
    filled = [t.model_copy() for t in turns]
    for turn in filled:
        if turn.field in answers and not turn.answer.strip():
            turn.answer = (answers[turn.field] or "").strip()
    return filled


def answered_current_round(turns: list[InterviewTurn], answers: dict[str, str]) -> bool:
    """이번 라운드 질문 중 하나라도 답이 들어왔는가.

    빈 문자열로 온 답도 「건너뛰겠다」는 답이다. 값이 아니라 키가 왔는지로 센다.
    값으로 세면 전부 건너뛴 사용자가 같은 질문을 영원히 다시 받는다.
    """
    round_no = current_round(turns)
    return any(t.field in answers for t in turns if t.round == round_no)


def apply_answers(
    constraints: Constraints, answers: dict[str, str], today: date | None = None
) -> Constraints:
    """답변에서 제약을 읽어낸다. 숫자로 안 읽히는 답은 무시하고 추론값을 유지한다.

    ⚠ 여기서 못 읽은 문장은 버려지는 게 아니라 `interview` 에 원문으로 남아
    decompose 프롬프트로 들어간다.
    """
    if not answers:
        return constraints
    data = constraints.model_dump()

    for field in ("duration_weeks", "hours_per_week", "team_size"):
        digits = "".join(ch for ch in str(answers.get(field, "")) if ch.isdigit())
        if digits:
            data[field] = int(digits)

    if answers.get("level") in ("beginner", "intermediate", "advanced"):
        data["level"] = answers["level"]
    if answers.get("stack"):
        data["stack"] = [s.strip() for s in str(answers["stack"]).split(",") if s.strip()]

    # 「언제까지」는 사람 말로 온다 — "3개월", "12주", "2026-12-01".
    weeks = weeks_from(answers.get("deadline", ""), today)
    if weeks:
        data["duration_weeks"] = weeks

    # Constraints 의 범위를 벗어나는 답은 그대로 넣으면 터진다. 잘라서 넣는다.
    data["duration_weeks"] = max(1, min(int(data["duration_weeks"]), 104))
    data["hours_per_week"] = max(1, min(int(data["hours_per_week"]), 80))
    data["team_size"] = max(1, int(data["team_size"]))
    return Constraints(**data)


def weeks_from(text: str, today: date | None = None) -> int | None:
    """「언제까지」 답에서 주 수를 읽는다. 못 읽으면 None."""
    text = (text or "").strip()
    if not text:
        return None

    iso = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", text)
    if iso:
        try:
            target = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            target = None
        if target:
            days = (target - (today or date.today())).days
            return max(1, math.ceil(days / 7)) if days > 0 else None

    if (m := re.search(r"(\d+)\s*년", text)):
        return int(m.group(1)) * 52
    if (m := re.search(r"(\d+)\s*(?:개?월|달)", text)):
        return max(1, round(int(m.group(1)) * 4.35))
    if (m := re.search(r"(\d+)\s*주", text)):
        return int(m.group(1))
    if (m := re.search(r"(\d+)\s*일", text)):
        return max(1, math.ceil(int(m.group(1)) / 7))
    return None
