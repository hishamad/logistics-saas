/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API runs on :8000 (uvicorn); the browser only talks to Vite,
// which forwards /api, so cookies stay same-origin exactly as in production.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "jsdom", restoreMocks: true, unstubGlobals: true, setupFiles: ["src/test/cleanup.ts"] },
});
