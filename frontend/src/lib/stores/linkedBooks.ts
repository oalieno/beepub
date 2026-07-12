/**
 * Which server books have a copy in the device's local library — the
 * reverse view of the local-book link map, for "on this device" badges
 * on server book cards. Native-only by construction: on web the set
 * stays empty and no storage is touched.
 */
import { writable, type Readable } from "svelte/store";

import { isNative } from "$lib/platform";
import { getLocalBookLinks } from "$lib/services/localLibrary";

const store = writable<ReadonlySet<string>>(new Set());
let loaded = false;

/** Re-read the link map. Call after anything that links, unlinks or
 *  removes a local book; harmless to over-call (one Preferences read). */
export async function refreshLinkedBookIds(): Promise<void> {
  if (!isNative()) return;
  try {
    const links = await getLocalBookLinks();
    store.set(new Set(Object.values(links)));
  } catch {
    // keep the previous set
  }
}

/** Server-book ids linked to a local copy. Loads lazily on first use. */
export const linkedServerBookIds: Readable<ReadonlySet<string>> = {
  subscribe(run, invalidate) {
    if (!loaded) {
      loaded = true;
      void refreshLinkedBookIds();
    }
    return store.subscribe(run, invalidate);
  },
};
