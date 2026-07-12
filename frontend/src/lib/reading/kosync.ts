/**
 * External-kosync SyncBackend — a decorator over localSync for serverless
 * local mode. Local Preferences stay the source of truth (every write lands
 * there first); the external server gets a throttled position push and
 * contributes a DevicePosition marker on open, which the reader's existing
 * kosync prompt/jump machinery consumes unchanged.
 *
 * Push state lives at module scope, keyed by digest: closing a book runs
 * the reader's onDestroy save (NOT saveProgressBeacon — that only fires on
 * real webview unloads), so the trailing timer must outlive the backend
 * instance to deliver the final position. Reopening the same book
 * supersedes any stale pending push.
 */
import { get } from "svelte/store";

import { parseKosyncXpointer } from "$lib/components/reader/kosync-xpointer";
import {
  fetchProgress,
  pushProgress,
  type KosyncProgressRecord,
  type KosyncPushPayload,
} from "$lib/kosync/client";
import type { KosyncAccount } from "$lib/services/kosyncAccount";
import type { LocalBookEntry } from "$lib/services/localLibrary";
// Deliberately networkConnected, not getIsOnline(): the latter includes
// BeePub-server reachability, which a third-party sync server doesn't need.
import { networkConnected } from "$lib/services/network";

import { localSync } from "./local";
import type {
  DevicePosition,
  ProgressSave,
  ProgressState,
  SyncBackend,
} from "./sync";

const DEVICE_NAME = "BeePub iOS";
/** Book-open budget for the remote position fetch. */
const PULL_RACE_MS = 3_000;
/** Minimum spacing between pushes — kosync servers see page turns
 *  otherwise (the reader saves behind a 2s debounce). */
const PUSH_WINDOW_MS = 30_000;

interface PushSlot {
  lastPushAt: number;
  lastPushedKey: string | null;
  timer: ReturnType<typeof setTimeout> | null;
  pending: { account: KosyncAccount; payload: KosyncPushPayload } | null;
  inFlight: boolean;
}

const slots = new Map<string, PushSlot>();

function slotFor(digest: string): PushSlot {
  let slot = slots.get(digest);
  if (!slot) {
    slot = {
      lastPushAt: 0,
      lastPushedKey: null,
      timer: null,
      pending: null,
      inFlight: false,
    };
    slots.set(digest, slot);
  }
  return slot;
}

function pushKey(payload: KosyncPushPayload): string {
  return `${payload.progress}|${payload.percentage}`;
}

function schedulePush(
  digest: string,
  account: KosyncAccount,
  payload: KosyncPushPayload,
  opts?: { immediate?: boolean },
): void {
  const slot = slotFor(digest);
  // The reader's 30s backup interval re-saves identical positions all
  // session — don't re-push what the server already has.
  if (pushKey(payload) === slot.lastPushedKey) return;
  slot.pending = { account, payload };
  const elapsed = Date.now() - slot.lastPushAt;
  if (opts?.immediate || (!slot.inFlight && elapsed >= PUSH_WINDOW_MS)) {
    void flush(digest);
  } else if (!slot.timer) {
    slot.timer = setTimeout(
      () => void flush(digest),
      Math.max(0, PUSH_WINDOW_MS - elapsed),
    );
  }
}

async function flush(digest: string): Promise<void> {
  const slot = slots.get(digest);
  if (!slot) return;
  if (slot.timer) {
    clearTimeout(slot.timer);
    slot.timer = null;
  }
  if (slot.inFlight || !slot.pending) return;
  const { account, payload } = slot.pending;
  slot.pending = null;
  // Attempts count whether or not they land — a dead server shouldn't be
  // hammered on every save.
  slot.lastPushAt = Date.now();
  if (!get(networkConnected)) return;
  slot.inFlight = true;
  try {
    await pushProgress(account, payload);
    slot.lastPushedKey = pushKey(payload);
  } catch (err) {
    // Silent by design: push failures mid-read would nag on every window.
    console.debug("kosync push failed", err);
  } finally {
    slot.inFlight = false;
    if (slot.pending && !slot.timer) {
      slot.timer = setTimeout(() => void flush(digest), PUSH_WINDOW_MS);
    }
  }
}

