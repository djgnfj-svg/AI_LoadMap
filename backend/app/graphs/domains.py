"""도메인 프리셋 (SPEC §1.5).

이 도구의 구조는 도메인과 무관하다 — 주 > 태스크 > 티켓, 티켓이 노드를 채우고,
지연이 쌓이면 재점검일이 잡힌다. 도메인마다 다른 것은 **낱말**뿐이다.

  소프트웨어: 아키텍처 / 컴포넌트 / frontend·backend·data·infra
  일반:       구성요소 지도 / 구성요소 / 결과물·실행·재료·환경

그래서 도메인을 프롬프트에 끼우는 값 묶음 하나로 두고, 그래프·critic·감지는
건드리지 않는다. 도메인이 늘어도 이 파일만 는다.
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
)

GENERAL = DomainPreset(
    key="general",
    label="일반",
    map_word="구성요소 지도",
    node_word="구성요소",
    node_types=[
        ("deliverable", "남는 것 (영상, 원고, 포트폴리오, 점수)"),
        ("skill", "몸에 붙는 것 (역량, 습관, 자격)"),
        ("resource", "모으거나 준비하는 것 (교재, 장비, 자료, 자금)"),
        ("external", "내가 못 정하는 것 (시험 일정, 심사, 거래처)"),
    ],
    layers=[
        ("output", "최종 결과물"),
        ("practice", "반복해서 하는 실행"),
        ("input", "배우고 모으는 재료"),
        ("support", "환경 · 도구 · 사람"),
    ],
    node_key_examples="'listening', 'thumbnail', 'mock_exam'",
    ticket_hint=(
        "티켓 본문은 그 일을 처음 하는 사람이 그대로 따라 할 수 있어야 한다. "
        "코드 이야기를 넣지 마라."
    ),
    criteria_examples='"모의고사 1회분 채점 완료", "영상 1편 업로드", "원고 3쪽 작성"',
    architect_hint=(
        "이 목표를 이루는 구성요소와 그 사이의 흐름을 그린다. "
        "무엇이 무엇의 재료가 되는지가 화살표다."
    ),
    stack_word="쓰는 도구 · 재료",
)

PRESETS: dict[str, DomainPreset] = {p.key: p for p in (SOFTWARE, GENERAL)}


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
