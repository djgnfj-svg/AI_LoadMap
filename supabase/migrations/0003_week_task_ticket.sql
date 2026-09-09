-- 계층을 주 > 태스크 > 티켓으로 바꾼다.
--
-- 왜:
--   전에는 마일스톤 > 주차 목표 > 티켓이었다. 티켓이 주에 바로 매달려서
--   「섬이 어떻게 보이나」처럼 한 덩어리로 묶이는 일곱 티켓을 표현할 자리가
--   없었다. 주 아래에서 티켓이 평평하게 깔리면 스무 개가 넘어가는 주에
--   무엇이 한 묶음인지 읽을 수 없다.
--
--   그래서 **주가 관리 단위**고, 주 안에 태스크가 살고, 태스크 안에 티켓이 산다.
--   한 태스크는 한 주에만 산다.
--
-- 마일스톤을 없앤다:
--   주가 최상위 관리 단위가 되면 마일스톤은 아무것도 안 든다.
--   R3 의 재설계 범위도 마일스톤 1개에서 주 1개로 내려간다 — 범위가 더
--   좁아지므로 R3 의 의도(한 번에 하나만 다시 그린다)는 그대로다.
--
-- 상태 낱말:
--   todo/doing/done/blocked -> open/claimed/resolved/parked. 태스크와 티켓이
--   같은 낱말을 쓴다.
--   ⚠ 「막힘」은 상태에서 빠진다. parked 는 접힘(의도적으로 미룸)이지
--   막힘이 아니다. 막힘은 blocked_reason 컬럼과 blocked 이벤트가 계속 든다 —
--   상태 한 낱말과 막힘 한 줄은 별개의 사실이고, 섞으면 둘 다 못 읽는다.
--   그래서 status = 'blocked' 이던 티켓은 claimed + blocked_reason 으로 간다.
--
-- 번호:
--   태스크는 프로젝트 안에서 전역으로 센다 (2 주에 TASK17 이 있을 수 있다).
--   티켓은 태스크마다 01 부터 다시 센다. 티켓을 부르는 이름이 NN-MM 이다.
--
-- 미정(TBD):
--   주가 안 정해진 태스크, 태스크가 안 정해진 티켓을 받는다. FK 를 푼다.
--   ⚠ 태스크가 없으면 티켓 번호도 없다 — 번호 앞자리가 태스크이기 때문이다.
--
-- ⚠ 절 순서가 중요하다. 주를 합치는 것(4)은 티켓이 주에서 떨어져 나온
--   뒤(3)에 와야 한다. tickets.weekly_goal_id 가 on delete cascade 라,
--   먼저 합치면 지워지는 주에 매달린 티켓이 같이 사라진다.

-- ─────────────────────────────────────────────────────────────
-- 1. weekly_goals 가 프로젝트에 바로 매달린다
-- ─────────────────────────────────────────────────────────────
alter table weekly_goals add column project_id uuid references projects(id) on delete cascade;

update weekly_goals w
   set project_id = m.project_id
  from milestones m
 where m.id = w.milestone_id;

alter table weekly_goals alter column project_id set not null;
alter table weekly_goals alter column week_index drop not null;  -- 주 미정을 받는다
alter table weekly_goals drop column milestone_id;

create index weekly_goals_project_idx on weekly_goals (project_id, week_index);

-- ─────────────────────────────────────────────────────────────
-- 2. 태스크 — 주와 티켓 사이
-- ─────────────────────────────────────────────────────────────
create table tasks (
  id             uuid primary key default gen_random_uuid(),
  project_id     uuid not null references projects(id) on delete cascade,
  -- ⚠ null 이면 주가 안 정해진 것이다 (WEEK_TBD).
  weekly_goal_id uuid references weekly_goals(id) on delete set null,
  -- 프로젝트 안에서 전역으로 센다. null 이면 아직 번호가 없다.
  task_number    int check (task_number >= 1),
  title          text not null,
  description    text,
  status         text not null default 'open'
                 check (status in ('open', 'claimed', 'resolved', 'parked')),
  created_at     timestamptz not null default now(),
  unique (project_id, task_number)
);

