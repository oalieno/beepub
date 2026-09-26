/**
 * Back-navigation memory for list pages that fetch after mount.
 *
 * Going back remounts the page, which starts on its skeleton; the
 * browser's scroll restore lands on that short page and clamps, so the
 * reader ends up somewhere random. The page instead hands its data to a
 * SvelteKit snapshot, puts it back without waiting on the network, and
 * the scroll position is restored once that list is on screen.
 */
import { tick } from "svelte";
import type { Snapshot } from "@sveltejs/kit";

export function scrollSnapshot<T>(page: {
  capture: () => T;
  restore: (data: T) => void;
}): Snapshot<{ data: T; scrollY: number }> {
  return {
    capture: () => ({ data: page.capture(), scrollY: window.scrollY }),
    restore: ({ data, scrollY }) => {
      page.restore(data);
      void tick().then(() =>
        requestAnimationFrame(() => window.scrollTo(0, scrollY)),
      );
    },
  };
}
