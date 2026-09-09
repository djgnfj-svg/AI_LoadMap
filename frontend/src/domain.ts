/** 도메인 프리셋의 화면 낱말 (SPEC §1.5).
 *
 * 서버(backend/app/graphs/domains.py)와 같은 목록이다. 축은 **무엇을 만드는가**이고,
 * 구조는 도메인과 무관하다. 갈리는 것은 낱말뿐이다 — 게임 로드맵에 「컴포넌트」,
 * 다큐 로드맵에 「프런트엔드」라고 쓰면 읽히지 않는다.
 */
export type Domain = "software" | "game" | "general";

interface Words {
  label: string;
  /** 오른쪽 그림의 이름 */
  map: string;
  /** 노드 하나를 부르는 말 */
  node: string;
  /** 제약 입력의 stack 라벨 */
  stack: string;
  stackPlaceholder: string;
}

const WORDS: Record<Domain, Words> = {
  software: {
    label: "앱 · 웹서비스 · 도구",
    map: "아키텍처",
    node: "컴포넌트",
    stack: "스택 (쉼표로 구분)",
    stackPlaceholder: "unity, c#",
  },
  game: {
    label: "게임 제작",
    map: "게임 구조도",
    node: "시스템",
    stack: "엔진 · 도구 (쉼표로 구분)",
    stackPlaceholder: "unity, c#",
  },
  general: {
    label: "그 밖의 만들기 (영상 · 글 · 제품 …)",
    map: "구성요소 지도",
    node: "구성요소",
    stack: "쓰는 도구 · 재료 (쉼표로 구분)",
    stackPlaceholder: "프리미어, 카메라",
  },
};

export function words(domain: string | null | undefined): Words {
  return WORDS[(domain as Domain) in WORDS ? (domain as Domain) : "software"];
}

export const DOMAINS: Domain[] = ["software", "game", "general"];
