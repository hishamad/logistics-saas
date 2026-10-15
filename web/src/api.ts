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
  upload: <T>(path: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<T>("POST", path, form);
  },
};

export type Me = {
  user: { name: string; email: string; role: "dispatcher" | "viewer" };
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
};

export type PlanRun = {
  id: string;
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
};

export type SheetKind = "jobs" | "fleet";

export type DataOverview = {
  version: number;
  updated_at: string;
  window: { start: string; end: string };
  jobs: { contract: number; spot: number; outside_window: number; customers: number };
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
