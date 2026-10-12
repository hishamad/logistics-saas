import type { components } from "./api-schema";

export type Workspace = components["schemas"]["WorkspaceView"];
export type Snapshot = components["schemas"]["Snapshot"];
export type Plan = components["schemas"]["PlanView"];
export type Run = components["schemas"]["RunView"];
export type Rule = components["schemas"]["Rule"];
export type Job = components["schemas"]["Job"];
export type ImportRow = {
  line: number;
  status: string;
  external_id?: string;
  errors: string[];
  data: Record<string, unknown> | null;
  previous?: Record<string, unknown>;
};
export type ImportBatch = Omit<components["schemas"]["ImportView"], "rows"> & {
  rows: ImportRow[];
};
export type Proposal = {
  id: string;
  base_version: number;
  status: string;
  explanation: string;
  question: string | null;
  rule: Rule | null;
  model?: string;
  latency_ms?: number;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public attemptComplete = false,
  ) {
    super(message);
  }
}

export function apiBase() {
  // One browser origin in both environments; API credentials never cross ports.
  return "";
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(apiBase() + path, {
    ...options,
    credentials: "include",
    cache: "no-store",
    signal: options.signal ?? AbortSignal.timeout(35000),
    headers: {
      "Content-Type": "application/json",
      "X-Freight-Request": "1",
      ...options.headers,
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map(
                (v: { loc: string[]; msg: string }) =>
                  `${v.loc.join(".")}: ${v.msg}`,
              )
              .join(" · ")
          : "The server could not complete this request.";
    throw new ApiError(
      response.status,
      message,
      response.headers.get("X-Freight-Attempt") === "complete",
    );
  }
  return payload as T;
}

export const send = <T>(path: string, body: unknown, method = "POST") =>
  api<T>(path, { method, body: JSON.stringify(body) });

export function localInput(iso: string) {
  return new Date(new Date(iso).getTime() + 3 * 3600000)
    .toISOString()
    .slice(0, 16);
}
export const riyadhISO = (local: string) => local + ":00+03:00";
