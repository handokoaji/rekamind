import { expect, test } from "@playwright/test";
const BASE = process.env.LOAD_BASE ?? "http://127.0.0.1:18998";
test("virtual task list is interactive", async ({ page }) => {
  const list = await (await page.request.get(`${BASE}/api/meetings`)).json();
  await page.goto(`${BASE}/rapat/${list[0].id}`);
  await page.getByRole("tab", { name: /^Task/ }).click();
  const confirm = page.getByRole("button", { name: /Konfirmasi/ }).first();
  await expect(confirm).toBeVisible();
  const before = await page.getByRole("heading", { name: /Perlu ditinjau \((\d+)\)/ }).textContent();
  await confirm.click();
  await expect(page.getByRole("heading", { name: /Perlu ditinjau/ })).not.toHaveText(before!);
  for (const y of [1200, 8000, 30000, 60000]) {
    await page.evaluate((v) => window.scrollTo(0, v), y); await page.waitForTimeout(500);
    const rows = await page.locator("li[data-index]").evaluateAll((els) => els.filter((e) => { const r = e.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight; }).length);
    console.log(`scroll ${y}: visible rows ${rows}`);
    expect(rows).toBeGreaterThan(2);
  }
  await page.screenshot({ path: "e2e-shots/vt-tasks.png" });
});
