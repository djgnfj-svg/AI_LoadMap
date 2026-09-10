-- 0009: 도메인을 게임 · 소프트웨어 · 웹 셋으로 좁힌다 (SPEC §1.5)
--
-- 0008 은 「소프트웨어 / 게임 / 그 밖의 만들기」였다. 그 「그 밖」이 문제였다 —
-- 영상·글·제품까지 받으려다 보니 노드 유형이 결과물·기술·재료처럼 뭉뚱그려졌고,
-- 그래서는 그림이 그려지지 않는다. 채울 칸이 뚜렷한 것만 남긴다.
--
-- 또 하나: 무엇을 만드는지는 이제 **첫 화면에서 사용자가 직접 고른다.** 추론에
-- 맡기면 두 번째 질문부터가 통째로 어긋나고 되돌릴 방법이 없다.
update projects set domain = 'software' where domain = 'general';

alter table projects drop constraint if exists projects_domain_check;
alter table projects
  add constraint projects_domain_check check (domain in ('game', 'software', 'web'));

alter table arch_nodes drop constraint if exists arch_nodes_node_type_check;
alter table arch_nodes
  add constraint arch_nodes_node_type_check check (
    node_type in (
      -- game
      'system', 'stage', 'asset',
      -- software
      'service', 'store', 'client',
      -- web
      'page', 'api',
      -- 공통
      'external'
    )
  );

alter table arch_nodes drop constraint if exists arch_nodes_layer_check;
alter table arch_nodes
  add constraint arch_nodes_layer_check check (
    layer in (
      -- game
      'play', 'rule', 'content', 'build',
      -- software · web
      'frontend', 'backend', 'data', 'infra'
    )
  );
