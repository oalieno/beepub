/**
 * Device-local reading-time ledger — the app-side half of device-scoped
 * reading activity. Local and kosync-backed books never hit PUT /progress,
 * so the server's live accumulator can't see them; instead the reader
 * ticks this ledger on page turns and the device REPLACEs its own per-day
 * rows via POST /api/activity/sync (idempotent — replays set values, never
 * add). Serverless reading accumulates here and backfills the streak the
 * moment a server is connected.
 *
 * beepub-kind books are deliberately NOT ticked: their saves carry
 * track_activity and the server credits the 'web' device row already.
 */
import { Preferences } from "@capacitor/preferences";
import { get } from "svelte/store";

import { activityApi } from "$lib/api/activity";
import { hasServerUrl } from "$lib/api/client";
import { isNative } from "$lib/platform";
import { getDeviceId } from "$lib/services/deviceId";
import { getIsOnline } from "$lib/services/network";
import { authStore } from "$lib/stores/auth";

const LEDGER_KEY = "reading-ledger";
/** Mirrors the backend accumulator's MAX_READING_SESSION_GAP — a longer
 *  gap means the user walked away, not read. */
const MAX_GAP_MS = 300_000;
const KEEP_DAYS = 60;
const PUSH_DAYS = 30;
const MAX_DAY_SECONDS = 86_400;

type Ledger = Record<string, number>;

let lastTick = 0;
let pushInFlight: Promise<void> | null = null;

/** Device-local calendar date — what the user perceives as "today". */
function localDateISO(d = new Date()): string {
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${month}-${day}`;
}

async function readLedger(): Promise<Ledger> {
  const { value } = await Preferences.get({ key: LEDGER_KEY });
  if (!value) return {};
  try {
    return JSON.parse(value) as Ledger;
  } catch {
    return {};
  }
}

function cutoffISO(days: number): string {
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);
  return localDateISO(cutoff);
}

/** Called by the reader on every user-driven relocation for non-beepub
 *  books. Credits the gap since the previous tick, session-gap capped. */
export async function tickReading(): Promise<void> {
  const now = Date.now();
  const delta = now - lastTick;
  lastTick = now;
  if (delta <= 0 || delta >= MAX_GAP_MS) return;
  const ledger = await readLedger();
  const today = localDateISO();
  ledger[today] = Math.min(
    (ledger[today] ?? 0) + Math.round(delta / 1000),
    MAX_DAY_SECONDS,
  );
  const cutoff = cutoffISO(KEEP_DAYS);
  for (const date of Object.keys(ledger)) {
    if (date < cutoff) delete ledger[date];
  }
  await Preferences.set({ key: LEDGER_KEY, value: JSON.stringify(ledger) });
}

/** Push the recent ledger window. Same preconditions as readingSync's
 *  canSync (private there): native, a server, a user, and reachable. */
export function pushLedger(): Promise<void> {
  if (
    !isNative() ||
    !hasServerUrl() ||
    get(authStore).user === null ||
    !getIsOnline()
  ) {
    return Promise.resolve();
  }
  if (pushInFlight) return pushInFlight;
  pushInFlight = (async () => {
    try {
      const ledger = await readLedger();
      const cutoff = cutoffISO(PUSH_DAYS);
      const entries = Object.entries(ledger)
        .filter(([date]) => date >= cutoff)
        .map(([date, seconds]) => ({
          date,
          seconds: Math.min(seconds, MAX_DAY_SECONDS),
        }));
      if (entries.length === 0) return;
      await activityApi.sync(await getDeviceId(), entries);
    } catch (err) {
      // Next trigger (reconnect, book close, full sync) retries.
      console.warn("readingLedger: push failed", err);
    } finally {
      pushInFlight = null;
    }
  })();
  return pushInFlight;
}
