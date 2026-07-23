// Whether the on-screen keyboard is open — bottom-fixed chrome (tab
// bars, action bars) hides while it is, mimicking native iOS where the
// keyboard covers the tab bar.
//
// In the Capacitor app the webview runs in the default `native` resize
// mode: the keyboard shrinks window.innerHeight and visualViewport
// together, so viewport heuristics never trip. The Keyboard plugin
// events are the authority there; the visualViewport heuristic stays as
// the mobile-web fallback (Safari shrinks only the visual viewport).
import { readable } from "svelte/store";

import { isNative } from "$lib/platform";

export const keyboardVisible = readable(false, (set) => {
  if (typeof window === "undefined") return;

  if (isNative()) {
    let cleanup: (() => void) | null = null;
    let stopped = false;
    import("@capacitor/keyboard").then(({ Keyboard }) => {
      if (stopped) return;
      const show = Keyboard.addListener("keyboardWillShow", () => set(true));
      const hide = Keyboard.addListener("keyboardWillHide", () => set(false));
      cleanup = () => {
        show.then((h) => h.remove());
        hide.then((h) => h.remove());
      };
    });
    return () => {
      stopped = true;
      cleanup?.();
    };
  }

  const viewport = window.visualViewport;
  if (!viewport) return;
  const onResize = () => set(viewport.height < window.innerHeight * 0.75);
  viewport.addEventListener("resize", onResize);
  return () => viewport.removeEventListener("resize", onResize);
});
