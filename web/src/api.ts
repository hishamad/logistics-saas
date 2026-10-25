// Thin client for the freight API. Same-origin: the session lives in an HttpOnly cookie.

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-Requested-With"] = "freight"; // the API's CSRF guard
  const form = body instanceof FormData;
  if (body !== undefined && !form) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // not JSON; keep the status text
    }
    throw new ApiError(response.status, typeof detail === "string" ? detail : response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  del: <T>(path: string) => request<T>("DELETE", path),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  upload: <T>(path: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<T>("POST", path, form);
  },
};

export type Role = "admin" | "dispatcher" | "viewer";

export type Me = {
  user: { name: string; email: string; role: Role };
  company: { name: string };
};

export type Operation = {
  name: string;
  version: number;
  updated_at: string;
  horizon: { start: string; end: string };
  trucks: number;
  sites: number;
  jobs_confirmed: number;
  jobs_offered: number;
  driving_rules: boolean;
};

export type PlanSummary = {
  valid: boolean;
  findings: string[];
  confirmed: number;
  served: number;
  offered: number;
  offers_taken: number;
  empty_share: number | null;
  cost_minor: number | null;
  revenue_minor: number | null;
  runtime_s: number;
  changed: number | null;
};

export type PlanRun = {
  id: string;
  created_by: string | null;
  status: "queued" | "running" | "done" | "failed";
  created_at: string;
  finished_at: string | null;
  settings: { seconds: number; rounds: number | null; seed: number; lookahead: boolean };
  summary: PlanSummary | null;
  error: string | null;
};

// Board data, as produced by freight.board.board_data on the server.
// An activity: [kind index, start minute, end minute, job id, from site, to site, km,
//               pauses [[break|rest, start, end]], kind name]
export type BoardActivity = [
  number,
  number,
  number,
  string | null,
  string,
  string,
  number,
  ["break" | "rest", number, number][],
  "loaded" | "empty" | "loading" | "unloading" | "turnaround" | "waiting" | "rest",
];

export type BoardTeam = {
  id: string;
  name: string;
  depot: string;
  equipment: string;
  acts: BoardActivity[];
  // When the truck cannot work: [start minute, end minute, from a rule or its calendar]
  blocks: [number, number, "rule" | "calendar"][];
  stats: { jobs: number; offers: number; loaded_km: number; empty_km: number; revenue: number; driving_h: number };
};

export type BoardJob = {
  ref: string;
  customer: string;
  from: string;
  to: string;
  offer: boolean;
  revenue: number | null;
  tonnes: number;
  equipment: string;
};

export type Board = {
  name: string;
  valid: boolean;
  findings: string[];
  released: string[];
  origin: string;
  horizonEnd: number;
  end: number;
  sites: Record<string, [string, string]>;
  jobs: Record<string, BoardJob>;
  teams: BoardTeam[];
  unserved: string[];
  kpis: {
    confirmed: number;
    served: number;
    offered: number;
    accepted: number;
    loaded_km: number;
    empty_km: number;
    cost: number | null;
    revenue: number | null;
    trucks: number;
    days: number;
    runtime_s: number;
  };
  emptyReasons: Record<string, number>;
  frozen: string[];
  geo: Record<string, [number, number, string, string]>; // latitude, longitude, city, city in Arabic
};

export type SheetKind = "jobs" | "fleet";

export type DataOverview = {
  version: number;
  updated_at: string;
  window: { start: string; end: string };
  jobs: { contract: number; spot: number; later: number; expired: number; customers: number };
  fleet: { trucks: number; depots: Record<string, number>; dry_van: number; flatbed: number };
  sites: { id: string; name: string; name_ar: string }[];
  locks: number;
  rules: number;
};

export type SheetProblem = { row: number; column: string; code: string; value: string; detail: string };

export type UploadResult = {
  applied: boolean;
  file_error: string | null;
  detail?: string;
  problems: SheetProblem[];
  problem_count?: number;
  summary: Record<string, number>;
  version?: number;
};

export type RuleKind = "resource_unavailable" | "required_end" | "customer_eligibility" | "preferred_assignment";

export type Rule = {
  id: string;
  kind: RuleKind;
  resource_id: string | null;
  team_id: string | null;
  job_id: string | null;
  site_id: string | null;
  customer: string | null;
  window: { start: string; end: string } | null;
  strength: "hard" | "soft";
  penalty_minor: number;
  source_text: string;
};

