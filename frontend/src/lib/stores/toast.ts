import { writable } from "svelte/store";

export type ToastType = "success" | "error" | "info" | "warning";

export interface ToastAction {
  label: string;
  onclick: () => void;
}

export interface Toast {
  id: string;
  message: string;
  type: ToastType;
  action?: ToastAction;
}

function createToastStore() {
  const { subscribe, update } = writable<Toast[]>([]);

  function add(
    message: string,
    type: ToastType = "info",
    opts?: { action?: ToastAction; duration?: number },
  ) {
    const id = Math.random().toString(36).slice(2);
    update((toasts) => [
      ...toasts,
      { id, message, type, action: opts?.action },
    ]);
    const duration =
      opts?.duration ?? (type === "error" || type === "warning" ? null : 3000);
    if (duration) setTimeout(() => remove(id), duration);
    return id;
  }

  function remove(id: string) {
    update((toasts) => toasts.filter((t) => t.id !== id));
  }

  return {
    subscribe,
    success: (
      message: string,
      opts?: { action?: ToastAction; duration?: number },
    ) => add(message, "success", opts),
    error: (
      message: string,
      opts?: { action?: ToastAction; duration?: number },
    ) => add(message, "error", opts),
    info: (
      message: string,
      opts?: { action?: ToastAction; duration?: number },
    ) => add(message, "info", opts),
    warning: (
      message: string,
      opts?: { action?: ToastAction; duration?: number },
    ) => add(message, "warning", opts),
    remove,
  };
}

export const toastStore = createToastStore();
