/** 티켓 상세 (SPEC §5). 복사 버튼이 곧 코딩 에이전트 프롬프트다 (§2.2). */
import { useState } from "react";

import type { ArchNodeRow, ProjectView, Ticket } from "../api";

interface Props {
  view: ProjectView;
  ticket: Ticket;
  onClose: () => void;
  onAction: (
    action: "start" | "complete" | "block" | "unblock" | "defer",
    extra?: { reason?: string },
  ) => void;
  onSelectNode: (nodeId: string) => void;
}

function agentPrompt(ticket: Ticket, nodes: ArchNodeRow[], deps: Ticket[]): string {
  const lines = [`# ${ticket.title}`, "", ticket.body ?? ""];
  if (nodes.length > 0) {
    lines.push("", `연결 컴포넌트: ${nodes.map((n) => n.node_key).join(", ")}`);
  }
  if (deps.length > 0) {
    lines.push(`선행 티켓: ${deps.map((d) => d.title).join(" / ")}`);
  }
  lines.push(`예상 소요: ${ticket.est_minutes}분`);
  return lines.join("\n");
}

export function TicketDetail({ view, ticket, onClose, onAction, onSelectNode }: Props) {
  const [copied, setCopied] = useState(false);
  const [reason, setReason] = useState("");

  const nodeIds = new Set(
    view.ticket_node_links.filter((l) => l.ticket_id === ticket.id).map((l) => l.node_id),
  );
  const nodes = view.arch_nodes.filter((n) => nodeIds.has(n.id));

  const depIds = new Set(
    view.ticket_dependencies.filter((d) => d.ticket_id === ticket.id).map((d) => d.depends_on),
  );
  const deps = view.tickets.filter((t) => depIds.has(t.id));
  const blockedByOpenDep = deps.some((d) => d.status !== "resolved");

  const copy = async () => {
    await navigator.clipboard.writeText(agentPrompt(ticket, nodes, deps));
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };

  return (
    <aside className="detail">
      <header>
        <h3>{ticket.title}</h3>
        <button onClick={onClose} aria-label="닫기">
          ✕
        </button>
      </header>
      <div className="sub">
        {ticket.est_minutes}분 · {ticket.status}
        {ticket.due_date && ` · 마감 ${ticket.due_date}`}
        {ticket.delay_count > 0 && ` · 지연 ${ticket.delay_count}회`}
      </div>

      <button className="primary" onClick={copy}>
        {copied ? "복사됨" : "에이전트 프롬프트로 복사"}
      </button>

      <section>
        <h5>본문</h5>
        <pre>{ticket.body ?? "(본문 없음)"}</pre>
      </section>

      {nodes.length > 0 && (
        <section>
          <h5>연결 컴포넌트</h5>
          {nodes.map((n) => (
            <button key={n.id} className="chip" onClick={() => onSelectNode(n.id)}>
              <span
                className="dot"
                style={{
                  background:
                    n.computed_status === "at_risk"
                      ? "#f85149"
                      : n.computed_status === "done"
                        ? "#3fb950"
                        : n.computed_status === "in_progress"
                          ? "#58a6ff"
                          : "#484f58",
                }}
              />
              {n.label}
            </button>
          ))}
        </section>
      )}

      {deps.length > 0 && (
        <section>
          <h5>선행 티켓</h5>
          {deps.map((d) => (
            <div key={d.id} className="sub" style={{ marginBottom: 4 }}>
              {d.status === "resolved" ? "✓" : "○"} {d.title}
            </div>
          ))}
          {blockedByOpenDep && (
            <div className="notice warn" style={{ marginTop: 8 }}>
              아직 안 끝난 선행 티켓이 있습니다.
            </div>
          )}
        </section>
      )}

      {ticket.blocked_reason && (
        <section>
          <h5>막힘 사유</h5>
          <div className="sub">{ticket.blocked_reason}</div>
        </section>
      )}

      <section>
        <h5>어디서 막혔나요?</h5>
        <input
          value={reason}
          placeholder="한 줄로 적어주세요"
          onChange={(e) => setReason(e.target.value)}
        />
        <div className="actions">
          <button
            disabled={!reason.trim()}
            onClick={() => {
              onAction("block", { reason: reason.trim() });
              setReason("");
            }}
          >
            막힘 기록
          </button>
        </div>
      </section>

      <div className="actions">
        {ticket.status !== "resolved" && (
          <button className="primary" onClick={() => onAction("complete")}>
            완료
          </button>
        )}
        {ticket.status === "open" && <button onClick={() => onAction("start")}>시작</button>}
        {ticket.blocked_reason !== null && (
          <button onClick={() => onAction("unblock")}>막힘 해제</button>
        )}
        {ticket.status !== "resolved" && <button onClick={() => onAction("defer")}>연기</button>}
      </div>
    </aside>
  );
}
