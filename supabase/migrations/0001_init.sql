-- Roadmap Planner — 초기 스키마
-- 기준: docs/SPEC.md §4. 이 파일과 SPEC이 어긋나면 이 파일이 기준이다.
--
-- SPEC §4.2 대비 추가된 것 (모두 R1~R6과 충돌 없음):
--   * projects.start_date  — weekly_goals.week_index 를 실제 날짜로 환산하는 기준점.
--                            §6.2 백필(D10)에서 과거 날짜로 시드하려면 필수.
--   * status / type 컬럼의 CHECK 제약 — SPEC 주석의 허용값을 DB가 강제
--   * est_minutes > 0 — R1의 하한
--   * 조회용 인덱스, 노드 상태 뷰(§4.4)
--
-- auth.users(Supabase) 가 없는 환경(로컬 Postgres, CI)에서도 그대로 돌아간다.

create extension if not exists pgcrypto;

-- ─────────────────────────────────────────────────────────────
-- 4.2 projects
-- ─────────────────────────────────────────────────────────────
create table projects (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid,
  title         text not null,
  goal_text     text not null,                     -- 원문 목표
  constraints   jsonb not null,                    -- {duration_weeks, hours_per_week, level, stack[], team_size}
  status        text not null default 'active'
                check (status in ('active', 'paused', 'done', 'abandoned')),
  start_date    date not null default current_date, -- week_index 기준일
  created_at    timestamptz not null default now()
);

-- Supabase 위에서만 auth.users FK 를 건다. 로컬/CI 에서는 건너뛴다.
do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'auth' and table_name = 'users'
  ) then
    alter table projects
      add constraint projects_user_id_fkey
      foreign key (user_id) references auth.users(id) on delete cascade;
  end if;
end $$;

-- ─────────────────────────────────────────────────────────────
-- 4.2 milestones / weekly_goals / tickets
-- ─────────────────────────────────────────────────────────────
create table milestones (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  order_index   int not null,
  title         text not null,
  description   text,
  target_date   date,
  status        text not null default 'pending'
                check (status in ('pending', 'in_progress', 'done')),
  unique (project_id, order_index)
);

create table weekly_goals (
  id            uuid primary key default gen_random_uuid(),
  milestone_id  uuid not null references milestones(id) on delete cascade,
  week_index    int not null check (week_index >= 1),  -- 프로젝트 시작 기준 주차
  title         text not null,
  target_date   date
);

create table tickets (
  id             uuid primary key default gen_random_uuid(),
  weekly_goal_id uuid not null references weekly_goals(id) on delete cascade,
  project_id     uuid not null references projects(id) on delete cascade,  -- 집계용 비정규화
  order_index    int not null,
  title          text not null,
  body           text,                              -- 무엇을 / 완료조건 / 참고
  -- R1: 티켓 1개 = 120분 이내. DB 가 강제한다.
  est_minutes    int not null check (est_minutes > 0 and est_minutes <= 120),
  status         text not null default 'todo'
                 check (status in ('todo', 'doing', 'done', 'blocked')),
  due_date       date,
  delay_count    int not null default 0 check (delay_count >= 0),  -- 재점검 트리거 입력값
  blocked_reason text,
  created_at     timestamptz not null default now(),
  completed_at   timestamptz
);

create table ticket_dependencies (
  ticket_id     uuid not null references tickets(id) on delete cascade,
  depends_on    uuid not null references tickets(id) on delete cascade,
  primary key (ticket_id, depends_on),
  check (ticket_id <> depends_on)                   -- 자기 자신 의존 금지
);

-- ─────────────────────────────────────────────────────────────
-- 4.2 아키텍처 그래프
-- ─────────────────────────────────────────────────────────────
create table arch_nodes (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  node_key      text not null,                      -- 'auth', 'netcode', 'db' 등 안정 식별자
  label         text not null,
  node_type     text check (node_type in ('service', 'store', 'client', 'external')),
  layer         text check (layer in ('frontend', 'backend', 'data', 'infra')),
  position      jsonb,                              -- React Flow 좌표 {x, y}
  status        text not null default 'pending'
                check (status in ('pending', 'in_progress', 'done', 'at_risk')),
  unique (project_id, node_key)
);

