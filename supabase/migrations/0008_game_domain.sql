-- 0008: 게임 제작 프리셋 (SPEC §1.5)
--
-- 0007 은 축을 「소프트웨어 / 그 밖」으로 잡았고, 그 「그 밖」이 학습·자격증 쪽을
-- 보고 있었다. 이 도구가 잘하는 일은 그쪽이 아니다 — 티켓이 노드를 채우고 그림이
-- 차오르려면 **만들어지는 것**이 있어야 한다. 점수에는 구성요소가 없다.
--
-- 축을 제작으로 다시 잡는다: 소프트웨어 / 게임 / 그 밖의 만들기.
-- 게임은 소프트웨어지만 낱말이 다르다 — 컴포넌트가 아니라 시스템과 콘텐츠다.
alter table projects drop constraint if exists projects_domain_check;
alter table projects
  add constraint projects_domain_check check (domain in ('software', 'game', 'general'));

alter table arch_nodes drop constraint if exists arch_nodes_node_type_check;
alter table arch_nodes
  add constraint arch_nodes_node_type_check check (
    node_type in (
      -- software
      'service', 'store', 'client',
      -- game
      'system', 'stage', 'asset',
      -- 그 밖의 만들기
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
      -- game
      'play', 'rule', 'content', 'build',
      -- 그 밖의 만들기
      'output', 'practice', 'input', 'support'
    )
  );
