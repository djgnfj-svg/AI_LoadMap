/** 티켓 보드 (SPEC §5 좌측 패널). 마일스톤 > 주차별 목표 > 티켓 (§2.1). */
import { useMemo } from "react";

import type { ProjectView, Ticket } from "../api";

interface Props {
  view: ProjectView;
  visibleTicketIds: Set<string> | null; // null 이면 필터 없음
  selectedTicketId: string | null;
  onSelectTicket: (ticket: Ticket) => void;
  onToggleDone: (ticket: Ticket) => void;
}

export function TicketBoard({
  view,
  visibleTicketIds,
  selectedTicketId,
  onSelectTicket,
  onToggleDone,
}: Props) {
  const tree = useMemo(() => {
    const byGoal = new Map<string, Ticket[]>();
    for (const t of view.tickets) {
      if (visibleTicketIds && !visibleTicketIds.has(t.id)) continue;
      const list = byGoal.get(t.weekly_goal_id) ?? [];
      list.push(t);
      byGoal.set(t.weekly_goal_id, list);
    }
    for (const list of byGoal.values()) list.sort((a, b) => a.order_index - b.order_index);

    return view.milestones
      .map((m) => {
        const goals = view.weekly_goals
          .filter((g) => g.milestone_id === m.id)
          .sort((a, b) => a.week_index - b.week_index)
          .map((g) => ({ goal: g, tickets: byGoal.get(g.id) ?? [] }))
          .filter((g) => g.tickets.length > 0);
        return { milestone: m, goals };
      })
      .filter((m) => m.goals.length > 0);
  }, [view, visibleTicketIds]);

  if (tree.length === 0) {
    return <div className="empty">보여줄 티켓이 없습니다.</div>;
  }

  return (
    <>
      {tree.map(({ milestone, goals }) => (
        <div className="milestone" key={milestone.id}>
          <h3>
            <span>{milestone.title}</span>
            <span className="meta">{milestone.target_date ?? ""}</span>
          </h3>
          {goals.map(({ goal, tickets }) => {
            const done = tickets.filter((t) => t.status === "done").length;
            return (
              <div className="week" key={goal.id}>
                <h4>
                  <span>
                    {goal.week_index}주차 · {goal.title}
                  </span>
                  <span className="bar">
                    <i style={{ width: `${(done / tickets.length) * 100}%` }} />
                  </span>
                  <span>
                    {done}/{tickets.length}
                  </span>
                </h4>
                {tickets.map((t) => (
                  <div
                    key={t.id}
                    className={[
                      "ticket",
                      t.status,
                      selectedTicketId === t.id ? "selected" : "",
                    ].join(" ")}
                    onClick={() => onSelectTicket(t)}
                  >
                    <div
                      className="check"
                      role="checkbox"
                      aria-checked={t.status === "done"}
                      aria-label={`${t.title} 완료`}
                      onClick={(e) => {
                        e.stopPropagation();
                        onToggleDone(t);
                      }}
                    >
                      {t.status === "done" ? "✓" : ""}
                    </div>
                    <div className="body">
                      <div className="title">{t.title}</div>
                      <div className="sub">
                        <span>{t.est_minutes}분</span>
                        {t.due_date && <span>{t.due_date}</span>}
                        {t.delay_count > 0 && (
                          <span className="delay">지연 {t.delay_count}회</span>
                        )}
                        {t.status === "blocked" && <span className="delay">막힘</span>}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      ))}
    </>
  );
}
