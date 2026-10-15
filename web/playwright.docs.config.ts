import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Menghasilkan screenshot README dari UI nyata + backend nyata (mesin "demo", data contoh). Manual:
//   npx playwright test -c playwright.docs.config.ts
const PORT = 18910;
export default defineConfig({
  testDir: "e2e-docs",
  timeout: 120_000,
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 1,
    colorScheme: "light",
    locale: "id-ID",
    timezoneId: "Asia/Jakarta",
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
  webServer: {
    command: `${process.env.REKAMIND_PYTHON ?? "python"} -m rekamind_server`,
    cwd: "../server",
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    env: {
      REKAMIND_PORT: String(PORT), REKAMIND_AUTH: "none", REKAMIND_ENGINES: "demo",
      REKAMIND_DATA_DIR: join(tmpdir(), `rekamind-docs-${Date.now()}`),
      REKAMIND_WEB_DIR: "../web/dist", REKAMIND_WORKER_POLL_SECONDS: "0.2",
      REKAMIND_INTEGRATIONS_ALLOW_PRIVATE: "true",
    },
  },
});
