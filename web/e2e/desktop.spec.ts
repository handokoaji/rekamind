import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// The exact JSON the Rust controller emits (golden file shared with the Rust tests).
const states = JSON.parse(readFileSync(join(import.meta.dirname, "../../desktop/contract/ui-state.json"), "utf8"));

/** Pretends to be the Tauri shell: same invoke() protocol, state taken from the Rust golden file. */
async function asDesktop(page: Page, phase: string, mode = "remote") {
  await page.addInitScript(({ states, phase, mode }) => {
    const w = window as unknown as Record<string, unknown> & { __calls: string[]; __phase: string };
    w.__calls = [];
    w.__phase = phase;
    w.__TAURI_INTERNALS__ = {
      transformCallback: () => 1,
      unregisterCallback: () => undefined,
      convertFileSrc: (p: string) => p,
      invoke: async (cmd: string, args: Record<string, unknown>) => {
        w.__calls.push(cmd + (args && args.dir ? `:${args.dir}` : ""));
        switch (cmd) {
          case "recorder_state": return states[w.__phase];
          case "recorder_start": w.__phase = "recording"; return;
          case "recorder_stop": w.__phase = "uploading"; return;
          case "recorder_dismiss": w.__phase = "idle"; return;
          case "settings_get":
            return { settings: { mode, server: location.origin, local_program: "auto", local_args: [], local_port: 8787, language: "id", local_user_name: "Andi", auto_process: true, hotkey: "CmdOrCtrl+Alt+R",
              whisper_model: "large-v3", whisper_device: "auto", diarizer: "none", llm_base_url: "https://api.groq.com/openai/v1", llm_model: "openai/gpt-oss-120b", glossary: "" },
              server_url: location.origin, auth_token: null, recordings_dir: "/home/andi/.local/share/rekamind/recordings", hotkey_error: null,
              has_llm_key: true, has_hf_token: false, bundled_backend: true, backend_dir: "/home/andi/.local/share/rekamind/backend" };
          case "engines_status":
            return { pack: { pack_dir: "/home/andi/.local/share/rekamind/backend/engine-pack", asr: true, diarize: false, kind: "cpu", python: "3.13" }, job: { running: null, log: ["Successfully installed faster-whisper-1.2.1"], last_error: null } };
          case "engines_check": return { ok: true, error: null, cuda_devices: 0, faster_whisper: "1.2.1" };
          default: return; // backend_ensure, recorder_retry, recorder_discard...
        }
      },
    };
    w.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener: () => undefined };
  }, { states, phase, mode });
}

async function settled(page: Page) {
  await expect(page.locator("main h1").first()).toBeVisible();
  await expect(page.locator('[role="status"]:not([aria-live]), .animate-pulse:not(.animate-ping)')).toHaveCount(0, { timeout: 8000 }).catch(() => undefined);
}

for (const scheme of ["light", "dark"] as const) {
  for (const phase of ["idle", "recording", "uploading", "done", "done_not_processed", "needs_attention"]) {
    test(`desktop recorder UI is WCAG AA clean: ${phase} (${scheme})`, async ({ page }) => {
      await asDesktop(page, phase);
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto("/");
      await settled(page);
      await expect(page.getByRole("region", { name: "Perekam" })).toBeVisible();
      const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      expect(res.violations.map((v) => `${v.id}: ${v.nodes[0]?.target.join(" ")}`), `${phase}/${scheme}`).toEqual([]);
      await page.screenshot({ path: `e2e-shots/desktop-${phase}-${scheme}.png`, fullPage: true });
    });
  }
}

test("the recording bar follows you to every page and shows a problem source in words", async ({ page }) => {
  await asDesktop(page, "recording");
  for (const route of ["/task", "/pengaturan"]) {
    await page.goto(route);
    const bar = page.getByRole("status").filter({ hasText: "Merekam" });
    await expect(bar).toBeVisible();
    await expect(bar).toContainText("Audio komputer: Perangkat terputus");
  }
});

test("start flow: type a title, start, stop needs confirmation, then upload progress shows", async ({ page }) => {
  await asDesktop(page, "idle");
  await page.goto("/");
  await page.getByLabel("Rekam rapat sekarang").fill("Rapat vendor");
  await page.getByRole("button", { name: /Mulai merekam/ }).click();
  await expect(page.getByText("Sedang merekam")).toBeVisible();
  await page.getByRole("button", { name: "Hentikan rekaman" }).click();
  await expect(page.getByRole("dialog", { name: "Hentikan rekaman?" })).toBeVisible();
  await page.getByRole("button", { name: "Lanjut merekam" }).click(); // cancelling must not stop
  expect(await page.evaluate(() => (window as unknown as { __calls: string[] }).__calls.includes("recorder_stop"))).toBe(false);
  await page.getByRole("button", { name: "Hentikan rekaman" }).click();
  await page.getByRole("dialog").getByRole("button", { name: /^Hentikan$/ }).click();
  await expect(page.getByRole("progressbar", { name: "Kemajuan unggahan" })).toBeVisible();
  const calls = await page.evaluate(() => (window as unknown as { __calls: string[] }).__calls);
  expect(calls).toContain("recorder_start");
  expect(calls).toContain("recorder_stop");
});

test("a normal browser never shows desktop-only controls", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Rapat", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Perekam" })).toHaveCount(0);
  await expect(page.getByText(/aplikasi desktop/)).toBeVisible(); // the browser is told where recording lives
});

for (const scheme of ["light", "dark"] as const) {
  test(`desktop settings with the local engine panel are WCAG AA clean (${scheme})`, async ({ page }) => {
    await asDesktop(page, "idle", "local");
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto("/pengaturan");
    await expect(page.getByRole("heading", { name: "Mesin transkripsi" })).toBeVisible();
    await expect(page.getByText(/Terpasang · CPU/)).toBeVisible();
    await expect(page.getByLabel("Kunci API ringkasan")).toHaveAttribute("type", "password");
    const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(res.violations.map((v) => `${v.id}: ${v.nodes[0]?.target.join(" ")}`)).toEqual([]);
    await page.screenshot({ path: `e2e-shots/desktop-settings-${scheme}.png`, fullPage: true });
  });
}
