import { expect, test } from "@playwright/test";

test("production sign-in exposes organizational SSO only", async ({ page }) => {
  await page.route("**/api/auth/config", (route) =>
    route.fulfill({
      json: { mode: "production", login_url: "/api/auth/login" },
    }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("link", { name: "Sign in with your organization" }),
  ).toHaveAttribute("href", "/api/auth/login");
  await expect(
    page.getByRole("button", { name: /Eastern Freight|Western Freight/ }),
  ).toHaveCount(0);
});

test("an ambiguous server failure preserves AI request identity", async ({
  page,
}) => {
  await page.route("**/api/workspace", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: { ...(await response.json()), ai_configured: true },
    });
  });
  const keys: string[] = [];
  await page.route("**/api/rule-proposals", async (route) => {
    keys.push(route.request().postDataJSON().idempotency_key);
    await route.fulfill({
      status: 503,
      json: { detail: "Temporary database failure; retry the same request." },
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /Western Freight/ }).click();
  await expect(
    page.getByRole("button", { name: "Optimize plan", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("textbox", { name: "Dispatcher instruction" })
    .fill("Assign SFD-1041 to Team 02");
  const interpret = page.getByRole("button", { name: "Interpret instruction" });
  await interpret.click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Temporary database failure" }),
  ).toBeVisible();
  await expect(interpret).toBeEnabled();
  await interpret.click();
  await expect.poll(() => keys.length).toBe(2);
  expect(keys[0]).toBe(keys[1]);
});

test("a failed poll recovers and double clicks create only one run", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Western Freight/ }).click();
  await expect(
    page.getByRole("button", { name: "Optimize plan", exact: true }),
  ).toBeEnabled();
  let submissions = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/runs"
    )
      submissions++;
  });
  let failed = false;
  await page.route(/\/api\/runs\/[^/?]+$/, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (!failed && body.state === "succeeded") {
      failed = true;
      await route.fulfill({
        status: 503,
        json: { detail: "Injected temporary poll failure" },
      });
    } else await route.fulfill({ response });
  });
  const optimize = page.getByRole("button", {
    name: "Optimize plan",
    exact: true,
  });
  await optimize.dblclick();
  await expect(
    page.getByText("Injected temporary poll failure", { exact: true }),
  ).toBeVisible();
  await expect(optimize).toBeEnabled({ timeout: 40000 });
  await expect(
    page.getByText("Independently validated", { exact: true }),
  ).toBeVisible();
  expect(submissions).toBe(1);
});

test("an open edit cannot overwrite a concurrently changed revision", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Western Freight/ }).click();
  await expect(
    page.getByRole("button", { name: "Optimize plan", exact: true }),
  ).toBeEnabled();
  const workspace = await (await page.request.get("/api/workspace")).json();
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let held = false;
  let reads = 0;
  let entered: () => void = () => {};
  const waiting = new Promise<void>((resolve) => {
    entered = resolve;
  });
  await page.route(/\/api\/runs\/[^/?]+$/, async (route) => {
    const response = await route.fetch();
    const run = await response.json();
    reads++;
    if (!held && reads > 1 && run.state === "succeeded") {
      held = true;
      entered();
      await gate;
    }
    await route.fulfill({ response });
  });
  await page
    .getByRole("button", { name: "Optimize plan", exact: true })
    .click();
  await waiting;
  await page.getByRole("button", { name: "SFD-1041", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("spinbutton", { name: "Weight (kg)" }).fill("15000");
  const otherJob = workspace.snapshot.jobs[1];
  try {
    const edit = await page.request.put(`/api/jobs/${otherJob.id}`, {
      headers: { "X-Freight-Request": "1" },
      data: {
        expected_version: workspace.version,
        job: { ...otherJob, weight_kg: otherJob.weight_kg + 1 },
      },
    });
    expect(edit.ok()).toBe(true);
    release();
    await expect(
      dialog.getByText(/Inputs changed while this form was open/),
    ).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: "Save reviewed inputs" }),
    ).toBeDisabled();
    const current = await (await page.request.get("/api/workspace")).json();
    expect(current.snapshot.jobs[0].weight_kg).toBe(
      workspace.snapshot.jobs[0].weight_kg,
    );
    const restore = await page.request.put(`/api/jobs/${otherJob.id}`, {
      headers: { "X-Freight-Request": "1" },
      data: { expected_version: current.version, job: otherJob },
    });
    expect(restore.ok()).toBe(true);
  } finally {
    release();
  }
});

test("AI provider failure stays visible and never creates an approved rule", async ({
  page,
}) => {
  await page.route("**/api/workspace", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: { ...(await response.json()), ai_configured: true },
    });
  });
  await page.route("**/api/rule-proposals", (route) =>
    route.fulfill({
      status: 503,
      json: {
        detail: "OpenAI rejected the configured API key. No rule was applied.",
      },
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: /Western Freight/ }).click();
  await expect(
    page.getByRole("button", { name: "Optimize plan", exact: true }),
  ).toBeEnabled();
  const before = await (await page.request.get("/api/workspace")).json();
  await page
    .getByRole("textbox", { name: "Dispatcher instruction" })
    .fill("أسند الشحنة SFD-1041 إلى Team 02");
  await page.getByRole("button", { name: "Interpret instruction" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "OpenAI rejected" }),
  ).toContainText("OpenAI rejected the configured API key");
  await expect(
    page.getByRole("button", { name: "Approve this rule" }),
  ).not.toBeVisible();
  const after = await (await page.request.get("/api/workspace")).json();
  expect(after.version).toBe(before.version);
  expect(after.snapshot.rules).toEqual(before.snapshot.rules);
});
