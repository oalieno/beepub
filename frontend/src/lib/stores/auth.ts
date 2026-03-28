import { writable } from "svelte/store";
import { isNative } from "$lib/platform";
import { apiBase } from "$lib/api/client";
import type { LoginResponse, UserOut } from "$lib/types";

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
      }
      const { access_token, ...user } = loginResponse;
      set({ user: user as UserOut });
    },
    logout: async () => {
      set({ user: null });
      if (isNative()) {
        localStorage.removeItem("token");
      }
      try {
        await fetch(`${apiBase()}/auth/logout`, { method: "POST" });
      } catch {
        // Cookie will be cleaned up by hooks.server.ts on next request
      }
    },
    setUser: (user: UserOut) => {
      update((s) => ({ ...s, user }));
    },
  };
}

export const authStore = createAuthStore();
