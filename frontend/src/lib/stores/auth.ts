import { writable } from "svelte/store";
import { isNative } from "$lib/platform";
import { apiBase } from "$lib/api/client";
import type { LoginResponse, UserOut } from "$lib/types";

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
      if (isNative()) {
        localStorage.setItem("token", loginResponse.access_token);
        localStorage.setItem("refresh_token", loginResponse.refresh_token);
      }
      const { access_token: _a, refresh_token: _r, ...user } = loginResponse;
      void _a;
      void _r;
      set({ user: user as UserOut });
      cacheUser(user as UserOut);
    },
    logout: async () => {
      set({ user: null });
      if (isNative()) {
        localStorage.removeItem("token");
        localStorage.removeItem("refresh_token");
        try {
          const { Preferences } = await import("@capacitor/preferences");
          await Preferences.remove({ key: CACHED_USER_KEY });
        } catch {
          // ignore
        }
      }
      try {
        await fetch(`${apiBase()}/auth/logout`, { method: "POST" });
      } catch {
        // Cookie will be cleaned up by hooks.server.ts on next request
      }
    },
    setUser: (user: UserOut) => {
      update((s) => ({ ...s, user }));
      cacheUser(user);
    },
  };
}

export const authStore = createAuthStore();
