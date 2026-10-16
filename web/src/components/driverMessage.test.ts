import { describe, expect, it } from "vitest";
import type { Board, BoardActivity, BoardTeam } from "../api";
import { driverMessage } from "./driverMessage";

const act = (kind: number, start: number, job: string | null, name: BoardActivity[8], from = "a", to = "a"): BoardActivity => [kind, start, start + 30, job, from, to, 0, [], name];

const team: BoardTeam = {
  id: "t1",
  name: "Truck 1",
  depot: "a",
  equipment: "dry_van",
  acts: [
    act(1, 0, null, "empty", "a", "b"),
    act(2, 60, "j1", "loading", "b", "b"),
    act(0, 90, "j1", "loaded", "b", "c"),
    act(2, 300, "j1", "unloading", "c", "c"),
    act(2, 400, "j2", "loading", "c", "c"),
    act(2, 600, "j2", "unloading", "a", "a"),
  ],
  stats: { jobs: 2, offers: 0, loaded_km: 0, empty_km: 0, revenue: 0, driving_h: 0 },
};

const board = {
  jobs: {
    j1: { ref: "SO-1", customer: "Acme", from: "b", to: "c", offer: false, revenue: 1, tonnes: 1, equipment: "dry_van" },
    j2: { ref: "SO-2", customer: "Beta", from: "c", to: "a", offer: false, revenue: 1, tonnes: 1, equipment: "dry_van" },
  },
} as unknown as Board;

const words = { header: "Truck 1: your plan", load: "Load", unload: "Unload", none: "No jobs." };
const site = (id: string) => ({ a: "Riyadh", b: "Dammam", c: "Jeddah" })[id] ?? id;

describe("driver message", () => {
  it("lists each job once, in order, with where and when to load and unload", () => {
    const text = driverMessage(board, team, words, (m) => `m${m}`, site);
    expect(text).toBe(
      ["Truck 1: your plan", "", "1. SO-1 · Acme", "   Load: m60 – Dammam", "   Unload: m300 – Jeddah", "", "2. SO-2 · Beta", "   Load: m400 – Jeddah", "   Unload: m600 – Riyadh"].join("\n"),
    );
  });

  it("says so when the truck has no jobs", () => {
    const idle = { ...team, acts: [act(4, 0, null, "rest")] };
    expect(driverMessage(board, idle, words, String, site)).toBe("Truck 1: your plan\nNo jobs.");
  });
});
