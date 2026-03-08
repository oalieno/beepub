import { writable } from "svelte/store";

export type ToastType = "success" | "error" | "info" | "warning";

export interface Toast {
  id: string;
  message: string;
  type: ToastType;
}

function createToastStore() {
  const { subscribe, update } = writable<Toast[]>([]);

  function add(message: string, type: ToastType = "info") {
    const id = Math.random().toString(36).slice(2);
    update((toasts) => [...toasts, { id, message, type }]);
    setTimeout(() => remove(id), 3000);
  }

  function remove(id: string) {
    update((toasts) => toasts.filter((t) => t.id !== id));
  }

  return {
    subscribe,
    success: (message: string) => add(message, "success"),
    error: (message: string) => add(message, "error"),
    info: (message: string) => add(message, "info"),
    warning: (message: string) => add(message, "warning"),
    remove,
  };
}

export const toastStore = createToastStore();
