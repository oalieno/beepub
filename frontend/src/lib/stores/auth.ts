import { writable } from 'svelte/store';
import type { UserOut } from '$lib/types';

interface AuthState {
  user: UserOut | null;
  token: string | null;
}

function createAuthStore() {
  const { subscribe, set, update } = writable<AuthState>({
    user: null,
    token: null,
  });

  return {
    subscribe,
    init: () => {
      if (typeof localStorage === 'undefined') return;
      const token = localStorage.getItem('token');
      const userStr = localStorage.getItem('user');
      if (token && userStr) {
        try {
          const user = JSON.parse(userStr) as UserOut;
          set({ user, token });
        } catch {
          localStorage.removeItem('token');
          localStorage.removeItem('user');
        }
      }
    },
    login: (user: UserOut, token: string) => {
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem('token', token);
        localStorage.setItem('user', JSON.stringify(user));
      }
      set({ user, token });
    },
    logout: () => {
      if (typeof localStorage !== 'undefined') {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
      }
      set({ user: null, token: null });
      // Clear server cookie
      document.cookie = 'token=; Max-Age=0; path=/';
    },
    setUser: (user: UserOut) => {
      update((s) => {
        if (typeof localStorage !== 'undefined') {
          localStorage.setItem('user', JSON.stringify(user));
        }
        return { ...s, user };
      });
    },
  };
}

export const authStore = createAuthStore();
