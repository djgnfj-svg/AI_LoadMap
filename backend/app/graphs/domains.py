"""도메인 프리셋 (SPEC §1.5).

축은 **무엇을 만드는가**다. 이 도구는 만들어지는 것이 있어야 성립한다 —
티켓을 끝내면 그림의 한 칸이 차오르는 게 전부이기 때문이다. 점수나 습관에는
채울 칸이 없다.

  게임:       게임 구조도 / 시스템 · 콘텐츠 / play·rule·content·build
  소프트웨어: 아키텍처 / 컴포넌트 / frontend·backend·data·infra
  웹:         서비스 구조도 / 구성 요소 / frontend·backend·data·infra

구조는 도메인과 무관하다 — 주 > 태스크 > 티켓, 티켓이 노드를 채우고, 지연이
쌓이면 재점검일이 잡힌다. 다른 것은 낱말뿐이라 프롬프트에 끼우는 값 묶음 하나로
두고, 그래프·critic·감지는 건드리지 않는다. 도메인이 늘어도 이 파일만 는다.
"""

from dataclasses import dataclass

from app.models.schemas import Domain


@dataclass(frozen=True)
class DomainPreset:
    key: Domain
    label: str
    #  「무엇을 그리는가」 — 화면과 프롬프트에서 부르는 이름
    map_word: str
    node_word: str
    node_types: list[tuple[str, str]]
    layers: list[tuple[str, str]]
    node_key_examples: str
    # 티켓 본문을 누가 어떻게 소비하는가
    ticket_hint: str
    # 완료 조건 예시. critic 의 판정 기준이 아니라 LLM 에게 보이는 본보기다.
    criteria_examples: str
    # 무엇을 노드로 그릴지
    architect_hint: str
    # 제약 표시 낱말
    stack_word: str
    # 1라운드 고정 질문 (SPEC §3.3). **field 는 도메인이 달라도 같다** —
    # apply_answers 가 field 로 제약을 읽고, 화면도 field 로 답을 맞춘다.
    # 갈리는 것은 묻는 말뿐이다.
    #
    # 순서도 도메인이 달라도 같다: **1번이 청사진**이고, 나머지는 전부
    # 자기 사정을 짚어 보게 하는 질문이다 (인원 · 실력 · 지금 위치 · 기간 · 주간 시간).
    # 이 다섯이 곧 Constraints 이고, 계획의 크기를 정하는 것은 목표가 아니라 이쪽이다.
    # 추론에 맡기지 않고 전부 묻는다 — 틀린 추론은 되돌릴 자리가 없다.
    questions: list[tuple[str, str]]


SOFTWARE = DomainPreset(
    key="software",
    label="소프트웨어",
    map_word="아키텍처",
    node_word="컴포넌트",
    node_types=[
        ("service", "직접 돌아가는 것 (API, 워커, 엔진)"),
        ("store", "저장하는 것 (DB, 캐시, 파일)"),
        ("client", "사람이 보는 것 (화면, 앱)"),
        ("external", "내가 만들지 않는 것 (외부 API, 결제사)"),
    ],
    layers=[
        ("frontend", "화면 쪽"),
        ("backend", "서버 쪽"),
        ("data", "데이터 쪽"),
        ("infra", "배포·운영 쪽"),
    ],
    node_key_examples="'auth', 'netcode', 'db'",
    ticket_hint="티켓 본문은 코딩 에이전트에 그대로 붙여넣을 수 있어야 한다.",
    criteria_examples='"테스트 3개 통과", "빌드 성공", "응답 200"',
    architect_hint="이 프로젝트가 만들 시스템의 컴포넌트와 호출 관계를 그린다.",
    stack_word="스택",
    questions=[
        ("blueprint", "당신이 만들고자 하는 것의 청사진이 무엇인가요?"),
        ("team_size", "몇 명이 만드나요?"),
        ("level", "이런 걸 만들어 본 적 있나요?"),
        ("starting_point", "지금 어디까지 돼 있나요?"),
        ("deadline", "언제까지 만드시나요?"),
        ("hours_per_week", "한 주에 몇 시간 쓸 수 있나요?"),
    ],
)

