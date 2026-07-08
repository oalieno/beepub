import fs from "node:fs";
import path from "node:path";
import { request, type FullConfig } from "@playwright/test";
import { ADMIN, ADMIN_STATE, LIBRARY_NAME } from "./helpers";

/**
 * Prepare the target stack through the API, not the UI:
 * - on a fresh instance, register the admin (the first user becomes admin)
 * - log in and persist the cookie state for specs that need a session
 * - make sure one library exists so upload tests have a destination
 *
 * Everything is idempotent — re-running against the same stack is fine.
 *
 * Setup requests authenticate with a Bearer token — no dependency on
 * cookie semantics, which differ between http and https targets.
 */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL!;
  const anon = await request.newContext({ baseURL });

  const status = await anon.get("/api/auth/registration-status");
  if (!status.ok()) {
    throw new Error(
      `Cannot reach ${baseURL} (${status.status()}). Is the e2e stack up? See e2e/README.md.`,
    );
  }
  if ((await status.json()).first_user) {
    const registered = await anon.post("/api/auth/register", { data: ADMIN });
    if (!registered.ok()) {
      throw new Error(
        `Registering the admin failed: ${await registered.text()}`,
      );
    }
  }

  const login = await anon.post("/api/auth/login", { form: ADMIN });
  if (!login.ok()) {
    throw new Error(
      `Login as ${ADMIN.username} failed: ${await login.text()}\n` +
        "The stack was initialized with different credentials — point the " +
        "tests at a fresh stack, or set E2E_ADMIN_USERNAME/E2E_ADMIN_PASSWORD.",
    );
  }
  const { access_token } = await login.json();
  await anon.dispose();

  const api = await request.newContext({
    baseURL,
    extraHTTPHeaders: { Authorization: `Bearer ${access_token}` },
  });
  const libraries = await (await api.get("/api/libraries")).json();
  if (!libraries.some((l: { name: string }) => l.name === LIBRARY_NAME)) {
    const created = await api.post("/api/libraries", {
      data: { name: LIBRARY_NAME },
    });
    if (!created.ok()) {
      throw new Error(`Creating the library failed: ${await created.text()}`);
    }
  }
  await api.dispose();

  // Hand the browser contexts the same session as a cookie (what the web
  // app actually uses).
  fs.mkdirSync(path.dirname(ADMIN_STATE), { recursive: true });
  fs.writeFileSync(
    ADMIN_STATE,
    JSON.stringify({
      cookies: [
        {
          name: "token",
          value: access_token,
          domain: new URL(baseURL).hostname,
          path: "/",
          expires: Math.floor(Date.now() / 1000) + 3600,
          httpOnly: true,
          // Mirror what the backend does: Secure follows the scheme.
          secure: baseURL.startsWith("https"),
          sameSite: "Lax",
        },
      ],
      origins: [],
    }),
  );
}
