/** 도메인 프리셋의 화면 낱말 (SPEC §1.5).
 *
 * 서버(backend/app/graphs/domains.py)와 같은 목록이다. 구조는 도메인과 무관하고
 * 낱말만 갈린다 — 토익 900점짜리 로드맵에 「컴포넌트」라고 쓰면 안 읽힌다.
 */
export type Domain = "software" | "general";

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
    label: "소프트웨어 만들기",
    map: "아키텍처",
    node: "컴포넌트",
    stack: "스택 (쉼표로 구분)",
    stackPlaceholder: "unity, c#",
  },
  general: {
    label: "그 밖 (학습 · 콘텐츠 · 사업 …)",
    map: "구성요소 지도",
    node: "구성요소",
    stack: "쓰는 도구 · 재료 (쉼표로 구분)",
    stackPlaceholder: "해커스 교재, 프리미어",
  },
};

export function words(domain: string | null | undefined): Words {
  return WORDS[(domain as Domain) in WORDS ? (domain as Domain) : "software"];
}

export const DOMAINS: Domain[] = ["software", "general"];
