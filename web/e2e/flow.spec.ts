import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

function tinyWav(): string {
  const rate = 16000, n = rate; // 1 second of silence
  const buf = Buffer.alloc(44 + n * 2);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write("WAVEfmt ", 8);
  buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(rate, 24); buf.writeUInt32LE(rate * 2, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34);
  buf.write("data", 36); buf.writeUInt32LE(n * 2, 40);
  const p = join(tmpdir(), "rapat-vendor.wav");
  writeFileSync(p, buf);
  return p;
}

test("upload -> process -> name speaker -> review tasks -> export", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Belum ada rapat" })).toBeVisible();
  await page.screenshot({ path: "e2e-shots/01-empty.png", fullPage: true });

  // Upload a recording; the title is prefilled from the file name.
  await page.getByRole("button", { name: "Rapat baru" }).first().click();
  await page.locator('input[type="file"]').setInputFiles(tinyWav());
  await expect(page.getByLabel("Judul rapat")).toHaveValue("rapat vendor");
  await page.getByLabel("Nama Anda di rekaman").fill("Andi");
  await page.screenshot({ path: "e2e-shots/02-upload.png" });
  await page.getByRole("button", { name: "Unggah" }).click();

  // Lands on the meeting; the worker finishes it and the page updates itself.
  await expect(page.getByRole("heading", { name: "rapat vendor" })).toBeVisible();
  await expect(page.getByText("Perlu ditinjau").first()).toBeVisible({ timeout: 15_000 });
  await page.screenshot({ path: "e2e-shots/03-summary.png", fullPage: true });

  // Name a speaker, then reprocess so the assignee gets linked.
  await page.getByRole("tab", { name: "Pembicara" }).click();
  await page.getByLabel("Nama untuk SPEAKER_01").fill("Budi Santoso");
  await page.getByLabel("Nama untuk SPEAKER_01").blur();
  await page.screenshot({ path: "e2e-shots/04-speakers.png", fullPage: true });
  await page.getByRole("button", { name: "memproses ulang rapat" }).click();
  await page.getByRole("button", { name: "Proses ulang", exact: true }).click();
  await expect(page.getByText("Perlu ditinjau").first()).toBeVisible({ timeout: 15_000 });

  await page.getByRole("tab", { name: /Task/ }).click();
  await expect(page.getByLabel("PIC").first()).toHaveValue(/.+/);
  await page.screenshot({ path: "e2e-shots/05-tasks.png", fullPage: true });

  // Confirm everything: the status flips to Selesai without a manual step.
  while (await page.getByRole("button", { name: "Konfirmasi", exact: true }).count()) {
    await page.getByRole("button", { name: "Konfirmasi", exact: true }).first().click();
    await page.waitForTimeout(300);
  }
  await expect(page.getByText("Selesai").first()).toBeVisible();
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Unduh JSON" }).click()]);
  expect(dl.suggestedFilename()).toMatch(/^task-.*\.json$/);

  await page.getByRole("tab", { name: "Transkrip" }).click();
  await page.screenshot({ path: "e2e-shots/06-transcript.png", fullPage: true });

  // Delete with undo from the list.
  await page.goto("/");
  await page.getByRole("button", { name: /^Hapus/ }).click();
  await expect(page.getByRole("heading", { name: "Belum ada rapat" })).toBeVisible();
  await page.getByRole("button", { name: "Urungkan" }).click();
  await expect(page.getByText("rapat vendor")).toBeVisible();
  await page.goto("/task");
  await page.screenshot({ path: "e2e-shots/07-all-tasks.png", fullPage: true });
});
