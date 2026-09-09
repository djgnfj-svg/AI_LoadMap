/** 아키텍처 다이어그램 (SPEC §5 우측 패널). */
import { useEffect, useMemo, useRef } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { ProjectView } from "../api";
import { ArchNode, type ArchFlowNode } from "./ArchNode";

const nodeTypes = { arch: ArchNode };

interface Props {
  view: ProjectView;
  selectedNodeId: string | null;
  highlightedNodeIds: Set<string>;
  onSelectNode: (nodeId: string | null) => void;
  /** 값이 바뀌면 화면에 다시 맞춘다 (상세 패널이 열리고 닫힐 때). */
  refitSignal: unknown;
}

export function ArchDiagram({
  view,
  selectedNodeId,
  highlightedNodeIds,
  onSelectNode,
  refitSignal,
}: Props) {
  const instance = useRef<ReactFlowInstance<ArchFlowNode, Edge> | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<ArchFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  // 사용자가 끌어다 놓은 좌표는 데이터가 갱신돼도 유지한다.
  const dragged = useRef<Record<string, { x: number; y: number }>>({});

  const doneByNode = useMemo(() => {
    const ticketStatus = new Map(view.tickets.map((t) => [t.id, t.status]));
    const counts: Record<string, number> = {};
    for (const link of view.ticket_node_links) {
      if (ticketStatus.get(link.ticket_id) === "resolved") {
        counts[link.node_id] = (counts[link.node_id] ?? 0) + 1;
      }
    }
    return counts;
  }, [view.tickets, view.ticket_node_links]);

  useEffect(() => {
    setNodes((current) => {
      for (const n of current) dragged.current[n.id] = n.position;
      return view.arch_nodes.map((n) => ({
        id: n.id,
        type: "arch" as const,
        position: dragged.current[n.id] ?? n.position ?? { x: 0, y: 0 },
        data: {
          label: n.label,
          nodeKey: n.node_key,
          status: n.computed_status,
          progress: n.progress ?? 0,
          ticketCount: n.ticket_count,
          doneCount: doneByNode[n.id] ?? 0,
          delayedTickets: n.delayed_tickets,
          highlighted: highlightedNodeIds.has(n.id) || selectedNodeId === n.id,
          dimmed: highlightedNodeIds.size > 0 && !highlightedNodeIds.has(n.id),
        },
      }));
    });
  }, [view.arch_nodes, doneByNode, highlightedNodeIds, selectedNodeId, setNodes]);

  useEffect(() => {
    setEdges(
      view.arch_edges.map((e) => ({
        id: e.id,
        source: e.from_node,
        target: e.to_node,
        label: e.label ?? undefined,
        animated: highlightedNodeIds.has(e.from_node) && highlightedNodeIds.has(e.to_node),
        style: { stroke: "#39424e" },
        labelStyle: { fill: "#8b949e", fontSize: 11 },
        labelBgStyle: { fill: "#161b22" },
      })),
    );
  }, [view.arch_edges, highlightedNodeIds, setEdges]);

  useEffect(() => {
    const timer = setTimeout(() => instance.current?.fitView({ duration: 250 }), 60);
    return () => clearTimeout(timer);
  }, [refitSignal]);

  return (
    <>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        colorMode="dark"
        onInit={(i) => {
          instance.current = i;
        }}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, node) => onSelectNode(node.id === selectedNodeId ? null : node.id)}
        onPaneClick={() => onSelectNode(null)}
        fitView
        proOptions={{ hideAttribution: false }}
      >
        <Background color="#262d36" gap={20} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable maskColor="rgba(14,17,22,0.7)" nodeColor="#30363d" />
      </ReactFlow>
      <div className="legend">
        <span><i style={{ borderColor: "#484f58" }} />대기</span>
        <span><i style={{ borderColor: "#58a6ff" }} />진행 중</span>
        <span><i style={{ borderColor: "#3fb950" }} />완료</span>
        <span><i style={{ borderColor: "#f85149" }} />지연 2건 이상</span>
      </div>
    </>
  );
}
