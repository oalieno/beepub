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

export async function initNetworkWatcher(): Promise<void> {
  if (initialized || !isNative()) return;
  initialized = true;

  const { Network } = await import("@capacitor/network");
  const status = await Network.getStatus();
  networkConnected.set(status.connected);

  Network.addListener("networkStatusChange", (s) => {
    networkConnected.set(s.connected);
    // Coming back online is the moment the server is most likely
    // reachable again — probe immediately instead of waiting a cycle.
    if (s.connected && !get(serverReachable)) {
      void probeServer();
    }
  });
}

export function getIsOnline(): boolean {
  return get(networkConnected) && get(serverReachable);
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
}
