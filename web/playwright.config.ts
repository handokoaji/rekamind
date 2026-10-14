import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PORT = 18900;
// Point at an already-running deployment (e.g. the Docker image) instead of starting a dev backend.
const EXTERNAL = process.env.E2E_BASE_URL;
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  workers: 1,
  use: {
    baseURL: EXTERNAL ?? `http://127.0.0.1:${PORT}`,
    // CI images ship their own Chromium; locally `npx playwright install chromium` is enough.
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
  // The real backend (fake engines, fresh data dir) serving the real production build.
  webServer: EXTERNAL ? undefined : {
    command: `${process.env.REKAMIND_PYTHON ?? "python"} -m rekamind_server`,
    cwd: "../server",
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    env: {
      REKAMIND_PORT: String(PORT),
      REKAMIND_ENGINES: "fake",
      REKAMIND_DATA_DIR: join(tmpdir(), `rekamind-e2e-${Date.now()}`),
      REKAMIND_WEB_DIR: "../web/dist",
      REKAMIND_WORKER_POLL_SECONDS: "0.2",
    },
  },
});