create index tasks_project_idx on tasks (project_id, task_number);
create index tasks_weekly_goal_idx on tasks (weekly_goal_id);

-- 지금 있는 티켓은 태스크 아래에 있던 적이 없다. 주차 목표마다 태스크 하나를
-- 세워 그 목표의 티켓을 통째로 담는다 — 없는 묶음을 지어내지 않는다.
-- ⚠ 옛 스키마에서는 한 주차에 주차 목표가 여럿일 수 있었다(마일스톤마다 하나).
--   그 나뉨이 곧 사람이 만들어 둔 묶음이라, 태스크는 그것을 그대로 물려받는다.
--   주 자체는 4 절에서 하나로 합친다.
insert into tasks (project_id, weekly_goal_id, task_number, title, status)
select
  w.project_id,
  w.id,
  row_number() over (partition by w.project_id order by w.week_index, w.id),
  w.title,
  'open'
from weekly_goals w;

-- ─────────────────────────────────────────────────────────────
-- 3. 티켓이 태스크에 매달린다
-- ─────────────────────────────────────────────────────────────
alter table tickets add column task_id uuid references tasks(id) on delete set null;

update tickets t
   set task_id = k.id
  from tasks k
 where k.weekly_goal_id = t.weekly_goal_id;

-- ⚠ 이 시점부터 티켓은 주를 직접 가리키지 않는다. 4 절에서 주를 지워도
--   티켓이 딸려 나가지 않는 이유가 이것이다.
alter table tickets drop column weekly_goal_id;

-- order_index 는 주 안에서의 순서였다. 이제 태스크 안에서의 번호다 —
-- 이름이 사실을 말하게 바꾼다. 티켓을 부르는 이름의 뒷자리가 이것이다.
alter table tickets rename column order_index to ticket_number;
alter table tickets alter column ticket_number drop not null;  -- 태스크 미정이면 번호가 없다

-- ⚠ 번호는 태스크마다 01 부터 다시 센다. 옛 order_index 는 주 안에서 이어
-- 세던 값이라 그대로 두면 태스크 하나가 11 부터 시작한다. 순서만 물려받고
-- 번호는 다시 매긴다. (unique 인덱스보다 먼저 해야 한다 — 값을 맞바꾸는
-- 도중에 잠깐 겹칠 수 있다.)
with renumbered as (
  select id, row_number() over (partition by task_id order by ticket_number, id) as n
    from tickets
   where task_id is not null
)
update tickets t set ticket_number = r.n from renumbered r where r.id = t.id;

alter table tickets add constraint tickets_ticket_number_positive
  check (ticket_number is null or ticket_number >= 1);
-- 태스크가 정해진 티켓은 그 안에서 번호가 겹치지 않는다.
create unique index tickets_task_number_idx on tickets (task_id, ticket_number)
  where task_id is not null and ticket_number is not null;
-- ⚠ 태스크가 없으면 번호도 없다 — 번호 앞자리가 태스크이기 때문이다.
alter table tickets add constraint tickets_number_needs_task
  check (task_id is not null or ticket_number is null);

-- ─────────────────────────────────────────────────────────────
-- 4. 한 주는 한 줄이다
-- ─────────────────────────────────────────────────────────────
-- 전에는 한 주차에 주차 목표가 여럿 설 수 있었다 — 마일스톤마다 하나씩이라
-- 「1주차」가 두 줄이었다. 이제 주가 관리 단위라 한 주는 한 줄이다.
-- 같은 주차의 것들을 하나로 합친다. 합쳐지는 쪽의 제목은 버리지 않고 이어
-- 붙인다 — 사람이 쓴 문장이라 지어낼 수 없다.
create temporary table _week_merge as
select
  w.id                                                        as old_id,
  first_value(w.id) over (
    partition by w.project_id, w.week_index order by w.id
  )                                                           as keep_id
from weekly_goals w
where w.week_index is not null;

-- 사라질 주를 가리키던 태스크를 남는 주로 옮긴다. 지우기 전에 옮겨야
-- 어느 주에 있던 태스크인지 알 수 있다.
update tasks k
   set weekly_goal_id = m.keep_id
  from _week_merge m
 where m.old_id = k.weekly_goal_id and m.keep_id <> m.old_id;