create table arch_edges (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  from_node     uuid not null references arch_nodes(id) on delete cascade,
  to_node       uuid not null references arch_nodes(id) on delete cascade,
  label         text,
  unique (from_node, to_node)
);

create table ticket_node_links (
  ticket_id     uuid not null references tickets(id) on delete cascade,
  node_id       uuid not null references arch_nodes(id) on delete cascade,
  primary key (ticket_id, node_id)
);

-- ─────────────────────────────────────────────────────────────
-- 4.2 events — 모든 실패 감지의 원천 (R2, R4)
-- ─────────────────────────────────────────────────────────────
create table events (
  id            bigserial primary key,
  project_id    uuid not null references projects(id) on delete cascade,
  ticket_id     uuid references tickets(id) on delete set null,
  node_id       uuid references arch_nodes(id) on delete set null,  -- 집계 최적화
  type          text not null
                check (type in ('created', 'started', 'completed', 'missed', 'deferred', 'blocked')),
  payload       jsonb,
  created_at    timestamptz not null default now()
);

-- §4.5 재점검 트리거 쿼리용
create index events_project_node_type_created_idx
  on events (project_id, node_id, type, created_at);
-- 티켓 단위 이력 조회용 (동일 티켓 2회 연기 규칙, §2.3)
create index events_ticket_type_idx
  on events (ticket_id, type);

-- ─────────────────────────────────────────────────────────────
-- 4.2 재점검 / 재설계
-- ─────────────────────────────────────────────────────────────
create table review_days (
  id             uuid primary key default gen_random_uuid(),
  project_id     uuid not null references projects(id) on delete cascade,
  node_id        uuid references arch_nodes(id) on delete set null,
  scheduled_date date not null,
  trigger_reason text,                              -- '동일 노드 지연 3건'
  status         text not null default 'scheduled'
                 check (status in ('scheduled', 'done', 'postponed')),
  created_at     timestamptz not null default now()
);

-- 같은 노드에 미해결 재점검일이 둘 이상 생기지 않게 한다 (§2.4 트리거 조건).
create unique index review_days_open_per_node_idx
  on review_days (project_id, node_id)
  where status = 'scheduled';

create table replan_sessions (
  id                 uuid primary key default gen_random_uuid(),
  review_day_id      uuid references review_days(id) on delete set null,
  project_id         uuid not null references projects(id) on delete cascade,
  diagnosis          text check (diagnosis in ('지식부족', '범위과다', '의존성누락', '외부요인')),
  scope_milestone_id uuid references milestones(id) on delete set null,
  diff_json          jsonb not null,                -- 변경 전/후
  applied            boolean not null default false,
  created_at         timestamptz not null default now()
);

-- 조회 인덱스
create index milestones_project_idx      on milestones (project_id, order_index);
create index weekly_goals_milestone_idx  on weekly_goals (milestone_id, week_index);
create index tickets_project_status_idx  on tickets (project_id, status);
create index tickets_due_idx             on tickets (due_date) where status <> 'done';
create index arch_nodes_project_idx      on arch_nodes (project_id);
create index arch_edges_project_idx      on arch_edges (project_id);
create index review_days_project_idx     on review_days (project_id, scheduled_date);

-- ─────────────────────────────────────────────────────────────
-- §4.4 노드 상태 계산 — 순수 SQL (R2)
-- 티켓이 하나도 안 붙은 노드는 progress 0 / pending 으로 나온다.
-- ─────────────────────────────────────────────────────────────
create view v_node_status as
select
  n.id                                                as node_id,
  n.project_id,
  n.node_key,
  count(t.id)                                         as ticket_count,
  count(*) filter (where t.status = 'done')::float
    / nullif(count(t.id), 0)                          as progress,
  count(*) filter (where t.delay_count >= 1)          as delayed_tickets,
  case
    when count(*) filter (where t.delay_count >= 1) >= 2 then 'at_risk'
    when count(t.id) = 0                                 then 'pending'
    when count(*) filter (where t.status = 'done') = count(t.id) then 'done'
    when count(*) filter (where t.status = 'done') > 0   then 'in_progress'
    else 'pending'
  end                                                 as status
from arch_nodes n
left join ticket_node_links l on l.node_id = n.id
left join tickets t          on t.id = l.ticket_id
group by n.id, n.project_id, n.node_key;
