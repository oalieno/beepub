import { defineConfig, devices } from "@playwright/test";

/**
 * E2E tests run against a full BeePub stack (nginx entrypoint) given by
 * BASE_URL — they are not tied to a dev server. See e2e/README.md for how
 * to start a disposable stack locally; CI starts one with docker compose.
 */
const baseURL = process.env.BASE_URL ?? "http://localhost:8091";

export default defineConfig({
  testDir: "./e2e",
  // One shared stateful instance: specs create global data (users, books).
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  globalSetup: "./e2e/global-setup",
  use: {
    baseURL,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
