import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "e2e-load", timeout: 120_000,
  use: { launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {} },
});
