/** 티켓을 부르는 이름 (SPEC §2.1). 화면과 분리된 순수 로직. */
import type { Task, Ticket } from "./api";

/** 태스크 번호와 티켓 번호를 두 겹으로 붙인 이름 — 08-03 처럼.
 *
 * 번호는 태스크마다 01 부터 다시 세므로, 앞자리 없이 뒷자리만으로는
 * 티켓이 특정되지 않는다. 그래서 태스크가 없으면 번호도 없다.
 */
export function ticketNumber(task: Task | undefined, ticket: Ticket): string | null {
  if (!task?.task_number || !ticket.ticket_number) return null;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(task.task_number)}-${pad(ticket.ticket_number)}`;
}
