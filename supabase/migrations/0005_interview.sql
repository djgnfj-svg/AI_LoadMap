-- 0005: 인터뷰 (SPEC §3.3 개정)
--
-- 목표 한 줄로는 계획을 못 짠다. 로그인 뒤 첫 화면에서 청사진을 묻고,
-- 그 답을 **원문 그대로** 남긴다.
--
-- 전에는 clarify 답변에서 숫자 몇 개만 뽑아 제약에 넣고 나머지 문장은 버렸다.
-- 그래서 사용자가 무슨 말을 해도 계획이 달라지지 않았다. 여기 남은 원문이
-- decompose 프롬프트로 들어간다.
--
-- 형태: [{"round": 1, "field": "blueprint", "question": "...", "answer": "..."}]
--   answer 가 빈 문자열이면 아직 답을 못 받은 질문이다. 그 상태가 DB 에 있으므로
--   새로고침하거나 서버가 재시작해도 인터뷰를 이어서 할 수 있다.
--   (전에는 질문이 프로세스 메모리에만 있어서, 새로고침하면 그 프로젝트가
--    티켓 0개인 채로 영영 멈춰 있었다.)
alter table projects
  add column if not exists interview jsonb not null default '[]'::jsonb;
