import { writable } from "svelte/store";
import type { UserOut } from "$lib/types";

interface AuthState {
  user: UserOut | null;
}

function createAuthStore() {
  const { subscribe, set, update } = writable<AuthState>({ user: null });

  return {
    subscribe,
    login: (user: UserOut) => {
      set({ user });
    },
    logout: async () => {
      set({ user: null });
      try {
        await fetch("/api/auth/logout", { method: "POST" });
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
