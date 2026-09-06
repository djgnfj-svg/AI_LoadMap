-- 알람 (SPEC §2.3, §3.5 GET /projects/{id}/alerts)
--
-- §4.1 테이블 목록에는 없지만 §3.5 의 알람 API 와 §3.6 의 "알람 큐"가 이 테이블을 전제한다.
-- events 로 대신할 수 없는 이유: 알람은 "확인했는가"라는 상태를 갖고, events 는 상태를 갖지 않는다 (R4).
--
-- 알람 문구는 전부 SQL 집계 결과로 채운 템플릿이다. LLM 이 만들지 않는다 (R2).
-- 톤은 R5 — 책망이 아니라 진단.

create table alerts (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  ticket_id     uuid references tickets(id) on delete cascade,
  node_id       uuid references arch_nodes(id) on delete cascade,
  review_day_id uuid references review_days(id) on delete cascade,
  rule          text not null
                check (rule in (
                  'due_24h',         -- 마감 24시간 경과 -> "어디서 막혔나요?"
                  'deferred_twice',  -- 동일 티켓 2회 연기 -> 재분할 제안
                  'node_at_risk',    -- 동일 노드 지연 2건 이상 -> 재점검일
                  'weekly_low',      -- 주간 완료율 50% 미만
                  'inactive_3d'      -- 3일 연속 무활동 (질문이지 알람이 아니다)
                )),
  severity      text not null check (severity in ('low', 'medium', 'high')),
  message       text not null,
  -- 스케줄러가 매일 돌아도 같은 알람이 쌓이지 않게 하는 키.
  dedupe_key    text not null,
  acknowledged  boolean not null default false,
  created_at    timestamptz not null default now()
);

-- 확인하지 않은 같은 알람은 하나만 존재한다. 확인한 뒤 다시 발생하면 새로 생긴다.
create unique index alerts_open_dedupe_idx
  on alerts (project_id, dedupe_key)
  where acknowledged = false;

create index alerts_project_open_idx
  on alerts (project_id, acknowledged, created_at desc);

-- 재점검일을 미룬 기록도 남긴다 (§2.4 — "미루면 미룬 사실도 이벤트로 기록된다").
alter table review_days add column postponed_count int not null default 0;
