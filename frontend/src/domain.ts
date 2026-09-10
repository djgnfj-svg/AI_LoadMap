/** 도메인 프리셋의 화면 낱말 (SPEC §1.5).
 *
 * 서버(backend/app/graphs/domains.py)와 같은 목록이다. 갈리는 것은 낱말뿐이다 —
 * 게임 로드맵에 「컴포넌트」라고 쓰면 읽히지 않는다.
 *
 * **새 로드맵은 전부 game 이다** (SPEC §1.5). software·web 은 그 전에 만든 로드맵이
 * 제 낱말로 읽히게 남겨 둔 것뿐이라, 고르는 화면은 없다.
 */
export type Domain = "game" | "software" | "web";

interface Words {
  label: string;
  /** 목표 한 줄을 받을 때 묻는 말 */
  ask: string;
  askPlaceholder: string;
  /** 청사진 질문의 빈 칸에 미리 적힌 예시. 한 줄짜리 목표와 달리 **자세히** 적는 자리다 */
  blueprintPlaceholder: string;
  /** 「무엇무엇이 들어가나요」의 예시. 여기 적은 것이 그대로 구조도 노드가 된다 */
  partsPlaceholder: string;
  /** 오른쪽 그림의 이름 */
  map: string;
  /** 노드 하나를 부르는 말 */
  node: string;
  /** 제약 입력의 stack 라벨 */
  stack: string;
  stackPlaceholder: string;
}

const WORDS: Record<Domain, Words> = {
  game: {
    label: "게임 제작",
    ask: "어떤 게임을 만드시나요?",
    askPlaceholder: "예: 친구 4명이 한 방에서 30분짜리 미션을 도는 코옵 게임",
    blueprintPlaceholder:
      "예: 친구 4명이 방에 들어와 무기를 고르고, 30분 동안 몰려오는 적을 막는다. " +
      "보스를 잡으면 이기고, 넷이 다 쓰러지면 진다. 스테이지 3개, 무기 6종, 보스 1마리.",
    partsPlaceholder: "예: 넷코드, 전투, 인벤토리, 보스 스테이지, 사운드, 스팀 빌드",
    map: "게임 구조도",
    node: "시스템",
    stack: "엔진 · 도구 (쉼표로 구분)",
    stackPlaceholder: "unity, c#",
  },
  software: {
    label: "소프트웨어",
    ask: "무엇을 하는 프로그램인가요?",
    askPlaceholder: "예: 회의 녹음을 넣으면 회의록을 뽑아 주는 데스크톱 앱",
    blueprintPlaceholder:
      "예: 녹음 파일을 끌어다 놓으면 화자별로 나뉜 회의록이 나오고, " +
      "요약과 할 일을 뽑아 마크다운으로 내보낸다. 화면 3개, 오프라인 동작.",
    partsPlaceholder: "예: 녹음 불러오기, 화자 분리, 요약, 내보내기, 설정 화면",
    map: "아키텍처",
    node: "컴포넌트",
    stack: "스택 (쉼표로 구분)",
    stackPlaceholder: "python, electron",
  },
  web: {
    label: "웹 제작",
    ask: "어떤 서비스를 만드시나요?",
    askPlaceholder: "예: 동네 사람끼리 공구를 빌려 쓰는 사이트",
    blueprintPlaceholder:
      "예: 로그인한 사람이 가진 공구를 올리고, 지도에서 근처 것을 찾아 빌린다. " +
      "빌린 뒤 후기를 남긴다. 화면 5개, 결제는 없다.",
    partsPlaceholder: "예: 로그인, 공구 등록, 지도 검색, 예약, 후기",
    map: "서비스 구조도",
    node: "구성 요소",
    stack: "스택 (쉼표로 구분)",
    stackPlaceholder: "react, fastapi",
  },
};

export function words(domain: string | null | undefined): Words {
  return WORDS[(domain as Domain) in WORDS ? (domain as Domain) : "software"];
}
