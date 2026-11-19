/**
 * Where the app keeps its login.
 *
 * On the web the login is two HttpOnly cookies and none of this applies.
 * The app keeps the tokens itself and sends them in headers.
 *
 * It keeps them in two places. `localStorage` is the working copy: it
 * can be read without waiting, which every request needs. But the system
 * may clear a web view's storage (when the device runs short of space),
 * and that used to sign the person out for no reason they could see. So
 * each token is also written to Preferences — the app's own settings,
 * which the system leaves alone — and put back from there at start-up
 * if the working copy has gone.
 */
import { isNative } from "#lib/platform.ts";

const ACCESS = "token";
const REFRESH = "refresh_token";
const KEPT = { [ACCESS]: "auth-token", [REFRESH]: "auth-refresh-token" };

// Loaded once. (Held inside an object: a Capacitor plugin answers to any
// property name, `then` included, so a promise must never resolve to the
// plugin itself — it would be taken for another promise and never settle.)
let loaded: Promise<{
  store: typeof import("@capacitor/preferences").Preferences;
}> | null = null;

function preferences() {
  loaded ??= import("@capacitor/preferences").then((module) => ({
    store: module.Preferences,
  }));
  return loaded;
}

async function keep(name: keyof typeof KEPT, value: string | null) {
  try {
    const { store } = await preferences();
    if (value === null) await store.remove({ key: KEPT[name] });
    else await store.set({ key: KEPT[name], value });
  } catch {
    // The working copy still holds it; only the safety copy is missing.
  }
}

export function accessToken(): string | null {
  return localStorage.getItem(ACCESS);
}

export function refreshToken(): string | null {
  return localStorage.getItem(REFRESH);
}

/** A new login. The working copy is written before this returns; the
 *  promise is the safety copy. */
export function storeTokens(access: string, refresh: string): Promise<void> {
  if (!isNative()) return Promise.resolve();
  localStorage.setItem(ACCESS, access);
  localStorage.setItem(REFRESH, refresh);
  return Promise.all([keep(ACCESS, access), keep(REFRESH, refresh)]).then(
    () => undefined,
  );
}

/** The access token has been renewed. */
export function storeAccessToken(access: string): Promise<void> {
  if (!isNative()) return Promise.resolve();
  localStorage.setItem(ACCESS, access);
  return keep(ACCESS, access);
}

/** Signed out. */
export async function clearTokens(): Promise<void> {
  if (!isNative()) return;
  localStorage.removeItem(ACCESS);
  localStorage.removeItem(REFRESH);
  await Promise.all([keep(ACCESS, null), keep(REFRESH, null)]);
}

/** At start-up: put back whatever the working copy has lost. A login
 *  from before the safety copy existed is copied into it. */
export async function restoreTokens(): Promise<void> {
  if (!isNative()) return;
  let store;
  try {
    ({ store } = await preferences());
  } catch {
    return;
  }
  for (const name of [ACCESS, REFRESH] as const) {
    try {
      const working = localStorage.getItem(name);
      const { value: kept } = await store.get({ key: KEPT[name] });
      if (!working && kept) localStorage.setItem(name, kept);
      else if (working && working !== kept) await keep(name, working);
    } catch {
      // Leave this one as it is.
    }
  }
}
