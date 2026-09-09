/** 오늘 할 일을 고르는 규칙 (SPEC §5 「오늘」 탭). 화면과 분리된 순수 로직.
 *
 * 로드맵은 주 단위로 페이스를 잡지만(§2.1 — 주차별 목표가 페이스 관리 단위),
 * 아침에 화면을 여는 사람이 묻는 건 하나다. "그래서 지금 뭘 하지."
 *
 * due_date 로 거르지 않는 이유:
 * 티켓의 due_date 는 주차 목표의 target_date 를 그대로 물려받아 주 경계에
 * 뭉쳐 있다. `due_date == 오늘` 로 필터하면 어떤 날은 0건이고 어떤 날은
 * 하루치를 훌쩍 넘긴다. 그래서 마감일이 아니라 **지금 실제로 손댈 수 있는가**
 * 로 고른다. 선행이 안 끝난 티켓과 막힌 티켓은 오늘 몫에서 빼고 따로 보여준다.
 * 마감이 지났어도 손댈 수 없으면 오늘 할 일이 아니다 — 그건 재점검 대상이다.
 */
import type { ProjectView, Ticket } from "./api";

/** 주 5일 기준 하루 몫. constraints 가 비면 주 30시간으로 둔다. */
export function dailyCapacityMinutes(hoursPerWeek: number | undefined): number {
  const perWeek = hoursPerWeek && hoursPerWeek > 0 ? hoursPerWeek : 30;
  return Math.round((perWeek / 5) * 60);
}

export function todayISO(now: Date = new Date()): string {
  // toISOString 은 UTC 로 밀린다. 사용자가 말하는 "오늘"은 로컬 날짜다.
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function daysBetween(from: string, to: string): number {
  const ms = Date.parse(`${to}T00:00:00`) - Date.parse(`${from}T00:00:00`);
  return Math.round(ms / 86400000);
}

export interface WaitingItem {
  ticket: Ticket;
  blockers: Ticket[];
}

export interface TodayPlan {
  capacityMinutes: number;
  plannedMinutes: number;
  /** 마감이 지났고 지금 손댈 수 있는 것. 무조건 맨 위. */
  overdue: Ticket[];
  /** 하루 몫이 허락하는 만큼 채운 오늘의 할 일. */
  today: Ticket[];
  /** 손댈 수는 있지만 오늘 몫을 넘긴 것. */
  later: Ticket[];
  /** 스스로 막힌 것 (blocked). 사유가 있다. */
  blocked: Ticket[];
  /** 선행 티켓이 안 끝나 아직 시작할 수 없는 것. */
  waiting: WaitingItem[];
}

/**
 * 오늘 할 일을 고른다.
 *
 * 1. 끝난 것은 뺀다
 * 2. 막힌 것(blocked)은 따로 — 오늘 몫에 넣어봐야 못 한다
 * 3. 선행이 안 끝난 것도 따로 — 순서를 어기면 계획이 아니다
 * 4. 남은 것 중 마감 지난 것을 먼저, 그다음 마감 가까운 순
 * 5. 하루 몫(주당 가용시간 / 5)까지만 채우고 나머지는 접는다
 */
export function selectTodayFocus(
  view: ProjectView,
  today: string,
  visibleTicketIds: Set<string> | null = null,
): TodayPlan {
  const byId = new Map(view.tickets.map((t) => [t.id, t]));
  const blockersOf = new Map<string, Ticket[]>();
  for (const dep of view.ticket_dependencies) {
    const parent = byId.get(dep.depends_on);
    if (!parent || parent.status === "done") continue;
    const list = blockersOf.get(dep.ticket_id) ?? [];
    list.push(parent);
    blockersOf.set(dep.ticket_id, list);
  }

  const open = view.tickets
    .filter((t) => t.status !== "done")
    .filter((t) => !visibleTicketIds || visibleTicketIds.has(t.id));

  const blocked: Ticket[] = [];
  const waiting: WaitingItem[] = [];
  const actionable: Ticket[] = [];

  for (const t of open) {
    if (t.status === "blocked") {
      blocked.push(t);
      continue;
    }
    const blockers = blockersOf.get(t.id);
    if (blockers && blockers.length > 0) {
      waiting.push({ ticket: t, blockers });
      continue;
    }
    actionable.push(t);
  }

  const isOverdue = (t: Ticket) => t.due_date !== null && t.due_date < today;
  const dueKey = (t: Ticket) => t.due_date ?? "9999-12-31";
  const order = (a: Ticket, b: Ticket) =>
    dueKey(a).localeCompare(dueKey(b)) || a.order_index - b.order_index;

  const overdue = actionable.filter(isOverdue).sort(order);
  const upcoming = actionable.filter((t) => !isOverdue(t)).sort(order);

  const capacityMinutes = dailyCapacityMinutes(view.project.constraints?.hours_per_week);
  // 밀린 것은 몫을 넘겨도 다 보여준다. 오늘 새로 집는 것만 몫으로 제한한다.
  let used = overdue.reduce((sum, t) => sum + t.est_minutes, 0);
  const todayList: Ticket[] = [];
  const later: Ticket[] = [];
  for (const t of upcoming) {
    if (used + t.est_minutes <= capacityMinutes) {
      todayList.push(t);
      used += t.est_minutes;
    } else {
      later.push(t);
    }
  }

  return {
    capacityMinutes,
    plannedMinutes: used,
    overdue,
    today: todayList,
    later,
    blocked,
    waiting,
  };
}
