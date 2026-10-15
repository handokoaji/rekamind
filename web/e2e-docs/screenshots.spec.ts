import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { join } from "node:path";

const OUT = join(import.meta.dirname, "../../docs/screenshots");
const states = JSON.parse(readFileSync(join(import.meta.dirname, "../../desktop/contract/ui-state.json"), "utf8"));

function wav(): Buffer {
  const n = 16000, b = Buffer.alloc(44 + n * 2);
  b.write("RIFF", 0); b.writeUInt32LE(36 + n * 2, 4); b.write("WAVEfmt ", 8); b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(16000, 24); b.writeUInt32LE(32000, 28);
  b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write("data", 36); b.writeUInt32LE(n * 2, 40);
  return b;
}

async function seed(r: APIRequestContext, title: string): Promise<string> {
  const m = await (await r.post("/api/meetings", { data: { title, local_user_name: "Andi" } })).json();
  for (const s of ["mic", "speaker"]) await r.put(`/api/meetings/${m.id}/audio/${s}`, { data: wav() });
  await r.post(`/api/meetings/${m.id}/finish`);
  await r.post(`/api/meetings/${m.id}/process`);
  await expect.poll(async () => (await (await r.get(`/api/meetings/${m.id}`)).json()).status, { timeout: 20_000 }).toBe("review");
  return m.id;
}

async function settled(page: Page) {
  await expect(page.locator("main h1").first()).toBeVisible();
  await expect(page.locator('[role="status"]:not([aria-live]), .animate-pulse:not(.animate-ping)')).toHaveCount(0, { timeout: 8000 }).catch(() => undefined);
  await page.waitForTimeout(250);
}
const shot = (page: Page, name: string, full = false) => page.screenshot({ path: join(OUT, `${name}.png`), fullPage: full });

async function asDesktop(page: Page, phase: string) {
  await page.addInitScript(({ states, phase }) => {
    const w = window as unknown as Record<string, unknown>;
    w.__TAURI_INTERNALS__ = {
      transformCallback: () => 1, unregisterCallback: () => undefined, convertFileSrc: (p: string) => p,
      invoke: async (cmd: string) => {
        switch (cmd) {
          case "recorder_state": return states[phase];
          case "settings_get":
            return { settings: { mode: "local", server: location.origin, local_program: "auto", local_args: [], local_port: 8787, language: "id", local_user_name: "Andi", auto_process: true, hotkey: "CmdOrCtrl+Alt+R",
              whisper_model: "large-v3", whisper_device: "auto", diarizer: "none", llm_base_url: "https://api.groq.com/openai/v1", llm_model: "openai/gpt-oss-120b", glossary: "" },
              server_url: location.origin, auth_token: null, recordings_dir: "C:\\Users\\Andi\\AppData\\Local\\Rekamind\\recordings", hotkey_error: null,
              has_llm_key: true, has_hf_token: false, bundled_backend: true, backend_dir: "C:\\Users\\Andi\\AppData\\Local\\Rekamind\\backend" };
          case "engines_status":
            return { pack: { pack_dir: "C:\\Users\\Andi\\AppData\\Local\\Rekamind\\backend\\engine-pack", asr: true, diarize: false, kind: "cuda", python: "3.13" }, job: { running: null, log: [], last_error: null } };
          case "engines_check": return { ok: true, error: null, cuda_devices: 1, faster_whisper: "1.2.1" };
          default: return;
        }
      },
    };
    w.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener: () => undefined };
  }, { states, phase });
}

