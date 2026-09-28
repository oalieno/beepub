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

// Long enough to be read after the eye comes back from where the user
// acted: a base plus reading time for the text, capped.
const MIN_TOAST_DURATION = 4000;
const MAX_TOAST_DURATION = 8000;
const PER_CHAR_MS = 60;

function readingTime(message: string): number {
  return Math.min(
    MAX_TOAST_DURATION,
    Math.max(MIN_TOAST_DURATION, 2000 + message.length * PER_CHAR_MS),
  );
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
      opts?.duration ??
      (type === "error" || type === "warning" ? null : readingTime(message));
    if (duration) {
      timers.set(id, { remaining: duration, started: Date.now() });
      schedule(id);
    }
    return id;
  }

  // Auto-dismiss timers, paused while the pointer rests on a toast.
  const timers = new Map<
    string,
    {
      remaining: number;
      started: number;
      handle?: ReturnType<typeof setTimeout>;
    }
  >();

  function schedule(id: string) {
    const timer = timers.get(id);
    if (!timer) return;
    timer.started = Date.now();
    timer.handle = setTimeout(() => remove(id), timer.remaining);
  }

  function pause(id: string) {
    const timer = timers.get(id);
    if (!timer?.handle) return;
    clearTimeout(timer.handle);
    timer.handle = undefined;
    timer.remaining = Math.max(
      0,
      timer.remaining - (Date.now() - timer.started),
    );
  }

  function resume(id: string) {
    const timer = timers.get(id);
    if (timer && !timer.handle) schedule(id);
  }

  function remove(id: string) {
    const timer = timers.get(id);
    if (timer?.handle) clearTimeout(timer.handle);
    timers.delete(id);
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
    pause,
    resume,
  };
}

export const toastStore = createToastStore();
