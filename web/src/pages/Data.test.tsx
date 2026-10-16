import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { DataOverview, UploadResult } from "../api";
import { fakeApi, ME, show } from "../test/setup";
import { Data } from "./Data";

const overview: DataOverview = {
  version: 7,
  updated_at: "2026-10-18T03:00:00Z",
  window: { start: "2026-10-18T03:00:00Z", end: "2026-10-20T03:00:00Z" },
  jobs: { contract: 10, spot: 2, later: 4, expired: 0, customers: 3 },
  fleet: { trucks: 5, depots: { a: 5 }, dry_van: 4, flatbed: 1 },
  sites: [{ id: "a", name: "Riyadh", name_ar: "الرياض" }],
  locks: 0,
  rules: 0,
};

const problems: UploadResult = {
  applied: false,
  file_error: null,
  problems: [
    { row: 2, column: "pickup_site", code: "unknown_site", value: "Atlantis", detail: "" },
    { row: 3, column: "reference", code: "duplicate", value: "SO-1", detail: "2" },
  ],
  problem_count: 2,
  summary: {},
  version: 7,
};

describe("data page", () => {
  it("shows every problem in an uploaded file in Arabic and offers nothing to apply", async () => {
    const calls = fakeApi({ "/api/me": ME(), "/api/data": { body: overview }, "/api/data/jobs": { body: problems } });
    show(<Data />, "ar");
    await waitFor(() => expect(document.querySelector('input[type="file"]')).not.toBeNull());
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "orders.csv")] } });
    await waitFor(() => expect(screen.getByText("موقع غير معروف")).toBeTruthy());
    expect(screen.getByText("مكرر (موجود أيضاً في الصف 2)")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "تطبيق" })).toBeNull();
    const upload = calls.find((c) => c.path === "/api/data/jobs");
    expect(upload?.init?.body).toBeInstanceOf(FormData);
  });

  it("tells how many orders wait for a later plan, and viewers cannot upload", async () => {
    fakeApi({ "/api/me": ME("viewer"), "/api/data": { body: overview } });
    show(<Data />);
    await waitFor(() => expect(screen.getByText(/4 orders start after this window/)).toBeTruthy());
    expect(document.querySelector('input[type="file"]')).toBeNull();
  });
});
