import { writable } from "svelte/store";
import { refreshAll } from "$app/navigation";
import { isNative } from "#lib/platform.ts";
import { apiBase } from "#lib/api/client.ts";
import { accessToken, clearTokens, storeTokens } from "#lib/auth/tokens.ts";
import type { LoginResponse, UserOut } from "#lib/types.ts";

const CACHED_USER_KEY = "cached-user";

/** Cache user info to Preferences for offline access (native only). */
async function cacheUser(user: UserOut): Promise<void> {
  if (!isNative()) return;
  try {
    const { Preferences } = await import("@capacitor/preferences");
    await Preferences.set({
      key: CACHED_USER_KEY,
      value: JSON.stringify(user),
    });
  } catch {
    // Best-effort caching
  }
}

/** Retrieve cached user from Preferences (native only). */
export async function getCachedUser(): Promise<UserOut | null> {
  if (!isNative()) return null;
  try {
    const { Preferences } = await import("@capacitor/preferences");
    const { value } = await Preferences.get({ key: CACHED_USER_KEY });
    if (!value) return null;
    return JSON.parse(value) as UserOut;
  } catch {
    return null;
  }
}

interface AuthState {
  user: UserOut | null;
}

function createAuthStore() {
  const { subscribe, set, update } = writable<AuthState>({ user: null });

  return {
    subscribe,
    login: (loginResponse: LoginResponse) => {
      void storeTokens(loginResponse.access_token, loginResponse.refresh_token);
      const { access_token: _a, refresh_token: _r, ...user } = loginResponse;
      void _a;
      void _r;
      set({ user: user as UserOut });
      cacheUser(user as UserOut);
    },
    logout: async () => {
      set({ user: null });
      // The server ends this login — it has to be told which one, so the
      // app's token goes with the request before it is forgotten here.
      // (The browser's cookies go by themselves.)
      const bearer = isNative() ? accessToken() : null;
      if (isNative()) {
        await clearTokens();
        try {
          const { Preferences } = await import("@capacitor/preferences");
          await Preferences.remove({ key: CACHED_USER_KEY });
        } catch {
          // ignore
        }
      }
      try {
        await fetch(`${apiBase()}/auth/logout`, {
          method: "POST",
          headers: bearer ? { Authorization: `Bearer ${bearer}` } : {},
        });
      } catch {
        // Cookie will be cleaned up by hooks.server.ts on next request
      }
      // Rerun the layout loads: page.data.user is cached load output and
      // survives client-side navigation, so without this the app chrome
      // keeps rendering the logged-in shell until a full restart.
      await refreshAll();
    },
    setUser: (user: UserOut) => {
      update((s) => ({ ...s, user }));
      // Keeps the offline-start cache converged on the freshest shape —
      // a cache written by an older login() would otherwise serve an
      // incomplete user until the next login.
      cacheUser(user);
    },
  };
}

export const authStore = createAuthStore();
