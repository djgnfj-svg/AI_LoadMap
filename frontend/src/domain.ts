/** 도메인 프리셋의 화면 낱말 (SPEC §1.5).
 *
 * 서버(backend/app/graphs/domains.py)와 같은 목록이다. 축은 **무엇을 만드는가**이고,
 * 구조는 도메인과 무관하다. 갈리는 것은 낱말뿐이다 — 게임 로드맵에 「컴포넌트」,
 * 다큐 로드맵에 「프런트엔드」라고 쓰면 읽히지 않는다.
 */
export type Domain = "game" | "software" | "web";

interface Words {
  label: string;
  /** 첫 화면에서 고를 때 곁들이는 한 줄 */
  pick: string;
  /** 목표 한 줄을 받을 때 묻는 말 */
  ask: string;
  askPlaceholder: string;
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
    pick: "플레이할 수 있는 것",
    ask: "어떤 게임을 만드시나요?",
    askPlaceholder: "예: 친구 4명이 한 방에서 30분짜리 미션을 도는 코옵 게임",
    map: "게임 구조도",
    node: "시스템",
    stack: "엔진 · 도구 (쉼표로 구분)",
    stackPlaceholder: "unity, c#",
  },
  software: {
    label: "소프트웨어",
    pick: "앱 · 도구 · 봇처럼 실행하는 것",
    ask: "무엇을 하는 프로그램인가요?",
    askPlaceholder: "예: 회의 녹음을 넣으면 회의록을 뽑아 주는 데스크톱 앱",
    map: "아키텍처",
    node: "컴포넌트",
    stack: "스택 (쉼표로 구분)",
    stackPlaceholder: "python, electron",
  },
  web: {
    label: "웹 제작",
    pick: "브라우저로 여는 것",
    ask: "어떤 서비스를 만드시나요?",
    askPlaceholder: "예: 동네 사람끼리 공구를 빌려 쓰는 사이트",
    map: "서비스 구조도",
    node: "구성 요소",
    stack: "스택 (쉼표로 구분)",
    stackPlaceholder: "react, fastapi",
  },
};

export function words(domain: string | null | undefined): Words {
  return WORDS[(domain as Domain) in WORDS ? (domain as Domain) : "software"];
}

export const DOMAINS: Domain[] = ["game", "software", "web"];
