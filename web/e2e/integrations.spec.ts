import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { createHmac } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { createServer, type IncomingMessage } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Real browser + real backend + a real HTTP receiver: the whole "confirm -> send -> export" path.
function wav(): string {
  const n = 16000, b = Buffer.alloc(44 + n * 2);
  b.write("RIFF", 0); b.writeUInt32LE(36 + n * 2, 4); b.write("WAVEfmt ", 8); b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(16000, 24); b.writeUInt32LE(32000, 28);
  b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write("data", 36); b.writeUInt32LE(n * 2, 40);
  const p = join(tmpdir(), "rapat-kirim.wav"); writeFileSync(p, b); return p;
}

test("confirm a task, send it to a webhook, export the meeting as Word and Markdown", async ({ page }) => {
  const got: { headers: IncomingMessage["headers"]; body: string }[] = [];
  const srv = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => { got.push({ headers: req.headers, body: Buffer.concat(chunks).toString("utf8") }); res.writeHead(204).end(); });
  });
  await new Promise<void>((r) => srv.listen(0, "127.0.0.1", r));
  const port = (srv.address() as { port: number }).port;

  try {
    // 1. a processed meeting
    await page.goto("/");
    await page.getByRole("button", { name: "Rapat baru" }).first().click();
    await page.locator('input[type="file"]').setInputFiles(wav());
    await page.getByLabel("Judul rapat").fill("Rapat kirim task");
    await page.getByRole("button", { name: "Unggah" }).click();
    await expect(page.getByRole("heading", { name: "Rapat kirim task" })).toBeVisible();
    await expect(page.getByText("Perlu ditinjau").first()).toBeVisible({ timeout: 15_000 });
    const meetingUrl = page.url();

    // 2. configure the integration in Settings and test the connection
    await page.goto("/pengaturan");
    await page.getByRole("button", { name: /Tambah integrasi/ }).click();
    await page.getByLabel("Jenis").selectOption("webhook");
    await page.getByLabel("Nama tampilan").fill("Task manager kami");
    await page.getByLabel("URL penerima").fill(`http://127.0.0.1:${port}/hook`);
    await page.getByLabel(/Rahasia tanda tangan/).fill("whsec_e2e");
    const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(axe.violations.map((v) => `${v.id}: ${v.nodes[0]?.target.join(" ")}`)).toEqual([]);
    await page.getByRole("button", { name: "Simpan" }).last().click(); // the server card above has its own
    await expect(page.getByText("Task manager kami")).toBeVisible();
    await page.getByRole("button", { name: "Uji integrasi" }).click();
    await expect(page.getByText("Webhook menjawab dengan sukses.")).toBeVisible();
    expect(got.at(-1)!.headers["x-rekamind-event"]).toBe("ping");

    // 3. confirming sends nothing; sending is its own click
    await page.goto(meetingUrl);
    await page.getByRole("tab", { name: /^Task/ }).click();
    const before = got.length;
    await page.getByRole("button", { name: /^Konfirmasi/ }).first().click();
    await expect(page.getByRole("button", { name: /^Kirim \d+ task/ })).toBeVisible();
    expect(got.length).toBe(before);
    await page.getByRole("button", { name: /^Kirim \d+ task/ }).click();
    await expect(page.getByText(/task terkirim ke Task manager kami/)).toBeVisible();
    await expect.poll(() => got.length).toBe(before + 1);
    const req = got.at(-1)!;
    const sig = "sha256=" + createHmac("sha256", "whsec_e2e").update(`${req.headers["x-rekamind-timestamp"]}.${req.body}`).digest("hex");
    expect(req.headers["x-rekamind-signature"]).toBe(sig);
    expect(JSON.parse(req.body).task.title).toBeTruthy();
    // sending again does nothing (the task is unchanged)
    await page.getByRole("button", { name: /^Kirim/ }).click();
    await page.waitForTimeout(500);
    expect(got.length).toBe(before + 1);

    // 4. exports
    await page.getByRole("button", { name: "Ekspor" }).click();
    const docx = page.waitForEvent("download");
    await page.getByRole("button", { name: /Unduh/ }).click();
    const d = await docx;
    expect(d.suggestedFilename()).toMatch(/^rekamind-.*rapat-kirim-task\.docx$/);
    expect(readFileSync((await d.path())!).subarray(0, 2).toString()).toBe("PK"); // a real zip container
    await page.getByRole("button", { name: "Ekspor" }).click();
    await page.getByRole("radio", { name: /Markdown/ }).check();
    const md = page.waitForEvent("download");
    await page.getByRole("button", { name: /Unduh/ }).click();
    const text = readFileSync(((await (await md).path()))!, "utf8");
    expect(text).toContain("# Rapat kirim task");
    expect(text).toContain("## Task");
    expect(text).toContain("## Transkrip");
  } finally {
    srv.close();
  }
});
