import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Board, BoardActivity, BoardTeam } from "../api";
import { I18nProvider } from "../i18n";
import { RouteMap } from "./RouteMap";

const drive = (kind: "loaded" | "empty", from: string, to: string): BoardActivity => [kind === "loaded" ? 0 : 1, 0, 60, null, from, to, 100, [], kind];
const team = (acts: BoardActivity[]): BoardTeam => ({
  id: "t",
  name: "T",
  depot: "ind",
  equipment: "dry_van",
  acts,
  blocks: [],
  stats: { jobs: 1, offers: 0, loaded_km: 0, empty_km: 0, revenue: 0, driving_h: 0 },
});
const board = {
  geo: { port: [26.5, 50.2, "Dammam", "الدمام"], ind: [26.3, 50.1, "Dammam", "الدمام"], ruh: [24.7, 46.8, "Riyadh", "الرياض"] },
} as unknown as Board;

function draw(acts: BoardActivity[], language: "en" | "ar" = "en") {
  localStorage.setItem("lang", language);
  return render(
    <I18nProvider>
      <RouteMap board={board} team={team(acts)} />
    </I18nProvider>,
  ).container;
}

describe("route map", () => {
  it("numbers each city once and skips the hop inside a city", () => {
    const map = draw([drive("empty", "ind", "port"), drive("loaded", "port", "ruh"), drive("empty", "ruh", "ind")]);
    const names = [...map.querySelectorAll("text")].map((n) => n.textContent);
    expect(names).toEqual(["1", "Dammam", "2", "Riyadh"]);
    expect(map.querySelectorAll(".route-leg")).toHaveLength(2); // Dammam → Riyadh loaded, back empty
    expect(map.querySelectorAll(".route-leg.empty")).toHaveLength(1);
  });

  it("names cities in Arabic but never mirrors the map", () => {
    const map = draw([drive("loaded", "port", "ruh")], "ar");
    expect(map.querySelector(".route-map")!.getAttribute("dir")).toBe("ltr");
    expect([...map.querySelectorAll("text")].map((n) => n.textContent)).toContain("الرياض");
  });

  it("draws nothing when a site has no map position", () => {
    expect(draw([drive("loaded", "port", "nowhere")]).querySelector("svg")).toBeNull();
  });
});
