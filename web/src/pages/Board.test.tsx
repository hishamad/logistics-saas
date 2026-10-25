import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Board as BoardData, BoardActivity, PlanRun } from "../api";
import { fakeApi, ME, show } from "../test/setup";
import { Board } from "./Board";

const act = (kind: number, start: number, end: number, job: string | null, name: BoardActivity[8], from: string, to: string, km = 0): BoardActivity => [
  kind,
  start,
  end,
  job,
  from,
  to,
  km,
  [],
  name,
];
const stats = { jobs: 1, offers: 0, loaded_km: 400, empty_km: 20, revenue: 480000, driving_h: 5 };

const board: BoardData = {
  name: "test",
  valid: true,
  findings: [],
  released: [],
  origin: "2026-10-19T03:00:00Z",
  horizonEnd: 2880,
  end: 2880,
  sites: { port: ["Dammam port", "ميناء الدمام"], ind: ["Dammam industrial", "صناعية الدمام"], ruh: ["Riyadh dry port", "ميناء الرياض الجاف"] },
  geo: { port: [26.5, 50.2, "Dammam", "الدمام"], ind: [26.3, 50.1, "Dammam", "الدمام"], ruh: [24.7, 46.8, "Riyadh", "الرياض"] },
  jobs: {
    j1: { ref: "SA-1", customer: "Almarai", from: "port", to: "ruh", offer: false, revenue: 480000, tonnes: 20, equipment: "dry_van" },
    j2: { ref: "SA-2", customer: "Sabic", from: "ruh", to: "port", offer: false, revenue: 300000, tonnes: 18, equipment: "dry_van" },
  },
  teams: [
    { id: "idle", name: "DMM-001", depot: "ind", equipment: "dry_van", acts: [], blocks: [[600, 1200, "rule"]], stats: { ...stats, jobs: 0, revenue: 0 } },
    {
      id: "busy",
      name: "DMM-002",
      depot: "ind",
      equipment: "dry_van",
      blocks: [],
      acts: [
        act(1, 0, 30, null, "empty", "ind", "port", 20),
        act(2, 30, 90, "j1", "loading", "port", "port"),
        act(0, 90, 400, "j1", "loaded", "port", "ruh", 400),
        act(2, 400, 460, "j1", "unloading", "ruh", "ruh"),
      ],
      stats,
    },
  ],
  unserved: ["j2"],
  kpis: { confirmed: 2, served: 1, offered: 0, accepted: 0, loaded_km: 400, empty_km: 20, cost: 100000, revenue: 480000, trucks: 2, days: 2, runtime_s: 1 },
  emptyReasons: {},
  frozen: [],
  roads: {},
};

const run: PlanRun = {
  id: "r1",
  created_by: "Test User",
  status: "done",
  created_at: "2026-10-19T03:00:00Z",
  finished_at: "2026-10-19T03:00:30Z",
  settings: { seconds: 30, rounds: null, seed: 1, lookahead: true },
  summary: null,
  error: null,
};

function api(role: "dispatcher" | "viewer" = "dispatcher") {
  return fakeApi({
    "/api/me": ME(role),
    "/api/steering": { body: { locks: [] } },
    "/api/plans": { body: [run] },
    "/api/plans/r1/changes": { body: { changes: null, against: null } },
    "/api/plans/r1/board": { body: board },
    "/api/plans/r1/why/j1": { body: { facts: {}, text: "Cheapest truck that reaches the port in time.", source: "template" } },
    "/api/plans/r1/why/j2": { body: { facts: {}, text: "No truck can reach Riyadh in time.", source: "template" } },
  });
}

describe("plan board", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        disconnect() {}
      },
    );
  });

  it("shows the plan's numbers and opens on a truck that has work", async () => {
    api();
    show(<Board />);
    const numbers = await screen.findByRole("region", { name: "Plan numbers" });
    expect(within(numbers).getByText("1 / 2")).toBeTruthy();
    expect(screen.getByText(/Passed every independent check/)).toBeTruthy();
    const card = screen.getByRole("region", { name: "Selected truck" });
    expect(within(card).getByRole("heading", { name: "DMM-002" })).toBeTruthy();
    expect(within(card).getByText("Dammam industrial · 1 order")).toBeTruthy();
    expect(within(card).getByRole("img", { name: "This truck’s route" })).toBeTruthy();
  });

  it("explains an order in place, and a second click puts the answer away", async () => {
    api();
    show(<Board />);
    const card = await screen.findByRole("region", { name: "Selected truck" });
    fireEvent.click(within(card).getByRole("button", { name: /Why this truck/ }));
    await waitFor(() => expect(within(card).getByText("Cheapest truck that reaches the port in time.")).toBeTruthy());
    fireEvent.click(within(card).getByRole("button", { name: /Why this truck/ }));
    expect(within(card).queryByText("Cheapest truck that reaches the port in time.")).toBeNull();

    const unserved = screen.getByRole("region", { name: "Orders without a truck" });
    expect(within(unserved).getByText("1 contract order")).toBeTruthy();
    fireEvent.click(within(unserved).getByRole("button", { name: /Why/ }));
    await waitFor(() => expect(within(unserved).getByText("No truck can reach Riyadh in time.")).toBeTruthy());
  });

  it("marks idle trucks and the time a truck cannot work", async () => {
    api();
    show(<Board />);
    await screen.findByRole("region", { name: "Selected truck" });
    expect(screen.getByText("No work in this plan")).toBeTruthy();
    expect(document.querySelector(".tl-block")?.getAttribute("title")).toMatch(/^Unavailable/);
    fireEvent.click(screen.getByText("DMM-001"));
    expect(within(screen.getByRole("region", { name: "Selected truck" })).getByText("This truck has no work in this plan.")).toBeTruthy();
  });

  it("lets viewers read the plan but not change it", async () => {
    api("viewer");
    show(<Board />);
    const card = await screen.findByRole("region", { name: "Selected truck" });
    expect(screen.queryByRole("button", { name: "Plan again" })).toBeNull();
    expect(within(card).queryByRole("button", { name: /Freeze/ })).toBeNull();
    expect(within(card).queryByRole("button", { name: /What if/ })).toBeNull();
    expect(within(card).getByRole("button", { name: /Copy driver message/ })).toBeTruthy();
  });
});
