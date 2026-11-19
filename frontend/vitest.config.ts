/**
 * Unit tests: plain functions, run in Node with no browser and no stack
 * (`pnpm test:unit`). What needs a page, a reader or a server is an e2e
 * spec (`e2e/`), not one of these.
 *
 * Kept apart from vite.config.ts on purpose: none of the app's build
 * (SvelteKit, the service worker, Capacitor) is needed to call a function.
 * `#lib/...` resolves through the `imports` field of package.json.
 */
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
