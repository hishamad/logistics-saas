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
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
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
