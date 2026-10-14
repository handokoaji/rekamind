/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": process.env.REKAMIND_API ?? "http://127.0.0.1:8787" } },
  build: { sourcemap: false, chunkSizeWarningLimit: 400 },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"], css: false, exclude: ["e2e/**", "e2e-auth/**", "e2e-load/**", "node_modules/**"] },
});
