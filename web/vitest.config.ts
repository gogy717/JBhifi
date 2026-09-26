import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * Unit tests for the shared web state (T05). `npm run test:unit` is the non-watch run.
 *
 * These tests cover browser behaviour the build cannot see: which response is allowed to reach the
 * screen when requests overlap, and how the shared dialogs behave with a keyboard. They mock the
 * network at the API-client boundary, never the race being tested.
 */
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test/setup.ts"],
  },
});
