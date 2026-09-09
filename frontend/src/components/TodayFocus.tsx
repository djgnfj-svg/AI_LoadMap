/** 오늘 포커스 (SPEC §5 좌측 패널 「오늘」 탭). 고르는 규칙은 src/today.ts 에 있다. */
import { useMemo, useState, type ReactNode } from "react";

import type { ProjectView, Ticket } from "../api";
import { daysBetween, selectTodayFocus } from "../today";
import { TicketRow } from "./TicketBoard";

interface Props {
  view: ProjectView;
  today: string;
  visibleTicketIds: Set<string> | null;
  selectedTicketId: string | null;
  onSelectTicket: (ticket: Ticket) => void;
  onToggleDone: (ticket: Ticket) => void;
}

export function TodayFocus({
  view,
  today,
  visibleTicketIds,
  selectedTicketId,
  onSelectTicket,
  onToggleDone,
}: Props) {
  const plan = useMemo(
    () => selectTodayFocus(view, today, visibleTicketIds),
    [view, today, visibleTicketIds],
  );
  const [showLater, setShowLater] = useState(false);
  const [showWaiting, setShowWaiting] = useState(false);

  const pickCount = plan.overdue.length + plan.today.length;
  const over = plan.plannedMinutes > plan.capacityMinutes;
  const fill = Math.min(100, (plan.plannedMinutes / plan.capacityMinutes) * 100);

  const row = (t: Ticket, extra?: ReactNode) => (
    <TicketRow
      key={t.id}
      ticket={t}
      selected={selectedTicketId === t.id}
      onSelect={onSelectTicket}
      onToggleDone={onToggleDone}
      extra={extra}
    />
  );

  return (
    <div className="today">
      <div className="today-head">
        <span className="date">{today}</span>
        <span className="count">
          할 수 있는 일 <b>{pickCount}</b>건 · {plan.plannedMinutes}분
        </span>
      </div>
      <div className={over ? "capacity over" : "capacity"}>
        <i style={{ width: `${fill}%` }} />
      </div>
      <div className="capacity-note">
        하루 몫 {plan.capacityMinutes}분
        {over && <b> · {plan.plannedMinutes - plan.capacityMinutes}분 넘침</b>}
      </div>

      {pickCount === 0 && plan.blocked.length === 0 && plan.waiting.length === 0 && (
        <div className="empty">남은 티켓이 없습니다.</div>
      )}

      {plan.overdue.length > 0 && (
        <section className="today-section">
          <h4 className="risk">밀린 것</h4>
          {plan.overdue.map((t) =>
            row(
              t,
              t.due_date ? (
                <span className="delay">{daysBetween(t.due_date, today)}일 지남</span>
              ) : undefined,
            ),
          )}
        </section>
      )}

      {plan.today.length > 0 && (
        <section className="today-section">
          <h4>오늘 할 것</h4>
          {plan.today.map((t) => row(t))}
        </section>
      )}

      {pickCount === 0 && (plan.blocked.length > 0 || plan.waiting.length > 0) && (
        <div className="notice warn">
          <h4>지금 손댈 수 있는 티켓이 없습니다</h4>
          <ul>
            <li>막힌 것을 먼저 풀어야 나머지가 따라 움직입니다.</li>
          </ul>
        </div>
      )}

      {plan.blocked.length > 0 && (
        <section className="today-section">
          <h4>막힌 것</h4>
          {plan.blocked.map((t) => (
            <div key={t.id}>
              {row(t)}
              {t.blocked_reason && <p className="reason">{t.blocked_reason}</p>}
            </div>
          ))}
        </section>
      )}

      {plan.waiting.length > 0 && (
        <section className="today-section">
          <h4 className="foldable" onClick={() => setShowWaiting((v) => !v)}>
            {showWaiting ? "▾" : "▸"} 선행 대기 {plan.waiting.length}건
          </h4>
          {showWaiting &&
            plan.waiting.map(({ ticket, blockers }) => (
              <div key={ticket.id}>
                {row(ticket)}
                <p className="reason">
                  「{blockers.map((b) => b.title).join("」, 「")}」이(가) 끝나야 시작할 수 있습니다
                </p>
              </div>
            ))}
        </section>
      )}

      {plan.later.length > 0 && (
        <section className="today-section">
          <h4 className="foldable" onClick={() => setShowLater((v) => !v)}>
            {showLater ? "▾" : "▸"} 나중에 {plan.later.length}건
          </h4>
          {showLater && plan.later.map((t) => row(t))}
        </section>
      )}
    </div>
  );
}
