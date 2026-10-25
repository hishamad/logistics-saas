import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Interpretation, Rule } from "../api";
import { useAuth } from "../auth";
import { fakeApi, ME, show } from "../test/setup";
import { AskBar } from "./AskBar";

const rule: Rule = {
  id: "",
  kind: "resource_unavailable",
  resource_id: "t1",
  team_id: null,
  job_id: null,
  site_id: null,
  customer: null,
  window: { start: "2026-10-19T03:00:00Z", end: "2026-10-19T11:00:00Z" },
  strength: "hard",
  penalty_minor: 0,
  source_text: "DMM-034 is in the workshop",
};

const steering = {
  ai: true,
  jobs: [{ id: "j1", reference: "SA-26255", customer: "Almarai", state: "confirmed" }],
  teams: [{ id: "team1", name: "DMM-034", depot: "dmm", tractor_id: "t1", equipment: "dry_van" }],
  sites: [],
};

// The app shows pages only once it knows who is signed in; so do these tests.
function Signed({ runId, suggestions = [] }: { runId: string; suggestions?: string[] }) {
  const { me } = useAuth();
  return me ? <AskBar runId={runId} suggestions={suggestions} /> : null;
}

function ask(text: string) {
  fireEvent.change(screen.getByLabelText("Ask Madar", { selector: "input" }), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

describe("ask Madar", () => {
  it("answers why an order is or is not planned with the plan's own explanation", async () => {
    const calls = fakeApi({
      "/api/me": ME(),
      "/api/steering": { body: steering },
      "/api/plans/run1/why/j1": { body: { facts: {}, text: "No truck was free in time.", source: "facts" } },
    });
    show(<Signed runId="run1" />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeTruthy());
    ask("why is sa-26255 not planned?");
    await waitFor(() => expect(screen.getByText("No truck was free in time.")).toBeTruthy());
    expect(screen.getByText("Why SA-26255")).toBeTruthy();
    expect(calls.some((c) => c.path === "/api/rules/interpret")).toBe(false);
  });

  it("proposes a rule and adds it only when the dispatcher says so", async () => {
    const reply: Interpretation = { status: "proposed", explanation: "DMM-034 unavailable until 14:00.", rule };
    const calls = fakeApi({
      "/api/me": ME("dispatcher"),
      "/api/steering": { body: steering },
      "/api/rules/interpret": { body: reply },
      "/api/rules": { body: rule },
    });
    show(<Signed runId="run1" suggestions={["DMM-034 is in the workshop tomorrow until 14:00"]} />);
    await waitFor(() => expect(screen.getByRole("button", { name: /workshop/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /workshop/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add this rule" })).toBeTruthy());
    // The exact rule, from the rule itself rather than the model's wording.
    expect(screen.getByText("DMM-034 unavailable 19 Oct 2026, 06:00 – 19 Oct 2026, 14:00")).toBeTruthy();
    expect(calls.some((c) => c.path === "/api/rules")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Add this rule" }));
    await waitFor(() => expect(screen.getByText(/Rule added/)).toBeTruthy());
    const added = calls.find((c) => c.path === "/api/rules")!;
    expect(JSON.parse(String(added.init!.body))).not.toHaveProperty("id");
  });

  it("does not offer viewers rules", async () => {
    const calls = fakeApi({ "/api/me": ME("viewer"), "/api/steering": { body: steering } });
    show(<Signed runId="run1" />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeTruthy());
    ask("Truck 4 is off tomorrow");
    await waitFor(() => expect(screen.getByText(/Rules are for dispatchers/)).toBeTruthy());
    expect(calls.some((c) => c.path === "/api/rules/interpret")).toBe(false);
  });

  it("says so when the AI is switched off instead of failing", async () => {
    const calls = fakeApi({ "/api/me": ME("dispatcher"), "/api/steering": { body: { ...steering, ai: false } } });
    show(<Signed runId="run1" />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeTruthy());
    ask("Truck 4 is off tomorrow");
    await waitFor(() => expect(screen.getByRole("status").textContent).toMatch(/not set up/));
    expect(calls.some((c) => c.path === "/api/rules/interpret")).toBe(false);
  });
});
