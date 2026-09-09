-- 0006: 완성 청사진 (SPEC §3.3)
--
-- 인터뷰에서 「무엇이 되면 끝났다고 할 수 있나요」를 물었다(0005). 그 답을 검증
-- 가능한 항목으로 끊어 여기 둔다. 그리고 **주마다 어떤 항목을 향해 가는지**를
-- 적게 한다. 그래야 critic 이 물어볼 수 있다 — "이 기준은 어느 주가 맡는가?"
--
-- 이 검증에 LLM 은 개입하지 않는다 (R2). 기준 키와 주의 covers 를 맞춰보는
-- 집합 연산이다. 청사진을 세우는 것은 AI 가, 계획이 그 청사진을 덮는지 확인하는
-- 것은 코드가 한다.
alter table projects
  add column if not exists blueprint jsonb not null default '{}'::jsonb;
  -- {"summary": "...", "criteria": [{"key": "sc1", "text": "..."}]}

alter table weekly_goals
  add column if not exists covers jsonb not null default '[]'::jsonb;
  -- 이 주가 맡는 성공 기준 키 목록. 예: ["sc1", "sc3"]
