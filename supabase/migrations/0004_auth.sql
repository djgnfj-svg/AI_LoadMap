-- 로그인을 붙인다 (SPEC §0.3 개정).
--
-- 왜:
--   §0.3 은 "v1 은 로그인 대신 데모 계정 고정"이었다. 그 결과 projects.user_id 가
--   비어 있고, 프로젝트 id 만 알면 누구나 남의 로드맵을 읽고 고칠 수 있다.
--   로드맵이 「내 것」이 되려면 계정이 먼저 있어야 한다.
--
-- 구글만 받는다:
--   비밀번호를 직접 보관하면 재설정·해시·유출 대응이 전부 딸려 온다. 로그인은
--   이 도구의 본론이 아니므로 그 전부를 구글에 맡긴다.
--
-- users 를 직접 든다 (auth.users 가 아니라):
--   0001 은 Supabase 위에서만 auth.users FK 를 걸었다. 이 프로젝트는 로컬
--   Postgres 에서 돌고 인증도 백엔드가 직접 하므로 계정 표를 여기 둔다.
--   0001 의 그 조건부 FK 는 여기서 걷어낸다.
--
-- 데모 계정:
--   API 키가 없으면 목업 Planner 로 도는 것과 같은 결이다. 구글 클라이언트 ID 가
--   없으면 데모 계정으로 로그인한다. 시드 스크립트와 테스트도 이 계정을 쓴다.
--   그래서 이 계정은 설정값이 아니라 실제 행이어야 한다.

create table users (
  id            uuid primary key default gen_random_uuid(),
  -- 구글이 주는 불변 식별자. 이메일은 바뀔 수 있어서 키로 쓰지 않는다.
  google_sub    text unique,
  email         text not null unique,
  display_name  text,
  avatar_url    text,
  created_at    timestamptz not null default now(),
  last_login_at timestamptz
);

-- 데모 계정. id 는 설정 기본값(DEMO_USER_ID)과 같아야 한다.
insert into users (id, email, display_name)
values ('00000000-0000-0000-0000-000000000001', 'demo@localhost', '데모 계정')
on conflict (id) do nothing;

-- 주인 없는 프로젝트는 데모 계정이 받는다. 시드로 만든 것들이다.
update projects
   set user_id = '00000000-0000-0000-0000-000000000001'
 where user_id is null;

alter table projects drop constraint if exists projects_user_id_fkey;
alter table projects
  add constraint projects_user_id_fkey
  foreign key (user_id) references users(id) on delete cascade;
alter table projects alter column user_id set not null;

-- 로그인하면 제일 먼저 그리는 것이 「내 프로젝트 목록」이다.
create index projects_user_idx on projects (user_id, created_at desc);
