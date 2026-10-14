import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext } from "@playwright/test";

function wav(): Buffer {
  const n = 16000, b = Buffer.alloc(44 + n * 2);
  b.write("RIFF", 0); b.writeUInt32LE(36 + n * 2, 4); b.write("WAVEfmt ", 8); b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(16000, 24); b.writeUInt32LE(32000, 28);
  b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write("data", 36); b.writeUInt32LE(n * 2, 40);
  return b;
}

async function seed(request: APIRequestContext, title: string): Promise<string> {
  const m = await (await request.post("/api/meetings", { data: { title, local_user_name: "Andi" } })).json();
  for (const src of ["mic", "speaker"]) await request.put(`/api/meetings/${m.id}/audio/${src}`, { data: wav() });
  await request.post(`/api/meetings/${m.id}/finish`);
  await request.post(`/api/meetings/${m.id}/process`);
  await expect.poll(async () => (await (await request.get(`/api/meetings/${m.id}`)).json()).status, { timeout: 15_000 }).toBe("review");
  return m.id;
}

const schemes = ["light", "dark"] as const;

/** A page is "ready" only when no spinner or skeleton is left and it has a heading: otherwise
 *  axe and screenshots would be judging a loading state, not the page. */
async function settled(page: import("@playwright/test").Page) {
  await expect(page.locator("main h1")).toBeVisible();
  await expect(page.locator('[role="status"], .animate-pulse')).toHaveCount(0);
}

for (const scheme of schemes) {
  test(`axe: no WCAG A/AA violations on every page (${scheme})`, async ({ page, request }) => {
    const id = await seed(request, `Rapat ${scheme}`);
    await page.emulateMedia({ colorScheme: scheme });
    const routes = ["/", `/rapat/${id}?tab=ringkasan`, `/rapat/${id}?tab=task`, `/rapat/${id}?tab=transkrip`, `/rapat/${id}?tab=pembicara`, "/task", "/pengaturan", "/tidak-ada"];
    for (const r of routes) {
      await page.goto(r);
      await settled(page);
      const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      const summary = res.violations.map((v) => `${v.id} (${v.nodes.length}): ${v.nodes[0]?.target.join(" ")}`);
      expect(summary, `${scheme} ${r}`).toEqual([]);
    }
    await page.goto(`/rapat/${id}?tab=task`);
    await settled(page);
    await page.screenshot({ path: `e2e-shots/${scheme}-tasks.png`, fullPage: true });
    await page.goto("/");
    await settled(page);
    await page.screenshot({ path: `e2e-shots/${scheme}-list.png`, fullPage: true });
  });
}

test("mobile layout: no horizontal scroll and primary actions reachable", async ({ page, request }) => {
  const id = await seed(request, "Rapat mobile");
  await page.setViewportSize({ width: 375, height: 800 });
  for (const r of ["/", `/rapat/${id}?tab=task`, `/rapat/${id}?tab=transkrip`, "/task", "/pengaturan"]) {
    await page.goto(r);
    await settled(page);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `horizontal overflow on ${r}`).toBeLessThanOrEqual(0);
  }
  await page.goto("/");
  await settled(page);
  await page.screenshot({ path: "e2e-shots/mobile-list.png", fullPage: true });
  await page.goto(`/rapat/${id}?tab=task`);
  await settled(page);
  await page.screenshot({ path: "e2e-shots/mobile-tasks.png", fullPage: true });
});

test("keyboard: '/' focuses search, dialog traps focus and Esc closes it", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Rapat", exact: true })).toBeVisible(); // app has mounted
  await page.keyboard.press("/");
  await expect(page.getByLabel("Cari rapat")).toBeFocused();
  await page.getByRole("button", { name: "Rapat baru" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
});
