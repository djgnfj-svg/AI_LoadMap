/** 티켓 보드 (SPEC §5 좌측 패널). 주 > 태스크 > 티켓 (§2.1). */
import { useMemo, type ReactNode } from "react";

import type { ProjectView, Task, Ticket, WeeklyGoal } from "../api";
import { ticketNumber } from "../tickets";

interface RowProps {
  ticket: Ticket;
  selected: boolean;
  onSelect: (ticket: Ticket) => void;
  onToggleDone: (ticket: Ticket) => void;
  /** 티켓 번호 (NN-MM). 태스크가 없으면 안 붙는다. */
  number?: string | null;
  /** 상태 줄 끝에 덧붙일 배지 (오늘 탭에서 "3일 지남" 같은 것). */
  extra?: ReactNode;
}

/** 티켓 한 줄. 「전체」와 「오늘」이 같은 마크업을 쓴다 — 같은 것은 같아 보여야 한다. */
export function TicketRow({
  ticket,
  selected,
  onSelect,
  onToggleDone,
  number,
  extra,
}: RowProps) {
  const done = ticket.status === "resolved";
  return (
    <div
      className={["ticket", ticket.status, selected ? "selected" : ""].join(" ")}
      onClick={() => onSelect(ticket)}
    >
      <div
        className="check"
        role="checkbox"
        aria-checked={done}
        aria-label={`${ticket.title} 완료`}
        onClick={(e) => {
          e.stopPropagation();
          onToggleDone(ticket);
        }}
      >
        {done ? "✓" : ""}
      </div>
      <div className="body">
        <div className="title">
          {number && <span className="num">{number}</span>}
          {ticket.title}
        </div>
        <div className="sub">
          <span>{ticket.est_minutes}분</span>
          {ticket.due_date && <span>{ticket.due_date}</span>}
          {ticket.delay_count > 0 && <span className="delay">지연 {ticket.delay_count}회</span>}
          {/* 막힘은 상태가 아니다 — 사유 한 줄이 붙어 있으면 막힌 것이다. */}
          {ticket.blocked_reason && <span className="delay">막힘</span>}
          {extra}
        </div>
      </div>
    </div>
  );
}

interface Props {
  view: ProjectView;
  visibleTicketIds: Set<string> | null; // null 이면 필터 없음
  selectedTicketId: string | null;
  onSelectTicket: (ticket: Ticket) => void;
  onToggleDone: (ticket: Ticket) => void;
}

interface TaskGroup {
  task: Task;
  tickets: Ticket[];
}

interface WeekGroup {
  /** 주가 아직 안 정해진 태스크를 담는 자리는 goal 이 null 이다. */
  goal: WeeklyGoal | null;
  tasks: TaskGroup[];
}

export function TicketBoard({
  view,
  visibleTicketIds,
  selectedTicketId,
  onSelectTicket,
  onToggleDone,
}: Props) {
  const tree = useMemo<WeekGroup[]>(() => {
    const byTask = new Map<string, Ticket[]>();
    for (const t of view.tickets) {
      if (visibleTicketIds && !visibleTicketIds.has(t.id)) continue;
      if (!t.task_id) continue; // 태스크 없는 티켓은 아래에서 따로 모은다
      const list = byTask.get(t.task_id) ?? [];
      list.push(t);
      byTask.set(t.task_id, list);
    }
    for (const list of byTask.values()) {
      list.sort((a, b) => (a.ticket_number ?? 0) - (b.ticket_number ?? 0));
    }

    const taskGroup = (k: Task): TaskGroup => ({ task: k, tickets: byTask.get(k.id) ?? [] });

    const weeks: WeekGroup[] = [...view.weekly_goals]
      .sort((a, b) => (a.week_index ?? 999) - (b.week_index ?? 999))
      .map((g) => ({
        goal: g,
        tasks: view.tasks
          .filter((k) => k.weekly_goal_id === g.id)
          .sort((a, b) => (a.task_number ?? 999) - (b.task_number ?? 999))
          .map(taskGroup)
          .filter((k) => k.tickets.length > 0),
      }));

    // 주가 아직 안 정해진 태스크 (WEEK_TBD).
    const orphanTasks = view.tasks
      .filter((k) => !k.weekly_goal_id)
      .sort((a, b) => (a.task_number ?? 999) - (b.task_number ?? 999))
      .map(taskGroup)
      .filter((k) => k.tickets.length > 0);
    if (orphanTasks.length > 0) weeks.push({ goal: null, tasks: orphanTasks });

    return weeks.filter((w) => w.tasks.length > 0);
  }, [view, visibleTicketIds]);

  if (tree.length === 0) {
    return <div className="empty">보여줄 티켓이 없습니다.</div>;
  }

  return (
    <>
      {tree.map(({ goal, tasks }) => {
        const all = tasks.flatMap((k) => k.tickets);
        const done = all.filter((t) => t.status === "resolved").length;
        return (
          <div className="week" key={goal?.id ?? "__tbd"}>
            <h3>
              <span>
                {goal ? `${goal.week_index}주 · ${goal.title}` : "주가 아직 안 정해졌습니다"}
              </span>
              <span className="meta">{goal?.target_date ?? ""}</span>
            </h3>
            <div className="week-bar">
              <span className="bar">
                <i style={{ width: `${(done / all.length) * 100}%` }} />
              </span>
              <span>
                {done}/{all.length}
              </span>
            </div>
            {tasks.map(({ task, tickets }) => {
              const taskDone = tickets.filter((t) => t.status === "resolved").length;
              return (
                <div className="task" key={task.id}>
                  <h4>
                    <span>
                      {task.task_number != null && (
                        <span className="num">
                          {String(task.task_number).padStart(2, "0")}
                        </span>
                      )}
                      {task.title}
                    </span>
                    <span>
                      {taskDone}/{tickets.length}
                    </span>
                  </h4>
                  {tickets.map((t) => (
                    <TicketRow
                      key={t.id}
                      ticket={t}
                      number={ticketNumber(task, t)}
                      selected={selectedTicketId === t.id}
                      onSelect={onSelectTicket}
                      onToggleDone={onToggleDone}
                    />
                  ))}
                </div>
              );
            })}
          </div>
        );
      })}
    </>
  );
}