GAME = DomainPreset(
    key="game",
    label="게임 제작",
    map_word="게임 구조도",
    node_word="시스템",
    node_types=[
        ("system", "규칙이 도는 것 (전투, 인벤토리, 넷코드, 세이브)"),
        ("stage", "플레이할 것 (스테이지, 레벨, 퀘스트, 모드)"),
        ("asset", "만들어 넣을 것 (캐릭터, 배경, 사운드, 이펙트)"),
        ("external", "내가 만들지 않는 것 (스토어, 플랫폼 SDK, 외주)"),
    ],
    layers=[
        ("play", "플레이어가 직접 만지는 것 (조작, 카메라, UI)"),
        ("rule", "규칙과 로직 (전투 계산, 경제, AI, 동기화)"),
        ("content", "채워 넣는 것 (레벨, 캐릭터, 사운드)"),
        ("build", "내보내는 것 (빌드, 서버, 스토어 등록)"),
    ],
    node_key_examples="'netcode', 'inventory', 'boss_stage'",
    ticket_hint=(
        "코드 티켓은 코딩 에이전트에 그대로 붙여넣을 수 있어야 하고, "
        "에셋·레벨 티켓은 무엇을 몇 개 만들지 그대로 적는다."
    ),
    criteria_examples=(
        '"친구 4명이 한 방에서 30분을 끊김 없이 돈다", "빌드가 스팀에서 실행된다", '
        '"첫 스테이지를 5분 안에 깬다"'
    ),
    architect_hint=(
        "이 게임을 이루는 시스템과 콘텐츠, 그 사이의 의존을 그린다. "
        "무엇이 있어야 무엇을 플레이할 수 있는지가 화살표다."
    ),
    stack_word="엔진 · 도구",
    questions=[
        ("blueprint", "당신이 만들고자 하는 게임의 청사진이 무엇인가요?"),
        ("team_size", "몇 명이 만드나요?"),
        ("level", "게임을 만들어 본 적 있나요?"),
        ("starting_point", "지금 어디까지 돼 있나요?"),
        ("deadline", "언제까지 만드시나요?"),
        ("hours_per_week", "한 주에 몇 시간 쓸 수 있나요?"),
    ],
)

WEB = DomainPreset(
    key="web",
    label="웹 제작",
    map_word="서비스 구조도",
    node_word="구성 요소",
    node_types=[
        ("page", "사람이 보는 화면 (랜딩, 대시보드, 폼)"),
        ("api", "서버가 하는 일 (엔드포인트, 인증, 배치)"),
        ("store", "저장하는 것 (DB, 캐시, 파일)"),
        ("external", "내가 만들지 않는 것 (결제, 메일, 소셜 로그인)"),
    ],
    layers=[
        ("frontend", "브라우저에서 도는 것"),
        ("backend", "서버에서 도는 것"),
        ("data", "데이터 쪽"),
        ("infra", "배포 · 도메인 · 운영"),
    ],
    node_key_examples="'landing', 'auth', 'billing'",
    ticket_hint="티켓 본문은 코딩 에이전트에 그대로 붙여넣을 수 있어야 한다.",
    criteria_examples=(
        '"로그인해서 글을 쓰고 남에게 보인다", "배포한 주소로 열린다", "결제가 실제로 찍힌다"'
    ),
    architect_hint=(
        "이 서비스를 이루는 화면과 서버, 저장소를 그린다. "
        "사람이 무엇을 눌러 어디로 가는지가 화살표다."
    ),
    stack_word="스택",
    questions=[
        ("blueprint", "당신이 만들고자 하는 서비스의 청사진이 무엇인가요?"),
        ("team_size", "몇 명이 만드나요?"),
        ("level", "이런 걸 만들어 본 적 있나요?"),
        ("starting_point", "지금 어디까지 돼 있나요?"),
        ("deadline", "언제까지 여시나요?"),
        ("hours_per_week", "한 주에 몇 시간 쓸 수 있나요?"),
    ],
)

PRESETS: dict[str, DomainPreset] = {p.key: p for p in (GAME, SOFTWARE, WEB)}


def preset(domain: str | None) -> DomainPreset:
    """모르는 값이 와도 소프트웨어로 떨어뜨린다 — 기존 프로젝트가 전부 그것이다."""
    return PRESETS.get(domain or "", SOFTWARE)


def format_types(p: DomainPreset) -> str:
    return "\n".join(f"  * {k}: {desc}" for k, desc in p.node_types)


def format_layers(p: DomainPreset) -> str:
    return "\n".join(f"  * {k}: {desc}" for k, desc in p.layers)


def layer_order(p: DomainPreset) -> list[str]:
    """다이어그램 세로 순서. 위에서부터 이 순서로 줄을 세운다."""
    return [k for k, _ in p.layers]
