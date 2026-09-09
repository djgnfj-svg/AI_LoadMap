-- 0007: 도메인 프리셋 (SPEC §1.5 2차 타겟)
--
-- 지금까지 이 도구는 소프트웨어를 만드는 사람만 쓸 수 있었다. 아키텍처 노드의
-- 유형과 레이어가 'service/store/client/external', 'frontend/backend/data/infra'
-- 로 못 박혀 있었기 때문이다. 토익 900점이나 유튜브 채널에는 프런트엔드가 없다.
--
-- 낱말만 갈아끼운다. 구조(주 > 태스크 > 티켓, 노드에 티켓이 붙고 완료가 노드를
-- 채운다, 지연이 쌓이면 재점검일)는 도메인과 무관하게 그대로다.
alter table projects
  add column if not exists domain text not null default 'software';

alter table projects drop constraint if exists projects_domain_check;
alter table projects
  add constraint projects_domain_check check (domain in ('software', 'general'));

-- 두 프리셋의 값을 함께 허용한다. 어느 낱말을 쓸지는 projects.domain 이 정하고,
-- 프롬프트가 그 목록만 내놓게 한다.
alter table arch_nodes drop constraint if exists arch_nodes_node_type_check;
alter table arch_nodes
  add constraint arch_nodes_node_type_check check (
    node_type in (
      -- software
      'service', 'store', 'client',
      -- general
      'deliverable', 'skill', 'resource',
      -- 공통
      'external'
    )
  );

alter table arch_nodes drop constraint if exists arch_nodes_layer_check;
alter table arch_nodes
  add constraint arch_nodes_layer_check check (
    layer in (
      -- software
      'frontend', 'backend', 'data', 'infra',
      -- general
      'output', 'practice', 'input', 'support'
    )
  );
