/** 백엔드 API 클라이언트. 타입은 backend/app/models/schemas.py 와 §4 스키마에 맞춘다. */

/** 태스크와 티켓이 같은 낱말을 쓴다.
 *  ⚠ 「막힘」은 여기 없다 — parked 는 접힘(의도적으로 미룸)이지 막힘이 아니다.
 *  막힌 티켓은 status 가 claimed 이고 blocked_reason 한 줄이 붙어 있다. */
export type WorkStatus = "open" | "claimed" | "resolved" | "parked";
export type TicketStatus = WorkStatus;
export type TaskStatus = WorkStatus;
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
  /** §1.5 도메인 프리셋 — 낱말만 갈린다. "software" | "general" */
  domain: string;
  /** §3.3 완성 청사진. 초안은 AI 가 쓰고 **확정은 사용자가 한다**. */
  blueprint: { summary?: string; criteria?: SuccessCriterion[]; confirmed?: boolean };
}

/** 「무엇이 되면 끝났다고 할 수 있나」 한 줄. 주(weekly_goal)가 covers 로 가리킨다. */
export interface SuccessCriterion {
  key: string;
  text: string;
}

/** 주 — 관리 단위이자 최상위. */
export interface WeeklyGoal {
  id: string;
  /** ⚠ 아직 주가 안 정해진 것은 null 이다. */
  week_index: number | null;
  title: string;
  target_date: string | null;
  /** 이 주가 끝내는 완성 기준 key 목록 (§3.3). */
  covers: string[];
}

/** 태스크 — 한 덩어리로 묶이는 티켓들의 집. 한 태스크는 한 주에만 산다. */
export interface Task {
  id: string;
  /** ⚠ 주가 안 정해졌으면 null. */
  weekly_goal_id: string | null;
  /** 프로젝트 안에서 전역으로 센다. 번호가 없으면 null. */
  task_number: number | null;
  title: string;
  description: string | null;
  status: TaskStatus;
}

export interface Ticket {
  id: string;
  /** ⚠ 태스크가 안 정해졌으면 null — 그러면 번호도 없다. */
  task_id: string | null;
  /** 태스크마다 1 부터 다시 센다. 티켓을 부르는 이름의 뒷자리다. */
  ticket_number: number | null;
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

/** 인터뷰 문답 하나 (SPEC §3.3). answer 가 비면 아직 답하지 않은 질문이다. */
export interface InterviewTurn {
  round: number;
  field: string;
  question: string;
  answer: string;
}

export interface ProjectView {
  project: Project;
  interview: InterviewTurn[];
  generation: {
    status: "running" | "awaiting_clarify" | "awaiting_blueprint" | "done" | "failed";
    questions: ClarifyQuestion[];
    repairs: string[];
    error: string | null;
  };
  weekly_goals: WeeklyGoal[];
  tasks: Task[];
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

// ─────────────────────────────────────────────────────────────
// 로그인
// ─────────────────────────────────────────────────────────────
export interface User {
  id: string;
  email: string;
  display_name: string | null;
  avatar_url: string | null;
}

export interface AuthConfig {
  google_enabled: boolean;
  /** 구글 버튼을 그리는 데 필요한 공개값. 꺼져 있으면 null. */
  google_client_id: string | null;
  /** 구글이 설정돼 있지 않을 때만 열리는 문. */
  demo_login: boolean;
}

export const authApi = {
  config: () => request<AuthConfig>("/auth/config"),
  /** 로그인 안 된 것은 오류가 아니라 답이다 — user 가 null 로 온다. */
  me: () => request<{ user: User | null }>("/auth/me"),
  google: (idToken: string) =>
    request<{ user: User }>("/auth/google", {
      method: "POST",
      body: JSON.stringify({ id_token: idToken }),
    }),
  demo: () => request<{ user: User }>("/auth/demo", { method: "POST" }),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),
};

/** 목록 화면 한 줄. 상세를 부르지 않고도 진행 정도가 보이게 숫자를 같이 받는다. */
export interface ProjectSummary {
  id: string;
  title: string;
  goal_text: string;
  status: string;
  start_date: string;
  /** §1.5 도메인 프리셋 — 낱말만 갈린다. "software" | "general" */
  domain: string;
  created_at: string;
  ticket_count: number;
  resolved_count: number;
}

export interface CreateProjectBody {
  goal_text: string;
  /** 첫 화면에서 고른 것. 이 값이 intake 의 추측을 이긴다. */
  domain?: string;
  duration_weeks?: number;
  hours_per_week?: number;
  level?: string;
  stack?: string[];
  team_size?: number;
}

export const api = {
  listProjects: () => request<{ projects: ProjectSummary[] }>("/projects"),

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

  /** 완성 기준과 도메인을 사용자가 확정한다 (§3.3, §1.5). */
  confirmBlueprint: (id: string, summary: string, criteria: string[], domain: string) =>
    request<{ project_id: string; status: string }>(`/projects/${id}/blueprint`, {
      method: "POST",
      body: JSON.stringify({ summary, criteria, domain }),
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
    onBlueprint: (
      draft: { summary?: string; criteria?: SuccessCriterion[] },
      domain: string | null,
    ) => void;
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
  source.addEventListener("blueprint", (e) => {
    const data = JSON.parse((e as MessageEvent).data);
    handlers.onBlueprint(data.blueprint ?? {}, data.domain ?? null);
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
  | "shift_week";

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
  scope_weekly_goal_id: string;
  scope_weekly_goal_title: string;
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
