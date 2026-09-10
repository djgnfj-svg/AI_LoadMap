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

from app.graphs import domains
from app.models.schemas import ClarifyQuestion, Constraints, InterviewTurn

# 한 라운드에 묻는 질문 수 상한 (SPEC §3.3).
# 5 였던 것을 6 으로 올렸다 — 다섯 칸이 한 화면에 쏟아지던 때의 숫자였고,
# 지금은 한 번에 하나씩 내민다. 1라운드 고정 질문(청사진 + 자기 사정 다섯)이 6개다.
MAX_QUESTIONS_PER_ROUND = 6
# 인터뷰 라운드 상한. 1라운드는 고정 질문, 2라운드는 LLM 후속 질문.
# 더 늘리면 계획을 만들기도 전에 사람이 지친다.
MAX_ROUNDS = 2

# 1라운드 질문은 **도메인이 쥔다** (graphs/domains.py 의 preset.questions).
#
# 1번은 청사진이다. 「목표가 뭐예요」가 아니라 「무엇을 만드나요」로 묻는다 —
# 앞의 질문에는 하고 싶은 것을 적고, 뒤의 질문에는 만들 것을 적기 때문이다.
#
# 2번부터는 전부 **자기 사정을 짚어 보게 하는 질문**이다: 인원 · 실력 · 지금 위치 ·
# 기간 · 주간 시간. 계획의 크기를 정하는 것은 목표가 아니라 이쪽이고, 사람은
# 대개 이걸 안 세어 보고 시작한다. 세어 보게 하는 것 자체가 이 단계의 값이다.
# 그래서 intake 가 추측했든 아니든 **전부 묻는다** — 틀린 추측은 되돌릴 자리가 없다.

# 건너뛸 수 없는 질문. 이 답이 없으면 계획이 **무엇을 향하는지** 정할 수 없고,
# 그 뒤의 완성 기준·주·티켓이 전부 남의 목표가 된다. 비워 보내면 다시 묻는다.
REQUIRED_FIELDS = frozenset({"blueprint"})

# 「실력」 답은 사람 말로 온다. 좁게만 읽는다 — 애매한 답을 억지로 분류하느니
# intake 의 추론값을 그대로 두는 게 낫다. 순서대로 먼저 걸리는 것이 이긴다.
_LEVEL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"처음|입문|초보|생초|해\s*본\s*적\s*(이|은)?\s*없|경험\s*(이|은)?\s*없"),
        "beginner",
    ),
    (
        re.compile(r"\d+\s*년|직업|실무|업무|전문|능숙|숙련|고급|상급|많이\s*(만들|해)"),
        "advanced",
    ),
    (
        re.compile(r"몇\s*(번|개)|조금|좀|취미|중급|해\s*봤|만들어\s*봤|해\s*본\s*적"),
        "intermediate",
    ),
]

# 「혼자」에는 숫자가 없다. 이 말이 team_size 답의 대부분이다.
_ALONE = re.compile(r"혼자|1인|나\s*뿐|저\s*뿐")


def first_round(domain: str | None = None) -> list[ClarifyQuestion]:
    """1라운드 질문. 도메인 프리셋이 통째로 쥔다 (청사진 + 자기 사정 다섯)."""
    preset = domains.preset(domain)
    return [
        ClarifyQuestion(field=f, question=q)
        for f, q in preset.questions[:MAX_QUESTIONS_PER_ROUND]
    ]


def pending(turns: list[InterviewTurn]) -> list[ClarifyQuestion]:
    """아직 답을 못 받은 질문. 새로고침 뒤 인터뷰를 이어서 그릴 때 쓴다."""
    return [
        ClarifyQuestion(field=t.field, question=t.question) for t in turns if not t.answered
    ]


def current_round(turns: list[InterviewTurn]) -> int:
    """지금까지 진행한 라운드 수. 아무것도 안 물었으면 0."""
    return max((t.round for t in turns), default=0)


def record_answers(turns: list[InterviewTurn], answers: dict[str, str]) -> list[InterviewTurn]:
    """받은 답을 채운다. 빈 답은 「건너뜀」이고, 그것도 답이라 answered 로 남긴다.

    ⚠ 예외는 REQUIRED_FIELDS 다. 청사진을 비워 보내면 답으로 치지 않고 다시 묻는다.

    답이 하나라도 온 라운드는 **통째로** 지나간 것으로 본다. 화면은 한 라운드를
    한 번에 제출하고, 비워 보낸 칸은 건너뛰겠다는 뜻이기 때문이다. 그렇게 하지
    않으면 전부 건너뛴 사용자가 같은 질문을 영원히 다시 받는다.
    """
    filled = [t.model_copy() for t in turns]
    touched = {t.round for t in filled if t.field in answers}
    for turn in filled:
        if turn.field in answers and not turn.answered:
            turn.answer = (answers[turn.field] or "").strip()
        if turn.round in touched:
            turn.answered = True
        # 청사진만은 「건너뜀」을 답으로 치지 않는다 (REQUIRED_FIELDS).
        if turn.field in REQUIRED_FIELDS and not turn.answer:
            turn.answered = False
    return filled


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

    # 첫 숫자만 읽는다. 자릿수를 이어 붙이면 "2~3명" 이 23명이 되고,
    # "주 10~15시간" 이 1015시간이 된다 — 물어보는 질문이 늘어난 만큼 실제로 온다.
    for field in ("duration_weeks", "hours_per_week", "team_size"):
        if m := re.search(r"\d+", str(answers.get(field, ""))):
            data[field] = int(m.group())

    if _ALONE.search(str(answers.get("team_size", ""))):
        data["team_size"] = 1

    level = str(answers.get("level", "")).strip()
    if level in ("beginner", "intermediate", "advanced"):
        data["level"] = level
    elif level:
        for pattern, value in _LEVEL_PATTERNS:
            if pattern.search(level):
                data["level"] = value
                break
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
