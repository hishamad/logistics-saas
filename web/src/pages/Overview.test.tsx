import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Network, OverviewData } from "../api";
import { fakeApi, ME, show } from "../test/setup";
import { Overview } from "./Overview";

const data: OverviewData = {
  operation: { name: "Test operation", version: 3, window: { start: "2026-10-18T03:00:00Z", end: "2026-10-20T03:00:00Z" }, trucks: 4, contract: 10, spot: 2, waiting: 5 },
  latest: null,
  running: null,
  attention: [{ kind: "unserved", count: 3 }, { kind: "expired", count: 1, refs: ["SO-9"] }, { kind: "plan_out_of_date" }],
};

// Two Riyadh sites (one city, labelled once with both cities' trucks) and Dammam.
const network: Network = {
  sites: [
    { id: "ry1", name: "Riyadh dry port", name_ar: "ميناء الرياض الجاف", city: "Riyadh", city_ar: "الرياض", lat: 24.7, lon: 46.8, trucks: 3 },
    { id: "ry2", name: "Riyadh 2nd Industrial City", name_ar: "المدينة الصناعية الثانية", city: "Riyadh", city_ar: "الرياض", lat: 24.55, lon: 46.9, trucks: 2 },
    { id: "dm", name: "Dammam port", name_ar: "ميناء الدمام", city: "Dammam", city_ar: "الدمام", lat: 26.5, lon: 50.2, trucks: 0 },
  ],
  lanes: [{ from: "ry1", to: "dm", loaded: true, trips: 2 }],
  roads: {},
};
const NETWORK = { "/api/network": { body: network } };

describe("overview", () => {
  it("lists what needs attention with a way to act on each", async () => {
    fakeApi({ "/api/me": ME("dispatcher"), "/api/overview": { body: data }, ...NETWORK });
    show(<Overview />);
    await waitFor(() => expect(screen.getByText("3 contract orders have no truck in the latest plan.")).toBeTruthy());
    expect(screen.getByText(/pickup time that already passed: SO-9/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to data" }).getAttribute("href")).toBe("/data");
    expect(screen.getByRole("link", { name: "Run a plan" }).getAttribute("href")).toBe("/board");
  });

  it("does not offer viewers actions they cannot take", async () => {
    fakeApi({ "/api/me": ME("viewer"), "/api/overview": { body: data }, ...NETWORK });
    show(<Overview />);
    await waitFor(() => expect(screen.getByText(/have no truck/)).toBeTruthy());
    await waitFor(() => expect(screen.getByRole("link", { name: "Open the board" })).toBeTruthy());
    expect(screen.queryByRole("link", { name: "Go to data" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Run a plan" })).toBeNull();
  });

  it("says all is clear when nothing needs attention", async () => {
    fakeApi({ "/api/me": ME(), "/api/overview": { body: { ...data, attention: [] } }, ...NETWORK });
    show(<Overview />, "ar");
    await waitFor(() => expect(screen.getByText(/كل شيء على ما يرام/)).toBeTruthy());
  });

  it("draws the network with each city labelled once", async () => {
    fakeApi({ "/api/me": ME(), "/api/overview": { body: data }, ...NETWORK });
    const { container } = show(<Overview />);
    await waitFor(() => expect(screen.getByRole("img", { name: /Map of the network/ })).toBeTruthy());
    const labels = [...container.querySelectorAll(".network-map text")].map((n) => n.textContent);
    expect(labels.filter((l) => l === "Riyadh")).toHaveLength(1);
    expect(labels).toContain("Dammam");
    expect(labels).toContain("5 trucks");
    expect(container.querySelectorAll(".network-map .lane")).toHaveLength(1);
  });

  it("labels the map in Arabic but keeps geography left to right", async () => {
    fakeApi({ "/api/me": ME(), "/api/overview": { body: data }, ...NETWORK });
    const { container } = show(<Overview />, "ar");
    await waitFor(() => expect(container.querySelector(".network-map")).toBeTruthy());
    expect(container.querySelector(".network-map")!.getAttribute("dir")).toBe("ltr");
    expect([...container.querySelectorAll(".network-map text")].map((n) => n.textContent)).toContain("الدمام");
  });

  it("follows the real road where the network has one, and zooms on request", async () => {
    const withRoad = { ...network, roads: { "ry1|dm": "_p~iF~ps|U_ulLnnqC_mqNvxq`@" } };
    fakeApi({ "/api/me": ME(), "/api/overview": { body: data }, "/api/network": { body: withRoad } });
    const { container } = show(<Overview />);
    await waitFor(() => expect(container.querySelector(".network-map .lane")).toBeTruthy());
    expect(container.querySelector(".network-map .lane")!.getAttribute("d")).toMatch(/^M[^Q]*L/);
    const svg = container.querySelector(".network-map svg")!;
    expect(svg.getAttribute("viewBox")).toBe("0 0 620 490");
    expect((screen.getByRole("button", { name: "Zoom out" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(svg.getAttribute("viewBox")).not.toBe("0 0 620 490");
    fireEvent.click(screen.getByRole("button", { name: "Show the whole country" }));
    expect(svg.getAttribute("viewBox")).toBe("0 0 620 490");
  });
});
