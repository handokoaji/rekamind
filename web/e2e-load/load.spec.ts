import { expect, test } from "@playwright/test";

// Not part of CI: run by hand against a server holding a big meeting (see docs/v2/PC_TEST_CHECKLIST.md).
const BASE = process.env.LOAD_BASE ?? "http://127.0.0.1:18998";

test("a 4-hour meeting (4000 segments, 300 tasks) opens fast and stays responsive", async ({ page }) => {
  const list = await (await page.request.get(`${BASE}/api/meetings`)).json();
  const big = list.find((m: { segments?: unknown }) => true);
  const all = await Promise.all(list.map(async (m: { id: string }) => (await page.request.get(`${BASE}/api/meetings/${m.id}`)).json()));
  const target = all.sort((a: { segments: unknown[] }, b: { segments: unknown[] }) => b.segments.length - a.segments.length)[0];
  expect(target.segments.length).toBeGreaterThan(3000);
  void big;

  const t0 = Date.now();
  await page.goto(`${BASE}/rapat/${target.id}`);
  await expect(page.getByRole("heading", { name: target.title })).toBeVisible();
  const loadMs = Date.now() - t0;
  const nodes = await page.evaluate(() => document.querySelectorAll("*").length);
  console.log(`detail load ${loadMs} ms, DOM nodes ${nodes}`);

  await page.evaluate(() => {
    (window as unknown as { __long: number[] }).__long = [];
    new PerformanceObserver((l) => l.getEntries().forEach((e) => (window as unknown as { __long: number[] }).__long.push(e.duration))).observe({ entryTypes: ["longtask"] });
  });
  for (const tab of ["Transkrip", "Task"]) {
    const t = Date.now();
    await page.getByRole("tab", { name: new RegExp(`^${tab}`) }).click();
    await page.waitForTimeout(100);
    const switchMs = Date.now() - t;
    const dom = await page.evaluate(() => document.querySelectorAll("*").length);
    for (let i = 0; i < 20; i++) { await page.mouse.wheel(0, 5000); await page.waitForTimeout(40); }
    const long = await page.evaluate(() => (window as unknown as { __long: number[] }).__long.splice(0));
    console.log(`tab ${tab}: switch ${switchMs} ms, DOM ${dom}, long tasks while scrolling ${long.length}, worst ${Math.max(0, ...long).toFixed(0)} ms`);
    expect(switchMs).toBeLessThan(3000);
  }
  const t1 = Date.now();
  await page.goto(`${BASE}/task`);
  await expect(page.getByRole("heading", { name: "Task", exact: true })).toBeVisible();
  await page.waitForTimeout(500);
  console.log(`tasks page ${Date.now() - t1} ms, DOM nodes ${await page.evaluate(() => document.querySelectorAll("*").length)}`);
  expect(loadMs).toBeLessThan(5000);
});
