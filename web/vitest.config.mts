import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Unit tests for the web app's own logic: `npm run test:unit`. The config is an .mts file so Node always loads
// it as an ES module — Vite and its React plugin are ES modules only, and the branch's .ts config failed with
// ERR_REQUIRE_ESM on Node 20.9.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: {
    environment: "jsdom",            // the checkout attempt lives in sessionStorage
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test/setup.ts"],
  },
});
