import { expect, test } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

// Cross-process: the real Rust binary starts a loopback listener, a real browser signs in at the
// fake Google, the browser is bounced back to the listener, and the binary exchanges the one-time
// code (+ PKCE verifier) for a token that the real backend then accepts.
const IDP = "http://127.0.0.1:18971";
const APP = "http://127.0.0.1:18970";
const REC = process.env.REKAMIND_REC ?? resolve("../recorder/target/debug/rekamind-rec");

function login(): Promise<{ url: Promise<string>; done: Promise<{ code: number | null; token: string; err: string }> }> {
  const p = spawn(REC, ["login", "--server", APP, "--no-browser", "--print-token"]);
  let out = "", err = "";
  let resolveUrl!: (u: string) => void;
  const url = new Promise<string>((r) => { resolveUrl = r; });
  p.stdout.on("data", (d) => { out += d; });
  p.stderr.on("data", (d) => { err += d; const m = /(https?:\/\/\S+)/.exec(err); if (m) resolveUrl(m[1]!); });
  const done = new Promise<{ code: number | null; token: string; err: string }>((r) => p.on("close", (code) => r({ code, token: out.trim(), err })));
  return Promise.resolve({ url, done });
}

async function cliSession(browser: import("@playwright/test").Browser, email: string) {
  const ctx = await browser.newContext();
  await ctx.request.post(`${IDP}/__identity`, { data: { email, sub: `sub-${email}`, name: email.split("@")[0] } });
  const l = await login();
  const page = await ctx.newPage();
  await page.goto(await l.url);
  const r = await l.done;
  await ctx.close();
  return r;
}

test("the command-line recorder signs in through the browser and uploads as that user only", async ({ browser, request }) => {
  const dan = await cliSession(browser, "dan@kantor.id");
  expect(dan.code, dan.err).toBe(0);
  expect(dan.token).toMatch(/^rks_/);

  const me = await request.get(`${APP}/api/me`, { headers: { authorization: `Bearer ${dan.token}` } });
  expect((await me.json()).email).toBe("dan@kantor.id");

  const out = mkdtempSync(join(tmpdir(), "rekamind-cli-"));
  const rec = spawnSync(REC, ["record", "--synthetic", "--duration", "2", "--out", out, "--server", APP, "--token", dan.token, "--title", "Dari CLI Dan"], { encoding: "utf8" });
  expect(rec.status, rec.stderr).toBe(0);

  const mine = await (await request.get(`${APP}/api/meetings`, { headers: { authorization: `Bearer ${dan.token}` } })).json();
  expect(JSON.stringify(mine)).toContain("Dari CLI Dan");

  const eve = await cliSession(browser, "eve@kantor.id");
  expect(eve.code, eve.err).toBe(0);
  const theirs = await (await request.get(`${APP}/api/meetings`, { headers: { authorization: `Bearer ${eve.token}` } })).json();
  expect(JSON.stringify(theirs)).not.toContain("Dari CLI Dan");

  // A bad token is refused, not silently treated as anonymous.
  const bad = await request.get(`${APP}/api/meetings`, { headers: { authorization: "Bearer rks_nope" } });
  expect(bad.status()).toBe(401);
  // And without a token at all the upload cannot happen.
  const noTok = await request.get(`${APP}/api/meetings`);
  expect(noTok.status()).toBe(401);
});
