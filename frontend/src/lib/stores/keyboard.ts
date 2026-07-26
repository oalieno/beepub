// Whether the on-screen keyboard is open — bottom-fixed chrome (tab
// bars, action bars) hides while it is, mimicking native iOS where the
// keyboard covers the tab bar.
//
// In the Capacitor app the webview runs in the default `native` resize
// mode: the keyboard shrinks window.innerHeight and visualViewport
// together, so viewport heuristics never trip. The Keyboard plugin
// events are the authority there; the visualViewport heuristic stays as
// the mobile-web fallback (Safari shrinks only the visual viewport).
//
// The listeners are armed once and never torn down: subscribers come and
// go per-route (the tab bar unmounts entirely on book detail), and a
// subscriber-scoped listener misses a hide event fired during that gap —
// the store then replays a stale `true` to the next subscriber and the
// nav bar stays vanished until the keyboard opens again.
import { writable, type Readable } from "svelte/store";

import { isNative } from "$lib/platform";

const state = writable(false);
let armed = false;

function arm() {
  if (armed || typeof window === "undefined") return;
  armed = true;

  if (isNative()) {
    import("@capacitor/keyboard").then(({ Keyboard }) => {
      Keyboard.addListener("keyboardWillShow", () => state.set(true));
      Keyboard.addListener("keyboardWillHide", () => state.set(false));
    });
    return;
  }

  const viewport = window.visualViewport;
  if (!viewport) return;
  viewport.addEventListener("resize", () =>
    state.set(viewport.height < window.innerHeight * 0.75),
  );
}

export const keyboardVisible: Readable<boolean> = {
  subscribe(run, invalidate) {
    arm();
    return state.subscribe(run, invalidate);
  },
};
