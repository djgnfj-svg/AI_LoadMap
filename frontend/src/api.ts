/** 백엔드 API 클라이언트. 타입은 backend/app/models/schemas.py 와 §4 스키마에 맞춘다. */

export type TicketStatus = "todo" | "doing" | "done" | "blocked";
export type NodeStatus = "pending" | "in_progress" | "done" | "at_risk";

export interface Project {
  id: string;
  title: string;
  goal_text: string;
  constraints: {
    duration_weeks: number;
    hours_per_week: number;
    level: string;
    stack: string[];
    team_size: number;
  };
  status: string;
  start_date: string;
}

export interface Milestone {
  id: string;
  order_index: number;
  title: string;
  description: string | null;
  target_date: string | null;
  status: string;
}

export interface WeeklyGoal {
  id: string;
  milestone_id: string;
  week_index: number;
  title: string;
  target_date: string | null;
}

export interface Ticket {
  id: string;
  weekly_goal_id: string;
  order_index: number;
  title: string;
  body: string | null;
  est_minutes: number;
  status: TicketStatus;
  due_date: string | null;
  delay_count: number;
  blocked_reason: string | null;
  completed_at: string | null;
}

export interface ArchNodeRow {
  id: string;
  node_key: string;
  label: string;
  node_type: string | null;
  layer: string | null;
  position: { x: number; y: number } | null;
  status: NodeStatus;
  /** §4.4 뷰가 계산한 값. */
  computed_status: NodeStatus;
  progress: number | null;
  delayed_tickets: number;
  ticket_count: number;
}

export interface ArchEdgeRow {
  id: string;
  from_node: string;
  to_node: string;
  label: string | null;
}

export interface ClarifyQuestion {
  field: string;
  question: string;
}

export interface ProjectView {
  project: Project;
  generation: {
    status: "running" | "awaiting_clarify" | "done" | "failed";
    questions: ClarifyQuestion[];
    repairs: string[];
    error: string | null;
  };
  milestones: Milestone[];
  weekly_goals: WeeklyGoal[];
  tickets: Ticket[];
  ticket_dependencies: { ticket_id: string; depends_on: string }[];
  arch_nodes: ArchNodeRow[];
  arch_edges: ArchEdgeRow[];
  ticket_node_links: { ticket_id: string; node_id: string }[];
}

