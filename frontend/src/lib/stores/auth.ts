import { writable } from 'svelte/store';
import type { UserOut } from '$lib/types';

interface AuthState {
  user: UserOut | null;
  token: string | null;
}

function setTokenCookie(token: string): void {
  if (typeof document === 'undefined') return;
  const secure = typeof location !== 'undefined' && location.protocol === 'https:' ? '; Secure' : '';
  document.cookie = `token=${encodeURIComponent(token)}; Max-Age=2592000; Path=/; SameSite=Lax${secure}`;
}

function clearTokenCookie(): void {
  if (typeof document === 'undefined') return;
  const secure = typeof location !== 'undefined' && location.protocol === 'https:' ? '; Secure' : '';
  document.cookie = `token=; Max-Age=0; Path=/; SameSite=Lax${secure}`;
}

function getInitialState(): AuthState {
  if (typeof localStorage === 'undefined') return { user: null, token: null };
  const token = localStorage.getItem('token');
  const userStr = localStorage.getItem('user');
  if (token && userStr) {
    try {
      return { user: JSON.parse(userStr) as UserOut, token };
    } catch {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
    }
  }
  return { user: null, token: null };
}

function createAuthStore() {
  const { subscribe, set, update } = writable<AuthState>(getInitialState());

  return {
    subscribe,
    init: () => {
      if (typeof localStorage === 'undefined') return;
      const token = localStorage.getItem('token');
      const userStr = localStorage.getItem('user');
      if (token && userStr) {
        try {
          const user = JSON.parse(userStr) as UserOut;
          setTokenCookie(token);
          set({ user, token });
        } catch {
          localStorage.removeItem('token');
          localStorage.removeItem('user');
          clearTokenCookie();
        }
      }
    },
    login: (user: UserOut, token: string) => {
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem('token', token);
        localStorage.setItem('user', JSON.stringify(user));
      }
      setTokenCookie(token);
      set({ user, token });
    },
    logout: () => {
      if (typeof localStorage !== 'undefined') {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
      }
      set({ user: null, token: null });
      clearTokenCookie();
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