export type Lock = { job_id: string; team_id: string; pickup_at: string | null };

export type Steering = {
  version: number;
  horizon: { start: string; end: string };
  rules: Rule[];
  locks: Lock[];
  latest_plan: string | null;
  teams: { id: string; name: string; depot: string; tractor_id: string; equipment: string }[];
  jobs: { id: string; reference: string; customer: string; state: string }[];
  sites: { id: string; name: string; name_ar: string }[];
  customers: string[];
  ai: boolean;
};

export type Interpretation = {
  status: "proposed" | "clarification" | "unsupported" | "error";
  explanation: string;
  question?: string | null;
  rule: Rule | null;
};

export type WhyFacts = {
  job: { reference: string; customer: string; pickup_window_riyadh: string; price_sar: number | null; kind: string };
  assigned?: { truck: string; extra_cost_sar: number; empty_km_to_pickup?: number; pickup_riyadh: string };
  alternatives: { truck: string; extra_cost_sar: number; more_than_chosen_sar?: number }[];
  other_trucks_that_could_take_it: number;
  trucks_that_cannot_take_it: Record<string, number>;
};

export type WhyAnswer = { facts: WhyFacts; text: string; source: string };

export type WhatIfNumbers = {
  contract_jobs_served: number;
  offers_taken: number;
  cost_sar: number | null;
  contribution_sar: number | null;
  empty_km: number | null;
};

export type WhatIfFacts = {
  method: "repair" | "replan";
  before: WhatIfNumbers;
  after: WhatIfNumbers;
  difference: Partial<WhatIfNumbers>;
  new_plan_valid: boolean;
  jobs_moved_count: number;
  jobs_no_longer_served: string[];
  jobs_newly_served: string[];
  trucks_whose_plan_changes: number;
};

export type WhatIfChange =
  | { kind: "drop"; job: string }
  | { kind: "assign"; job: string; team: string }
  | { kind: "unavailable"; team: string; start: string; end: string };

export type WhatIfRun = {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  created_at: string;
  change: WhatIfChange;
  result: { facts: WhatIfFacts | null; impossible?: boolean; text: { en: string; ar: string }; source: string } | null;
  error: string | null;
};

export type ChangedJob = { job: string; ref: string; customer: string };

export type Changes = {
  moved: (ChangedJob & { from: string; to: string })[];
  retimed: (ChangedJob & { truck: string; before: string; after: string })[];
  added: (ChangedJob & { truck: string })[];
  dropped: (ChangedJob & { truck: string })[];
  unchanged: number;
  notify: { truck: string; changes: number }[];
};

export type ChangesAnswer = { against: { id: string; created_at: string } | null; changes: Changes | null };

export type RollPreview = {
  run_id: string;
  start: string;
  jobs: { job: string; ref: string; customer: string; truck: string; pickup_at: string }[];
};

export type RollReport = {
  executed: number;
  not_done: string[];
  in_progress: string[];
  missed: { job: string; ref: string; customer: string }[];
  kept: number;
  trucks_moved: number;
  drivers_with_hours: number;
  window: { start: string; end: string };
};

export type UserRow = { id: string; email: string; name: string; role: Role; active: boolean; created_at: string };

export type AuditRow = { at: string; by: string | null; action: string; detail: Record<string, unknown> };

export type Attention =
  | { kind: "no_plan" | "plan_out_of_date" }
  | { kind: "plan_invalid"; findings: string[] }
  | { kind: "unserved"; count: number; refs?: string[] }
  | { kind: "notify"; count: number }
  | { kind: "released"; refs: string[] }
  | { kind: "idle_trucks"; count: number; names: string[] }
  | { kind: "expired"; count: number; refs: string[] }
  | { kind: "window_behind"; start: string };

export type OverviewData = {
  operation: { name: string; version: number; window: { start: string; end: string }; trucks: number; contract: number; spot: number; waiting: number };
  latest: PlanRun | null;
  running: PlanRun | null;
  attention: Attention[];
};

export type Network = {
  sites: { id: string; name: string; name_ar: string; city: string; city_ar: string; lat: number; lon: number; trucks: number }[];
  lanes: { from: string; to: string; loaded: boolean; trips: number }[];
};
