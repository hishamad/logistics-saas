import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { OverviewData } from "../api";
import { fakeApi, ME, show } from "../test/setup";
import { Overview } from "./Overview";

const data: OverviewData = {
  operation: { name: "Test operation", version: 3, window: { start: "2026-10-18T03:00:00Z", end: "2026-10-20T03:00:00Z" }, trucks: 4, contract: 10, spot: 2, waiting: 5 },
  latest: null,
  running: null,
  attention: [{ kind: "unserved", count: 3 }, { kind: "expired", count: 1, refs: ["SO-9"] }, { kind: "plan_out_of_date" }],
};

describe("overview", () => {
  it("lists what needs attention with a way to act on each", async () => {
    fakeApi({ "/api/me": ME("dispatcher"), "/api/overview": { body: data } });
    show(<Overview />);
    await waitFor(() => expect(screen.getByText("3 contract orders have no truck in the latest plan.")).toBeTruthy());
    expect(screen.getByText(/pickup time that already passed: SO-9/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to data" }).getAttribute("href")).toBe("/data");
    expect(screen.getByRole("link", { name: "Run a plan" }).getAttribute("href")).toBe("/board");
  });

  it("does not offer viewers actions they cannot take", async () => {
    fakeApi({ "/api/me": ME("viewer"), "/api/overview": { body: data } });
    show(<Overview />);
    await waitFor(() => expect(screen.getByText(/have no truck/)).toBeTruthy());
    await waitFor(() => expect(screen.getByRole("link", { name: "Open the board" })).toBeTruthy());
    expect(screen.queryByRole("link", { name: "Go to data" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Run a plan" })).toBeNull();
  });

  it("says all is clear when nothing needs attention", async () => {
    fakeApi({ "/api/me": ME(), "/api/overview": { body: { ...data, attention: [] } } });
    show(<Overview />, "ar");
    await waitFor(() => expect(screen.getByText(/كل شيء على ما يرام/)).toBeTruthy());
  });
});
