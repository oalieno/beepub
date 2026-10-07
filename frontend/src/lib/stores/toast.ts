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
  /** How often the message has come again while it was showing: the
   *  toast on screen answers each time (a small shake, read again). */
  repeats?: number;
  /** For tests to find it by. */
  testId?: string;
}

export interface ToastOptions {
  action?: ToastAction;
  duration?: number;
  testId?: string;
}

// Long enough to be read after the eye comes back from where the user
// acted: a base plus reading time for the text, capped. Errors and
// warnings stay longer than a confirmation, and one that offers an
// action longer still — but every toast leaves by itself: a message
// that has to be tapped away outlives what it was about.
const PER_CHAR_MS = 60;
const DURATION = {
  passing: { min: 4000, max: 8000 },
  problem: { min: 6000, max: 10000 },
};
const PROBLEM_WITH_ACTION_MS = 15000;

function readingTime(message: string, band: { min: number; max: number }) {
  return Math.min(
    band.max,
    Math.max(band.min, band.min - 2000 + message.length * PER_CHAR_MS),
  );
}

function defaultDuration(
  message: string,
  type: ToastType,
  action?: ToastAction,
): number {
  if (type !== "error" && type !== "warning")
    return readingTime(message, DURATION.passing);
  return action
    ? PROBLEM_WITH_ACTION_MS
    : readingTime(message, DURATION.problem);
}

function createToastStore() {
  const { subscribe, update } = writable<Toast[]>([]);
  let current: Toast[] = [];
  subscribe((toasts) => (current = toasts));

  /**
   * Show a toast. `duration` (ms) overrides the default; 0 keeps the
   * toast until it is dismissed. A message that is already showing is
   * not shown twice: the one on screen starts its time over, and shows
   * that it was said again.
   */
  function add(message: string, type: ToastType = "info", opts?: ToastOptions) {
    const duration =
      opts?.duration ?? defaultDuration(message, type, opts?.action);
    const showing = current.find(
      (t) => t.message === message && t.type === type,
    );
    if (showing) {
      const id = showing.id;
      const action = opts?.action ?? showing.action;
      update((toasts) =>
        toasts.map((t) =>
          t.id === id ? { ...t, action, repeats: (t.repeats ?? 0) + 1 } : t,
        ),
      );
      const timer = timers.get(id);
      const paused = !!timer && !timer.handle;
      if (timer?.handle) clearTimeout(timer.handle);
      timers.delete(id);
      if (duration) {
        timers.set(id, { remaining: duration, started: Date.now() });
        // (Under the pointer it stays paused; leaving resumes it.)
        if (!paused) schedule(id);
      }
      return id;
    }
    const id = Math.random().toString(36).slice(2);
    update((toasts) => [
      ...toasts,
      { id, message, type, action: opts?.action, testId: opts?.testId },
    ]);
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
    success: (message: string, opts?: ToastOptions) =>
      add(message, "success", opts),
    error: (message: string, opts?: ToastOptions) =>
      add(message, "error", opts),
    info: (message: string, opts?: ToastOptions) => add(message, "info", opts),
    warning: (message: string, opts?: ToastOptions) =>
      add(message, "warning", opts),
    remove,
    pause,
    resume,
  };
}

export const toastStore = createToastStore();
