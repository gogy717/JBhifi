import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

/**
 * The browser suite runs against its *own* stack, never the developer's (T18).
 *
 * `npm run test:e2e` builds a disposable database from `sql/*.sql` plus the reproducible demo
 * scenarios, starts an API pointed at that database and a Next server that proxies to *that* API, then
 * drives the real storefront and `/admin` in a browser. Nothing here reads or writes `jbhifi`, so a test
 * cannot disturb the shared development data, and a developer's running API is left alone.
 */
const API_PORT = Number(process.env.E2E_API_PORT ?? 8100);
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3100);
const DATABASE = process.env.E2E_DATABASE ?? "jbhifi_e2e_demo";

const webRoot = __dirname;
const repoRoot = path.resolve(webRoot, "..");
const python = process.env.E2E_PYTHON ?? (process.platform === "win32"
  ? path.join(repoRoot, ".venv", "Scripts", "python.exe")
  : path.join(repoRoot, ".venv", "bin", "python"));

export const stack = { API_PORT, WEB_PORT, DATABASE, repoRoot, webRoot, python };

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  // One database, one journey at a time: the specs sign in, buy, refund and cancel in the same rows.
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: repoRoot,
      // The API is ready when it is serving; the database it needs is built by the global setup below
      // (which runs after this probe, so probing /health here would wait for it forever).
      url: `http://127.0.0.1:${API_PORT}/docs`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { ...process.env, POSTGRES_DB: DATABASE, DEMO_MODE: "1" },
    },
    {
      command: `npm run dev -- --port ${WEB_PORT}`,
      cwd: webRoot,
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      // Its own build directory: `next dev` allows one instance per directory, and the developer's
      // storefront may well be running already. NEXT_DIST_DIR also keeps the two caches apart.
      env: {
        ...process.env,
        API_URL: `http://127.0.0.1:${API_PORT}`,
        NEXT_DIST_DIR: ".next/e2e",
      },
    },
  ],
});
