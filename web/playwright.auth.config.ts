import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Real browser + real Rekamind (Google login mode) + a real HTTP identity provider that signs real
// RS256 tokens. Nothing about the login flow is mocked on the Rekamind side.
const APP = 18970, IDP = 18971;
const py = process.env.REKAMIND_PYTHON ?? "python";
export default defineConfig({
  testDir: "e2e-auth",
  timeout: 45_000,
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${APP}`,
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
  webServer: [
    { command: `${py} run_mock_idp.py --port ${IDP} --redirect http://127.0.0.1:${APP}/auth/callback`, cwd: "../server/tests", url: `http://127.0.0.1:${IDP}/.well-known/openid-configuration`, reuseExistingServer: false },
    {
      command: `${py} -m rekamind_server`,
      cwd: "../server",
      url: `http://127.0.0.1:${APP}/api/health`,
      reuseExistingServer: false,
      env: {
        REKAMIND_AUTH: "google", REKAMIND_PORT: String(APP), REKAMIND_HOST: "127.0.0.1",
        REKAMIND_PUBLIC_URL: `http://127.0.0.1:${APP}`, REKAMIND_GOOGLE_CLIENT_ID: "cid", REKAMIND_GOOGLE_CLIENT_SECRET: "csecret",
        REKAMIND_OIDC_ISSUER: `http://127.0.0.1:${IDP}`, REKAMIND_SUPERADMINS: "boss@kantor.id", REKAMIND_ALLOWED_DOMAINS: "kantor.id",
        REKAMIND_ENGINES: "fake", REKAMIND_WORKER_POLL_SECONDS: "0.2", REKAMIND_WEB_DIR: "../web/dist",
        REKAMIND_DATA_DIR: join(tmpdir(), `rekamind-e2e-auth-${Date.now()}`),
      },
    },
  ],
});
