/**
 * Reactive connectivity store for Capacitor.
 *
 * Two independent signals feed `isOnline`:
 * - networkConnected: the device has a network (@capacitor/network)
 * - serverReachable: the configured API server actually answers, tracked
 *   from fetch failures in the api client. A reachable internet with an
 *   unreachable server (NAS powered off, wrong network) must behave
 *   exactly like being offline — only downloaded content is usable.
 *
 * Recovery paths (iOS suspends JS timers in the background, and the
 * network plugin can fire "connected" before DNS is actually usable, so
 * no single mechanism is enough):
 * - a probe burst (0s/3s/10s) whenever the network reports back
 * - the same burst when the app returns to the foreground
 * - a 20s interval while unreachable
 * - checkServerNow() for an explicit user-triggered retry
 *
 * No-op on web (always reports online): there the app itself is served
 * by the same server, so "server down" means the page never loaded.
 */
import { writable, derived, get } from "svelte/store";
import { isNative } from "$lib/platform";

export const networkConnected = writable(true);
const serverReachable = writable(true);

export const isOnline = derived(
  [networkConnected, serverReachable],
  ([network, server]) => network && server,
);

let initialized = false;
let probeTimer: ReturnType<typeof setInterval> | null = null;
let burstTimers: ReturnType<typeof setTimeout>[] = [];

export async function initNetworkWatcher(): Promise<void> {
  if (initialized || !isNative()) return;
  initialized = true;

  const { Network } = await import("@capacitor/network");
  const status = await Network.getStatus();
  networkConnected.set(status.connected);

  Network.addListener("networkStatusChange", (s) => {
    networkConnected.set(s.connected);
    if (s.connected && !get(serverReachable)) {
      probeBurst();
    }
  });

  // App returning to the foreground: suspended timers may not have run
  // and networkStatusChange events may have been missed — re-read the
  // network state and probe.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    void Network.getStatus().then((s) => {
      networkConnected.set(s.connected);
      if (s.connected && !get(serverReachable)) {
        probeBurst();
      }
    });
  });
}

export function getIsOnline(): boolean {
  return get(networkConnected) && get(serverReachable);
}

/**
 * User-triggered connectivity check (the retry button on offline
 * screens). Re-reads the device network state, probes the server once,
 * and returns whether the app is online afterwards.
 */
export async function checkServerNow(): Promise<boolean> {
  if (!isNative()) return true;
  try {
    const { Network } = await import("@capacitor/network");
    const status = await Network.getStatus();
    networkConnected.set(status.connected);
  } catch {
    // plugin unavailable — trust the current value
  }
  if (get(networkConnected) && !get(serverReachable)) {
    await probeServer();
  }
  return getIsOnline();
}

/** Called by the api client whenever the server answered (any HTTP status). */
export function reportServerReachable(): void {
  if (!get(serverReachable)) {
    serverReachable.set(true);
  }
  stopProbe();
}

/** Called by the api client when a request failed at the network level. */
export function reportServerUnreachable(): void {
  if (!isNative()) return;
  if (get(serverReachable)) {
    serverReachable.set(false);
  }
  startProbe();
}

async function probeServer(): Promise<void> {
  // Dynamic import to avoid a static cycle with the api client.
  const { apiBase } = await import("$lib/api/client");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const res = await fetch(`${apiBase()}/health`, {
      signal: controller.signal,
    });
    if (res.ok) {
      reportServerReachable();
    }
  } catch {
    // still unreachable — keep probing
  } finally {
    clearTimeout(timeout);
  }
}

/** Probe now, then again shortly after — right after a network change
 *  iOS often reports connected before name resolution actually works. */
function probeBurst(): void {
  for (const t of burstTimers) clearTimeout(t);
  burstTimers = [];
  void probeServer();
  for (const delay of [3000, 10000]) {
    burstTimers.push(
      setTimeout(() => {
        if (!get(serverReachable) && get(networkConnected)) {
          void probeServer();
        }
      }, delay),
    );
  }
}

function startProbe(): void {
  if (probeTimer) return;
  probeTimer = setInterval(() => {
    if (get(networkConnected)) {
      void probeServer();
    }
  }, 20000);
}

function stopProbe(): void {
  if (probeTimer) {
    clearInterval(probeTimer);
    probeTimer = null;
  }
  for (const t of burstTimers) clearTimeout(t);
  burstTimers = [];
}
