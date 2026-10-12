import { expect, test } from "@playwright/test";

test("live Arabic instruction requires approval and changes the real plan", async ({
  page,
}) => {
  test.skip(
    process.env.FREIGHT_LIVE_AI !== "1",
    "Explicit opt-in required: makes a paid OpenAI call on synthetic data.",
  );
  await page.goto("/");
  await page.getByRole("button", { name: /Western Freight/ }).click();
  await expect(
    page.getByRole("button", { name: "Optimize plan", exact: true }),
  ).toBeEnabled();
  const before = await (await page.request.get("/api/workspace")).json();
  expect(before.ai_configured).toBe(true);
  expect(before.snapshot.mode).toBe("demo");
  await page.getByRole("button", { name: "العربية", exact: true }).click();
  await page
    .getByRole("textbox", { name: "تعليمات الموزّع" })
    .fill("يجب إسناد الشحنة SFD-1041 إلى Team 02.");
  const response = page.waitForResponse(
    (res) =>
      res.url().endsWith("/api/rule-proposals") &&
      res.request().method() === "POST",
  );
  await page.getByRole("button", { name: "تفسير التعليمات" }).click();
  const returned = await response;
  expect(returned.ok()).toBe(true);
  const proposal = await returned.json();
  expect(proposal.rule).toMatchObject({
    kind: "preferred_assignment",
    job_id: "job-001",
    team_id: "team-02",
    strength: "hard",
  });
  const pending = await (await page.request.get("/api/workspace")).json();
  expect(pending.version).toBe(before.version);
  await expect(
    page.getByRole("button", { name: "اعتماد هذه القاعدة" }),
  ).toBeEnabled();
  await page.screenshot({
    path: "../../.runtime/screenshots/live-ai-arabic-review.png",
    fullPage: true,
  });
  try {
    await page.getByRole("button", { name: "اعتماد هذه القاعدة" }).click();
    await expect(
      page.getByRole("button", { name: "اعتماد هذه القاعدة" }),
    ).not.toBeVisible();
    const optimize = page.getByRole("button", {
      name: "تحسين الخطة",
      exact: true,
    });
    await optimize.click();
    await expect(optimize).toBeEnabled({ timeout: 40000 });
    const row = page.getByRole("row").filter({
      has: page.getByRole("button", { name: "SFD-1041", exact: true }),
    });
    await expect(row).toContainText("Team 02");
    const runs = await (await page.request.get("/api/runs")).json();
    const run = await (
      await page.request.get(`/api/runs/${runs[0].id}`)
    ).json();
    expect(run.result.candidate.valid).toBe(true);
    expect(run.result.candidate.coverage).toBe("complete");
    await page.screenshot({
      path: "../../.runtime/screenshots/live-ai-arabic-plan.png",
      fullPage: true,
    });
  } finally {
    const latest = await (await page.request.get("/api/workspace")).json();
    if (
      latest.snapshot.rules.some(
        (rule: { id: string }) => rule.id === proposal.rule.id,
      )
    ) {
      const removed = await page.request.delete(
        `/api/rules/${proposal.rule.id}`,
        {
          headers: { "X-Freight-Request": "1" },
          data: { expected_version: latest.version },
        },
      );
      expect(removed.ok()).toBe(true);
    }
  }
});
