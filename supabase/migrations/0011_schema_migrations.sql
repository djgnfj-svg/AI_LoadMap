-- 어디까지 적용됐는지를 DB 가 기억하게 한다.
--
-- 전까지 `scripts/setup.sh` 는 매번 `supabase/migrations/*.sql` 을 **전부** 먹였다.
-- 이미 있는 DB 에 다시 돌리면 `0001_init.sql` 의 `create table` 에서 죽고,
-- 어디까지 적용됐는지 알 방법도 없었다. 배포하면 두 번째 배포에서 바로 걸린다.
create table if not exists schema_migrations (
  filename   text primary key,
  applied_at timestamptz not null default now()
);
