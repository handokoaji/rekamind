import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Browser, type Page } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const IDP = "http://127.0.0.1:18971";

function wav(): string {
  const n = 16000, b = Buffer.alloc(44 + n * 2);
  b.write("RIFF", 0); b.writeUInt32LE(36 + n * 2, 4); b.write("WAVEfmt ", 8); b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(16000, 24); b.writeUInt32LE(32000, 28);
  b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write("data", 36); b.writeUInt32LE(n * 2, 40);
  const p = join(tmpdir(), "rapat-alice.wav");
  writeFileSync(p, b);
  return p;
}

/** A person at their own browser (own cookie jar), signing in as `email` at the fake Google. */
async function signIn(browser: Browser, email: string) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await ctx.request.post(`${IDP}/__identity`, { data: { email, sub: `sub-${email}`, name: email.split("@")[0] } });
  await page.goto("/");
  await page.getByRole("link", { name: /Masuk dengan Google/ }).click();
  return { ctx, page };
}
const ready = (page: Page) => expect(page.getByRole("heading", { name: "Rapat", exact: true })).toBeVisible();

async function uploadAndProcess(page: Page, title: string) {
  await page.getByRole("button", { name: "Rapat baru" }).first().click();
  await page.locator('input[type="file"]').setInputFiles(wav());
  await page.getByLabel("Judul rapat").fill(title);
  await page.getByRole("button", { name: "Unggah" }).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText("Perlu ditinjau").first()).toBeVisible({ timeout: 15_000 });
  return page.url();
}

