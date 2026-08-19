/**
 * Server-mode disconnect detection (damped).
 *
 * Server mode needs a connection by definition — when the server is
 * unusable, the (app) layout swaps the page tree for a single
 * disconnect screen (retry / switch to local mode) instead of letting
 * every page grow its own failure state. One surface, so new features
 * can't be offline-broken: offline never renders them.
 *
 * Damping: a dropped device network (airplane mode) is definitive and
 * flips immediately; a bare server failure (NAS restarting, a blip)
 * waits DISCONNECT_DELAY_MS before yanking the user off the page they
 * were on. Recovery is always immediate.
 *
 * Never active on web (no offline concept) or in local mode (zero
 * server traffic there — nothing to disconnect from). The reader lives
 * in its own layout group and deliberately survives the swap: going
 * offline mid-book must never interrupt reading.
 */
import { derived, readable } from "svelte/store";

import { hasServerUrl, isLocalMode } from "$lib/api/client";
import { isNative } from "$lib/platform";
import { isOnline, networkConnected } from "$lib/services/network";

const DISCONNECT_DELAY_MS = 10_000;

export const serverDisconnected = readable(false, (set) => {
  if (!isNative() || isLocalMode()) return;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const unsub = derived(
    [networkConnected, isOnline],
    (values) => values,
  ).subscribe(([network, online]) => {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    // Only `online` dissolves the screen — a recovered device network
    // with an unreachable server stays disconnected.
    if (online || !hasServerUrl()) {
      set(false);
    } else if (!network) {
      set(true);
    } else {
      timer = setTimeout(() => set(true), DISCONNECT_DELAY_MS);
    }
  });
  return () => {
    if (timer) clearTimeout(timer);
    unsub();
  };
});