export interface TicketPatchResult {
  ticket: Pick<Ticket, "id" | "status" | "delay_count" | "due_date" | "blocked_reason">;
  node_changes: { node_id: string; node_key: string; status: NodeStatus }[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

export interface CreateProjectBody {
  goal_text: string;
  duration_weeks?: number;
  hours_per_week?: number;
  level?: string;
  stack?: string[];
  team_size?: number;
}

export const api = {
  createProject: (body: CreateProjectBody) =>
    request<{ project_id: string; status: string }>("/projects", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getProject: (id: string) => request<ProjectView>(`/projects/${id}`),

  submitClarify: (id: string, answers: Record<string, string>) =>
    request<{ project_id: string; status: string }>(`/projects/${id}/clarify`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),

  patchTicket: (
    id: string,
    action: "start" | "complete" | "block" | "unblock" | "defer",
    extra: { reason?: string; new_due_date?: string } = {},
  ) =>
    request<TicketPatchResult>(`/tickets/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ action, ...extra }),
    }),
};

/** 생성 그래프 진행 이벤트 (SPEC §3.5 SSE). */
export interface StepEvent {
  node: string;
  label: string;
  ok?: boolean;
  violations?: { code: string; message: string }[];
  repairs?: string[];
  counts?: Record<string, number>;
}

export function streamGeneration(
  projectId: string,
  handlers: {
    onStep: (e: StepEvent) => void;
    onClarify: (questions: ClarifyQuestion[]) => void;
    onDone: (repairs: string[]) => void;
    onError: (message: string) => void;
  },
): () => void {
  const source = new EventSource(`/projects/${projectId}/stream`);
  const close = () => source.close();

  source.addEventListener("step", (e) => handlers.onStep(JSON.parse((e as MessageEvent).data)));
  source.addEventListener("clarify", (e) => {
    handlers.onClarify(JSON.parse((e as MessageEvent).data).questions);
    close();
  });
  source.addEventListener("done", (e) => {
    handlers.onDone(JSON.parse((e as MessageEvent).data).repairs ?? []);
    close();
  });
  source.addEventListener("error", (e) => {
    const data = (e as MessageEvent).data;
    if (data) handlers.onError(JSON.parse(data).message);
    close();
  });

  return close;
}

// ─────────────────────────────────────────────────────────────
// 알람 (SPEC §2.3, §3.5)
// ─────────────────────────────────────────────────────────────
export type AlertRule =
  | "due_24h"
  | "deferred_twice"
  | "node_at_risk"
  | "weekly_low"
  | "inactive_3d";

export interface Alert {
  id: string;
  rule: AlertRule;
  severity: "low" | "medium" | "high";
  message: string;
  acknowledged: boolean;
  created_at: string;
  ticket_id: string | null;
  ticket_title: string | null;
  node_id: string | null;
  node_label: string | null;
  review_day_id: string | null;
  review_date: string | null;
  review_status: string | null;
}

export interface ReviewDay {
  id: string;
  node_id: string | null;
  node_label: string | null;
  node_key: string | null;
  scheduled_date: string;
  trigger_reason: string | null;
  status: string;
  postponed_count: number;
}

// ─────────────────────────────────────────────────────────────
// 재점검 세션 (SPEC §2.4, §3.4)
// ─────────────────────────────────────────────────────────────
export interface ReplanSignals {
  node_key: string;
  node_label: string;
  total_tickets: number;
  done_tickets: number;
  delayed_tickets: number;
  missed_count: number;
  deferred_count: number;
  avg_delay_days: number;
  blocked_reasons: string[];
}

export type ChangeType =
  | "split_ticket"
  | "add_ticket"
  | "reduce_ticket"
  | "drop_ticket"
  | "add_dependency"
  | "shift_milestone";

export interface ReplanChange {
  id: string;
  type: ChangeType;
  label: string;
  reason: string;
  before: string | null;
  after: string | null;
}

export interface ReplanDiff {
  signals: ReplanSignals;
  diagnosis: string;
  rationale: string;
  scope_milestone_id: string;
  scope_milestone_title: string;
  changes: ReplanChange[];
  residual_violations: { code: string; message: string }[];
  repairs: string[];
}

export interface ReviewView {
  review_day: ReviewDay & { project_id: string };
  signals: ReplanSignals;
  session: { id: string; diagnosis: string; applied: boolean; diff: ReplanDiff } | null;
}

export const alertsApi = {
  list: (projectId: string) =>
    request<{ alerts: Alert[]; review_days: ReviewDay[] }>(`/projects/${projectId}/alerts`),
  ack: (alertId: string) =>
    request<{ id: string }>(`/alerts/${alertId}/ack`, { method: "POST" }),
  /** 스케줄러 작업을 즉시 한 번 돌린다 (데모·개발용). */
  detect: (projectId: string) =>
    request<{
      missed_events: number;
      review_days_created: number;
      alerts_created: number;
    }>(`/projects/${projectId}/detect`, { method: "POST", body: JSON.stringify({}) }),
};

export const reviewsApi = {
  get: (reviewDayId: string) => request<ReviewView>(`/reviews/${reviewDayId}`),
  run: (reviewDayId: string) =>
    request<{ session_id: string; diff: ReplanDiff }>(`/reviews/${reviewDayId}/run`, {
      method: "POST",
    }),
  apply: (reviewDayId: string, approved: string[]) =>
    request<{ approved: string[]; rejected: string[]; applied: string[] }>(
      `/reviews/${reviewDayId}/apply`,
      { method: "POST", body: JSON.stringify({ approved }) },
    ),
  postpone: (reviewDayId: string, scheduledDate: string) =>
    request<{ scheduled_date: string; postponed_count: number }>(`/reviews/${reviewDayId}`, {
      method: "PATCH",
      body: JSON.stringify({ scheduled_date: scheduledDate }),
    }),
};