test("anyone not signed in sees only the login screen, and it is accessible in both themes", async ({ browser }) => {
  for (const scheme of ["light", "dark"] as const) {
    const ctx = await browser.newContext({ colorScheme: scheme });
    const page = await ctx.newPage();
    await page.goto("/rapat/anything");
    await expect(page.getByRole("link", { name: /Masuk dengan Google/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Rapat", exact: true })).toHaveCount(0); // no app chrome leaks
    expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations.map((v) => v.id)).toEqual([]);
    await page.screenshot({ path: `e2e-shots/auth-login-${scheme}.png` });
    await ctx.close();
  }
});

test("signing in lands you back where you were going, and the session survives a reload", async ({ browser }) => {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await ctx.request.post(`${IDP}/__identity`, { data: { email: "alice@kantor.id", sub: "sub-alice@kantor.id", name: "Alice" } });
  await page.goto("/task");
  await page.getByRole("link", { name: /Masuk dengan Google/ }).click();
  await expect(page).toHaveURL(/\/task$/);
  await expect(page.getByRole("heading", { name: "Task", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Task", exact: true })).toBeVisible();
  await expect(page.getByText("alice@kantor.id").first()).toBeVisible();
  await ctx.close();
});

test("two users never see each other's meetings, even with the direct link", async ({ browser }) => {
  const alice = await signIn(browser, "alice@kantor.id");
  await ready(alice.page);
  const url = await uploadAndProcess(alice.page, "Rapat rahasia Alice");

  const bob = await signIn(browser, "bob@kantor.id");
  await ready(bob.page);
  await expect(bob.page.getByRole("heading", { name: "Belum ada rapat" })).toBeVisible();
  await bob.page.goto(url); // Alice's private link, pasted into Bob's browser
  await expect(bob.page.getByRole("heading", { name: "Rapat tidak ditemukan" })).toBeVisible();
  await expect(bob.page.getByText("Rapat rahasia Alice")).toHaveCount(0);
  await bob.page.screenshot({ path: "e2e-shots/auth-bob-cannot-see.png" });

  await alice.page.goto("/");
  await expect(alice.page.getByText("Rapat rahasia Alice")).toBeVisible();
  await alice.ctx.close(); await bob.ctx.close();
});

test("a person outside the allow list is told clearly, and gets no account", async ({ browser }) => {
  const s = await signIn(browser, "stranger@gmail.com");
  await expect(s.page.getByRole("heading", { name: "Akun Anda belum diizinkan" })).toBeVisible();
  await expect(s.page.getByText(/Minta administrator/)).toBeVisible();
  await s.page.screenshot({ path: "e2e-shots/auth-not-allowed.png" });
  await s.page.goto("/");
  await expect(s.page.getByRole("link", { name: /Masuk dengan Google/ })).toBeVisible();
  await s.ctx.close();
});

test("sign out ends the session", async ({ browser }) => {
  const a = await signIn(browser, "alice@kantor.id");
  await ready(a.page);
  await a.page.getByRole("button", { name: "Keluar" }).click();
  await expect(a.page.getByRole("link", { name: /Masuk dengan Google/ })).toBeVisible();
  await a.page.goto("/");
  await expect(a.page.getByRole("link", { name: /Masuk dengan Google/ })).toBeVisible();
  await a.ctx.close();
});

test("ordinary users have no admin page and no 'all users' switch", async ({ browser }) => {
  const a = await signIn(browser, "alice@kantor.id");
  await ready(a.page);
  await expect(a.page.getByRole("link", { name: "Pengguna" })).toHaveCount(0);
  await expect(a.page.getByRole("group", { name: "Cakupan rapat" })).toHaveCount(0);
  await a.page.goto("/admin");
  await expect(a.page.getByRole("heading", { name: "Rapat", exact: true })).toBeVisible(); // bounced home
  await a.ctx.close();
});

test("the super admin manages users and can look at everyone's meetings", async ({ browser }) => {
  const alice = await signIn(browser, "alice@kantor.id");
  await ready(alice.page);
  await uploadAndProcess(alice.page, "Rapat Alice untuk admin");
  const bob = await signIn(browser, "bob@kantor.id");
  await ready(bob.page);

  const boss = await signIn(browser, "boss@kantor.id");
  await ready(boss.page);
  await expect(boss.page.getByText("Super admin").first()).toBeVisible();
  await expect(boss.page.getByText("Rapat Alice untuk admin")).toHaveCount(0); // default view: only my own
  await boss.page.getByRole("button", { name: "Semua pengguna" }).click();
  const row = boss.page.getByRole("link", { name: /Rapat Alice untuk admin/ });
  await expect(row).toBeVisible();
  await expect(boss.page.getByText("alice@kantor.id").first()).toBeVisible(); // whose it is
  await boss.page.screenshot({ path: "e2e-shots/auth-boss-all-meetings.png" });

  await boss.page.getByRole("link", { name: "Pengguna" }).click();
  await expect(boss.page.getByRole("heading", { name: "Pengguna", exact: true })).toBeVisible();
  await boss.page.getByLabel("Undang dengan email Google").fill("carol@luar.org");
  await boss.page.getByRole("button", { name: "Undang" }).click();
  await expect(boss.page.getByText("carol@luar.org")).toBeVisible();
  await expect(boss.page.getByText("Diundang")).toBeVisible();
  await boss.page.screenshot({ path: "e2e-shots/auth-admin-users.png", fullPage: true });
  expect((await new AxeBuilder({ page: boss.page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations.map((v) => `${v.id}: ${v.nodes[0]?.target.join(" ")}`)).toEqual([]);

  // Disabling Bob ends his session at once: his next request lands on the login screen.
  await boss.page.getByRole("listitem").filter({ hasText: "bob@kantor.id" }).getByRole("button", { name: "Nonaktifkan" }).click();
  await boss.page.getByRole("dialog").getByRole("button", { name: "Ya, lanjutkan" }).click();
  await expect(boss.page.getByText("Nonaktif", { exact: true })).toBeVisible();
  await bob.page.reload();
  await expect(bob.page.getByRole("link", { name: /Masuk dengan Google/ })).toBeVisible();

  // The only active super admin cannot demote themselves: the server refuses and says why.
  await boss.page.getByRole("listitem").filter({ hasText: "boss@kantor.id" }).getByRole("button", { name: "Cabut super admin" }).click();
  await boss.page.getByRole("dialog").getByRole("button", { name: "Ya, lanjutkan" }).click();
  await expect(boss.page.getByText(/super admin aktif terakhir/)).toBeVisible();
  for (const c of [alice, bob, boss]) await c.ctx.close();
});