test("screenshots README", async ({ page, request }) => {
  test.setTimeout(240_000);

  // login (backend berjalan tanpa auth, jadi /api/me dijawab 401 hanya untuk gambar ini)
  await page.route("**/api/me", (r) => r.fulfill({ status: 401, contentType: "application/json", body: '{"detail":"login"}' }));
  await page.goto("/");
  await expect(page.getByRole("link", { name: /Masuk dengan Google/ })).toBeVisible();
  await shot(page, "01-login");
  await page.unroute("**/api/me");

  // daftar kosong -> unggah
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Belum ada rapat" })).toBeVisible();
  await shot(page, "02-kosong");

  // data contoh
  const id = await seed(request, "Rapat peluncuran fitur laporan");
  await seed(request, "Evaluasi vendor lisensi Q4");
  await seed(request, "Sinkronisasi tim desain mingguan");

  await page.goto("/");
  await page.getByRole("button", { name: "Rapat baru" }).first().click();
  await page.getByLabel("Judul rapat").fill("Rapat anggaran Q4");
  await page.getByLabel("Nama Anda di rekaman").fill("Andi");
  await shot(page, "03-unggah");
  await page.keyboard.press("Escape");

  await page.goto("/");
  await settled(page);
  await shot(page, "04-daftar-rapat");

  // detail
  await page.goto(`/rapat/${id}?tab=ringkasan`);
  await settled(page);
  await shot(page, "05-ringkasan", true);

  await page.getByRole("tab", { name: "Pembicara" }).click();
  await page.getByLabel("Nama untuk SPEAKER_00").fill("Rina Wijaya");
  await page.getByLabel("Nama untuk SPEAKER_00").blur();
  await page.getByLabel("Nama untuk SPEAKER_01").fill("Dewi Lestari");
  await page.getByLabel("Nama untuk SPEAKER_01").blur();
  await page.waitForTimeout(500);
  await shot(page, "07-pembicara", true);

  await page.getByRole("tab", { name: "Transkrip" }).click();
  await settled(page);
  await shot(page, "06-transkrip", true);

  // integrasi webhook penerima nyata
  const srv = createServer((q, s) => { q.resume(); q.on("end", () => s.writeHead(204).end()); });
  await new Promise<void>((r) => srv.listen(0, "127.0.0.1", r));
  const port = (srv.address() as { port: number }).port;
  try {
    await page.goto("/pengaturan");
    await page.getByRole("button", { name: /Tambah integrasi/ }).click();
    await page.getByLabel("Jenis").selectOption("webhook");
    await page.getByLabel("Nama tampilan").fill("Task manager tim");
    await page.getByLabel("URL penerima").fill(`http://127.0.0.1:${port}/hook`);
    await page.getByLabel(/Rahasia tanda tangan/).fill("whsec_contoh");
    await page.getByRole("button", { name: "Simpan" }).last().click();
    await expect(page.getByText("Task manager tim")).toBeVisible();
    await settled(page);
    await shot(page, "12-pengaturan", true);

    await page.goto(`/rapat/${id}?tab=task`);
    await settled(page);
    await page.getByRole("button", { name: /^Konfirmasi/ }).first().click();
    await page.waitForTimeout(300);
    await page.getByRole("button", { name: /^Konfirmasi/ }).first().click();
    await page.waitForTimeout(300);
    await shot(page, "08-task", true);
    await page.getByRole("button", { name: /^Kirim \d+ task/ }).click();
    await expect(page.getByText(/task terkirim ke Task manager tim/)).toBeVisible();
    await shot(page, "10-kirim-task");
  } finally { srv.close(); }

  await page.getByRole("button", { name: "Ekspor" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await shot(page, "09-ekspor");
  await page.keyboard.press("Escape");

  await page.goto("/task");
  await settled(page);
  await shot(page, "11-semua-task", true);

  // gelap
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto(`/rapat/${id}?tab=ringkasan`);
  await settled(page);
  await shot(page, "05b-ringkasan-gelap", true);
  await page.emulateMedia({ colorScheme: "light" });
});

for (const [phase, name] of [["idle", "13-desktop-siap"], ["recording", "14-desktop-merekam"]] as const) {
  test(`desktop ${phase}`, async ({ page }) => {
    await asDesktop(page, phase);
    await page.goto("/");
    await settled(page);
    await shot(page, name);
  });
}

test("desktop pengaturan mesin", async ({ page }) => {
  await asDesktop(page, "idle");
  await page.goto("/pengaturan");
  await expect(page.getByRole("heading", { name: "Mesin transkripsi" })).toBeVisible();
  await settled(page);
  await shot(page, "15-desktop-mesin", true);
});
