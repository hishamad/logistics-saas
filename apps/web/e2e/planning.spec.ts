import { expect, test } from "@playwright/test";

test("real planning, rule approval, import review, persistence and Arabic layout", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Step into the planning room" }),
  ).toBeVisible();
  await page.screenshot({
    path: "../../.runtime/screenshots/welcome.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: /Eastern Freight/ }).click();
  await expect(
    page.getByRole("heading", { name: "See the day. Shape the plan." }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Optimize plan", exact: true })
    .click();
  // The API and navigation remain responsive while the separate worker solves.
  await page.getByRole("button", { name: "Plan history", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Every plan has a provenance" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Planning board", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Optimize plan", exact: true }),
  ).toBeEnabled({ timeout: 40000 });
  await expect(
    page.getByText("Independently validated", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("All obligations assigned", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../../.runtime/screenshots/planning-en.png",
    fullPage: true,
  });
  const timelineActivity = page.locator(".activity.empty").first();
  await expect(timelineActivity).toHaveCSS("height", "20px");
  await expect(timelineActivity).toHaveCSS("padding", "0px");
  await page
    .getByRole("button", { name: "Add a structured rule", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("combobox", { name: "Team", exact: true })
    .selectOption("team-02");
  await dialog
    .getByRole("combobox", { name: "Job", exact: true })
    .selectOption("job-001");
  await dialog
    .getByRole("button", { name: "Approve rule", exact: true })
    .click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByText(/Showing saved revision/)).toBeVisible();
  await page
    .getByRole("button", { name: "Optimize plan", exact: true })
    .click();
  await expect(page.getByText(/Showing saved revision/)).not.toBeVisible({
    timeout: 30000,
  });
  const row = page.getByRole("row").filter({
    has: page.getByRole("button", { name: "SFD-1041", exact: true }),
  });
  await expect(row).toContainText("Team 02");
  await page.getByRole("button", { name: "Data imports", exact: true }).click();
  await page.getByText("Or paste CSV", { exact: true }).click();
  await page
    .getByRole("textbox", { name: "CSV contents" })
    .fill(
      "id,reference,customer,pickup_site_id,delivery_site_id,pickup_start,pickup_end,delivery_start,delivery_end,equipment,weight_kg\nreview-job,REVIEW-01,Demo Customer,depot,industrial,2026-10-13T08:00:00+03:00,2026-10-13T12:00:00+03:00,2026-10-13T09:00:00+03:00,2026-10-13T16:00:00+03:00,dry_van,8000",
    );
  await page.getByRole("button", { name: "Preview & validate" }).click();
  await expect(
    page.getByRole("heading", { name: "Review changes" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Commit reviewed rows" }).click();
  await expect(page.getByText(/Committed .* changes/)).toBeVisible();
  await page
    .getByRole("button", { name: "Planning board", exact: true })
    .click();
  await page.getByRole("button", { name: "العربية", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(
    page.getByRole("heading", { name: "راقب يومك، وارسم خطتك." }),
  ).toBeVisible();
  await page.screenshot({
    path: "../../.runtime/screenshots/planning-ar.png",
    fullPage: true,
  });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(
    page.getByRole("heading", { name: "راقب يومك، وارسم خطتك." }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "../../.runtime/screenshots/planning-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});
