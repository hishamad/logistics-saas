import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Board, BoardActivity } from "../api";
import { I18nProvider } from "../i18n";
import { Timeline } from "./Timeline";

const act = (kind: number, start: number, end: number, job: string | null, name: BoardActivity[8]): BoardActivity => [kind, start, end, job, "a", "b", 10, [], name];

const team = (id: string, name: string, depot: string, acts: BoardActivity[]) => ({
  id,
  name,
  depot,
  equipment: "dry_van",
  acts,
  blocks: [],
  stats: { jobs: acts.filter((a) => a[3]).length, offers: 0, loaded_km: 10, empty_km: 5, revenue: 1000, driving_h: 2 },
});

const board: Board = {
  name: "test",
  valid: true,
  findings: [],
  released: [],
  origin: "2026-10-18T03:00:00Z",
  horizonEnd: 2880,
  end: 2880,
  sites: { a: ["Riyadh", "الرياض"], b: ["Jeddah", "جدة"] },
  jobs: { j1: { ref: "SO-1", customer: "Acme", from: "a", to: "b", offer: false, revenue: 100000, tonnes: 20, equipment: "dry_van" } },
  teams: [team("t1", "Truck 1", "a", [act(0, 60, 300, "j1", "loaded")]), team("t2", "Truck 2", "b", [act(1, 0, 120, null, "empty")]), team("t3", "Truck 3", "b", [])],
  unserved: [],
  kpis: { confirmed: 1, served: 1, offered: 0, accepted: 0, loaded_km: 10, empty_km: 5, cost: 100, revenue: 1000, trucks: 3, days: 2, runtime_s: 1 },
  emptyReasons: {},
  frozen: ["j1"],
  geo: {},
};

function show(language: "en" | "ar", onSelect = vi.fn()) {
  localStorage.setItem("lang", language);
  render(
    <I18nProvider>
      <Timeline board={board} selected={null} onSelect={onSelect} />
    </I18nProvider>,
  );
  return onSelect;
}

describe("truck timeline", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        disconnect() {}
      },
    );
  });

  it("shows a row per truck, grouped by depot, and selects a truck on click", () => {
    const onSelect = show("en");
    expect(screen.getAllByText(/^Truck \d$/)).toHaveLength(3);
    expect(document.querySelectorAll(".tl-group")).toHaveLength(2); // Riyadh, Jeddah
    fireEvent.click(screen.getByText("Truck 2"));
    expect(onSelect).toHaveBeenCalledWith("t2");
  });

  it("searches by customer and job reference", () => {
    show("en");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "acme" } });
    expect(screen.getAllByText(/^Truck \d$/).map((e) => e.textContent)).toEqual(["Truck 1"]);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "nothing-like-this" } });
    expect(screen.getByText("No trucks match these filters.")).toBeTruthy();
  });

  it("places bars from the inline start, so Arabic runs right to left, and marks frozen jobs", () => {
    show("ar");
    const bar = document.querySelector(".tl-seg.k-loaded") as HTMLElement;
    expect(bar.style.insetInlineStart).not.toBe("");
    expect(bar.style.left).toBe("");
    expect(bar.classList.contains("frozen")).toBe(true);
    expect(document.querySelector(".tl-group")?.textContent).toBe("الرياض");
  });
});

describe("counting in both languages", () => {
  it("uses every plural form Arabic has", async () => {
    const { renderHook } = await import("@testing-library/react");
    const { useI18n } = await import("../i18n");
    localStorage.setItem("lang", "ar");
    const { result } = renderHook(() => useI18n(), { wrapper: I18nProvider });
    expect([1, 2, 5, 11, 100].map((n) => result.current.count("orders", n))).toEqual(["طلب واحد", "طلبان", "5 طلبات", "11 طلباً", "100 طلب"]);
    localStorage.setItem("lang", "en");
    const english = renderHook(() => useI18n(), { wrapper: I18nProvider }).result.current;
    expect([1, 3].map((n) => english.count("trucks", n))).toEqual(["1 truck", "3 trucks"]);
  });
});
