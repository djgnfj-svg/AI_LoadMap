/** 메인 화면 (SPEC §5). 좌: 티켓 보드 / 우: React Flow 다이어그램.
 *
 * 양방향 하이라이트가 제품 인상을 결정한다.
 * 티켓을 클릭하면 해당 노드가 빛나고, 노드를 클릭하면 관련 티켓만 필터된다.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { api, type ProjectView, type Ticket } from "../api";
import { ArchDiagram } from "../components/ArchDiagram";
import { TicketBoard } from "../components/TicketBoard";
import { TicketDetail } from "../components/TicketDetail";

interface Props {
  projectId: string;
  onBack: () => void;
}

export function Main({ projectId, onBack }: Props) {
  const [view, setView] = useState<ProjectView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setView(await api.getProject(projectId));
    } catch (e) {
      setError(String(e));
    }
  }, [projectId]);

  useEffect(() => {
    // setState 는 await 뒤에서 일어나므로 동기 호출이 아니다. 서버에서 계획을 읽어오는
    // 것 자체가 외부 시스템 동기화라 effect 가 맞는 자리다.
    // oxlint-disable-next-line react/set-state-in-effect
    void refresh();
  }, [refresh]);

  // 티켓 -> 노드 (선택한 티켓이 어느 컴포넌트를 만드는가)
  const highlightedNodeIds = useMemo(() => {
    if (!view) return new Set<string>();
    if (selectedNodeId) return new Set([selectedNodeId]);
    if (!selectedTicketId) return new Set<string>();
    return new Set(
      view.ticket_node_links
        .filter((l) => l.ticket_id === selectedTicketId)
        .map((l) => l.node_id),
    );
  }, [view, selectedTicketId, selectedNodeId]);

  // 노드 -> 티켓 (선택한 컴포넌트를 만드는 티켓만 남긴다)
  const visibleTicketIds = useMemo(() => {
    if (!view || !selectedNodeId) return null;
    return new Set(
      view.ticket_node_links.filter((l) => l.node_id === selectedNodeId).map((l) => l.ticket_id),
    );
  }, [view, selectedNodeId]);

  const act = async (
    ticket: Ticket,
    action: "start" | "complete" | "block" | "unblock" | "defer",
    extra?: { reason?: string },
  ) => {
    await api.patchTicket(ticket.id, action, extra);
    await refresh(); // 노드 상태는 서버가 다시 계산한다 (§4.4, R2)
  };

  if (error) return <div className="empty">불러오지 못했습니다: {error}</div>;
  if (!view) return <div className="empty">불러오는 중…</div>;

  const { generation } = view;
  if (generation.status === "running") {
    return <div className="empty">아직 생성 중입니다. 잠시 후 새로고침해 주세요.</div>;
  }
  if (generation.status === "awaiting_clarify") {
    return (
      <div className="empty">
        clarify 질문에 답해야 계획이 만들어집니다.{" "}
        <button className="link-btn" onClick={onBack}>
          입력 화면으로
        </button>
      </div>
    );
  }

  const doneCount = view.tickets.filter((t) => t.status === "done").length;
  const atRisk = view.arch_nodes.filter((n) => n.computed_status === "at_risk");
  const selectedTicket = view.tickets.find((t) => t.id === selectedTicketId) ?? null;
  const selectedNode = view.arch_nodes.find((n) => n.id === selectedNodeId) ?? null;

  return (
    <div className={selectedTicket ? "main with-detail" : "main"}>
      <div className="topbar">
        <button onClick={onBack}>←</button>
        <h2>{view.project.title}</h2>
        <span className="goal">{view.project.goal_text}</span>
        <span className="stat">
          티켓 <b>{doneCount}</b>/{view.tickets.length}
        </span>
        {atRisk.length > 0 && (
          <span className="stat" style={{ color: "#f85149" }}>
            막힌 컴포넌트 <b>{atRisk.length}</b>
          </span>
        )}
      </div>

      <div className="pane left">
        {selectedNode && (
          <div className="filter-banner">
            <span>
              <b>{selectedNode.label}</b> 를 만드는 티켓만 보는 중
            </span>
            <button onClick={() => setSelectedNodeId(null)}>해제</button>
          </div>
        )}
        {generation.repairs.length > 0 && (
          <div className="notice warn" style={{ marginBottom: 14 }}>
            <h4>계획을 자동으로 손봤습니다</h4>
            <ul>
              {generation.repairs.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>
        )}
        <TicketBoard
          view={view}
          visibleTicketIds={visibleTicketIds}
          selectedTicketId={selectedTicketId}
          onSelectTicket={(t) => setSelectedTicketId(t.id === selectedTicketId ? null : t.id)}
          onToggleDone={(t) => void act(t, t.status === "done" ? "start" : "complete")}
        />
      </div>

      <div className="pane right">
        <ArchDiagram
          view={view}
          selectedNodeId={selectedNodeId}
          highlightedNodeIds={highlightedNodeIds}
          refitSignal={selectedTicketId}
          onSelectNode={(id) => {
            setSelectedNodeId(id);
            setSelectedTicketId(null);
          }}
        />
      </div>

      {selectedTicket && (
        <TicketDetail
          view={view}
          ticket={selectedTicket}
          onClose={() => setSelectedTicketId(null)}
          onAction={(action, extra) => void act(selectedTicket, action, extra)}
          onSelectNode={(id) => {
            setSelectedNodeId(id);
            setSelectedTicketId(null);
          }}
        />
      )}
    </div>
  );
}