/** Push everything pending right now. Called on reader exit and app
 *  backgrounding — waiting out the throttle window there risks losing the
 *  final position to a task-switcher kill. */
export function flushKosyncPushes(): void {
  for (const digest of slots.keys()) void flush(digest);
}

let visibilityHooked = false;
function hookVisibility(): void {
  if (visibilityHooked || typeof document === "undefined") return;
  visibilityHooked = true;
  // iOS fires visibilitychange before suspending JS — the last reliable
  // moment to get the position out.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushKosyncPushes();
  });
}

/** Skips the push when the canonical percentage is unknown (locations not
 *  ready) — a percentage-less record reads as "no progress" to stock
 *  clients and would clobber a good one. */
function payloadFrom(
  entry: LocalBookEntry,
  account: KosyncAccount,
  state: ProgressSave,
): KosyncPushPayload | null {
  const totalProgression = state.locator.locations.totalProgression;
  if (totalProgression === undefined) return null;
  return {
    document: entry.digest,
    // Chapter-start synthesis when no paragraph xpointer was computable —
    // the same fallback the server-side bridge serves.
    progress:
      state.xpointer ?? `/body/DocFragment[${state.sectionIndex + 1}]/body`,
    percentage: Math.round(totalProgression * 10_000) / 10_000,
    device: DEVICE_NAME,
    device_id: account.deviceId,
  };
}

function toDevicePosition(remote: KosyncProgressRecord): DevicePosition {
  return {
    // Wire scale is 0..1; the marker convention is 0..100.
    percentage: remote.percentage * 100,
    device: remote.device,
    sectionIndex: remote.progress
      ? (parseKosyncXpointer(remote.progress)?.sectionIndex ?? null)
      : null,
    xpointer: remote.progress,
  };
}

export function makeKosyncSync(
  entry: LocalBookEntry,
  account: KosyncAccount,
): SyncBackend {
  hookVisibility();
  // Fired at construction so it overlaps openBook's filesystem read —
  // getProgress is awaited after that. Never rejects.
  const prefetch: Promise<KosyncProgressRecord | null> = get(networkConnected)
    ? fetchProgress(account, entry.digest).catch(() => null)
    : Promise.resolve(null);

  return {
    kind: "kosync",

    // Never throws (a throw would trip the reader's beepub-oriented
    // localStorage fallback) and never persists the remote marker — the
    // Preferences record stays owned by localSync/readingSync.
    async getProgress(bookId: string): Promise<ProgressState | null> {
      const base = await localSync.getProgress(bookId);
      const remote = await Promise.race([
        prefetch,
        new Promise<undefined>((resolve) =>
          setTimeout(() => resolve(undefined), PULL_RACE_MS),
        ),
      ]);
      if (!remote) return base;
      // Own echo: the latest record is this device's previous push —
      // offering a jump to it would prompt on every reopen.
      if (remote.deviceId && remote.deviceId === account.deviceId) return base;
      const devicePosition = toDevicePosition(remote);
      if (base) return { ...base, devicePosition };
      // Never opened here but read elsewhere: a marker-only state makes
      // the reader auto-jump (no local CFI to defend).
      return {
        locator: null,
        fontSize: null,
        sectionIndex: null,
        sectionPage: null,
        sectionPageCounts: null,
        totalPages: null,
        lastReadAt: null,
        devicePosition,
      };
    },

    async saveProgress(bookId: string, state: ProgressSave): Promise<void> {
      await localSync.saveProgress(bookId, state);
      const payload = payloadFrom(entry, account, state);
      if (payload) schedulePush(entry.digest, account, payload);
    },

    saveProgressBeacon(bookId: string, state: ProgressSave): void {
      localSync.saveProgressBeacon(bookId, state);
      const payload = payloadFrom(entry, account, state);
      if (payload)
        schedulePush(entry.digest, account, payload, { immediate: true });
    },

    listHighlights: (bookId) => localSync.listHighlights(bookId),
    createHighlight: (bookId, data) => localSync.createHighlight(bookId, data),
    updateHighlight: (bookId, highlightId, patch) =>
      localSync.updateHighlight(bookId, highlightId, patch),
    deleteHighlight: (bookId, highlightId) =>
      localSync.deleteHighlight(bookId, highlightId),
  };
}
