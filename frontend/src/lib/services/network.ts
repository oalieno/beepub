/**
 * Reactive network status store for Capacitor.
 * Wraps @capacitor/network with a Svelte writable store.
 * No-op on web (always reports online).
 */
import { writable, get } from "svelte/store";
import { isNative } from "$lib/platform";

export const isOnline = writable(true);

let initialized = false;

export async function initNetworkWatcher(): Promise<void> {
  if (initialized || !isNative()) return;
  initialized = true;

  const { Network } = await import("@capacitor/network");
  const status = await Network.getStatus();
  isOnline.set(status.connected);

  Network.addListener("networkStatusChange", (s) => {
    isOnline.set(s.connected);
  });
}

export function getIsOnline(): boolean {
  return get(isOnline);
}
