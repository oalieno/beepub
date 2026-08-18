/**
 * Offline shell activation for connected-mode native apps.
 *
 * When the server is unusable, the app doesn't grey out surfaces one by
 * one — it collapses to the device shelf (/local) behind a minimal
 * chrome. An allowlist instead of per-surface `requiresOnline` flags:
 * new features are offline-safe by default because offline never
 * renders them at all.
 *
 * Damping: a dropped device network (airplane mode) is definitive and
 * flips the shell immediately; a bare server failure (NAS restarting, a
 * blip) waits SHELL_DELAY_MS before yanking the user out of the page
 * they were on. Recovery is always immediate.
 *
 * Never active on web (no offline concept) or in serverless local mode
 * (its own chrome takes precedence in the layout).
 */
import { derived, readable } from "svelte/store";

import { hasServerUrl } from "$lib/api/client";
import { isNative } from "$lib/platform";
import { isOnline, networkConnected } from "$lib/services/network";

const SHELL_DELAY_MS = 10_000;

export const offlineShell = readable(false, (set) => {
  if (!isNative()) return;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const unsub = derived(
    [networkConnected, isOnline],
    (values) => values,
  ).subscribe(([network, online]) => {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    // Only `online` dissolves the shell — a recovered device network
    // with an unreachable server stays in the shell.
    if (online || !hasServerUrl()) {
      set(false);
    } else if (!network) {
      set(true);
    } else {
      timer = setTimeout(() => set(true), SHELL_DELAY_MS);
    }
  });
  return () => {
    if (timer) clearTimeout(timer);
    unsub();
  };
});
