/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { defineConfig } from "vite";

const version: string = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")).version;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { __APP_VERSION__: JSON.stringify(version) },
  server: { proxy: { "/api": process.env.REKAMIND_API ?? "http://127.0.0.1:8787" } },
  build: { sourcemap: false, chunkSizeWarningLimit: 400 },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"], css: false, exclude: ["e2e/**", "e2e-auth/**", "e2e-load/**", "e2e-docs/**", "node_modules/**"] },
});