update weekly_goals w
   set title = agg.title, target_date = coalesce(agg.target_date, w.target_date)
  from (
    select m.keep_id,
           string_agg(g.title, ' · ' order by g.id) as title,
           max(g.target_date)                       as target_date
      from _week_merge m
      join weekly_goals g on g.id = m.old_id
     group by m.keep_id
  ) agg
 where agg.keep_id = w.id;

delete from weekly_goals w
 using _week_merge m
 where m.old_id = w.id and m.keep_id <> m.old_id;

drop table _week_merge;

-- 한 프로젝트에 같은 주는 하나뿐이다.
create unique index weekly_goals_project_week_idx
  on weekly_goals (project_id, week_index)
  where week_index is not null;

-- ─────────────────────────────────────────────────────────────
-- 5. 상태 낱말 — 태스크와 티켓이 같은 넷을 쓴다
-- ─────────────────────────────────────────────────────────────
alter table tickets alter column status drop default;
alter table tickets drop constraint tickets_status_check;

update tickets set status = case status
  when 'todo'    then 'open'
  when 'doing'   then 'claimed'
  when 'done'    then 'resolved'
  -- 막혔다는 것은 잡고 있다가 멈췄다는 뜻이다. 사유는 blocked_reason 이 든다.
  when 'blocked' then 'claimed'
  else status
end;

alter table tickets add constraint tickets_status_check
  check (status in ('open', 'claimed', 'resolved', 'parked'));
alter table tickets alter column status set default 'open';

-- 세워둔 태스크의 상태를 그 안의 티켓에서 되읽는다.
update tasks k set status = sub.status
  from (
    select
      t.task_id,
      case
        when count(*) filter (where t.status = 'resolved') = count(*) then 'resolved'
        when count(*) filter (where t.status <> 'open') > 0           then 'claimed'
        else 'open'
      end as status
    from tickets t
    where t.task_id is not null
    group by t.task_id
  ) sub
 where sub.task_id = k.id;

-- ─────────────────────────────────────────────────────────────
-- 6. 재설계 범위가 마일스톤에서 주로 내려간다 (R3)
-- ─────────────────────────────────────────────────────────────
-- ⚠ 과거 세션의 범위는 안 옮긴다. 마일스톤 하나가 주 여럿을 담고 있어서
-- 어느 주였는지 되찾을 수 없다. 지나간 재설계 기록의 diff 는 그대로 남고
-- 범위 칸만 빈다 — 없는 사실을 지어내는 것보다 낫다.
alter table replan_sessions add column scope_weekly_goal_id uuid
  references weekly_goals(id) on delete set null;

alter table replan_sessions drop column scope_milestone_id;

-- ─────────────────────────────────────────────────────────────
-- 7. 마일스톤을 없앤다
-- ─────────────────────────────────────────────────────────────
drop index if exists milestones_project_idx;
drop table milestones;

-- ─────────────────────────────────────────────────────────────
-- 8. 'done' 을 보던 것들을 'resolved' 로
-- ─────────────────────────────────────────────────────────────
drop index if exists tickets_due_idx;
create index tickets_due_idx on tickets (due_date) where status <> 'resolved';

drop view if exists v_node_status;
create view v_node_status as
select
  n.id                                                as node_id,
  n.project_id,
  n.node_key,
  count(t.id)                                         as ticket_count,
  count(*) filter (where t.status = 'resolved')::float
    / nullif(count(t.id), 0)                          as progress,
  count(*) filter (where t.delay_count >= 1)          as delayed_tickets,
  case
    when count(*) filter (where t.delay_count >= 1) >= 2 then 'at_risk'
    when count(t.id) = 0                                 then 'pending'
    when count(*) filter (where t.status = 'resolved') = count(t.id) then 'done'
    when count(*) filter (where t.status = 'resolved') > 0 then 'in_progress'
    else 'pending'
  end                                                 as status
from arch_nodes n
left join ticket_node_links l on l.node_id = n.id
left join tickets t          on t.id = l.ticket_id
group by n.id, n.project_id, n.node_key;
