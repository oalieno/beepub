/**
 * Touch paging for non-iOS devices (Android, desktop touch), where native
 * text selection stays enabled: a horizontal swipe turns the page unless
 * text is selected. Engine-agnostic — attach to a section document. iOS
 * goes through ios-touch-selection.ts, whose state machine arbitrates the
 * same gesture against long-press selection.
 *
 * Gesture geometry is measured in screen coordinates: a page that
 * follows the finger moves the frame the events come from, so client
 * coordinates would shift under a still finger by exactly the distance
 * just moved and feed that back as movement (the page then oscillates).
 */

export const isIOSDevice = (): boolean =>
  typeof navigator !== "undefined" &&
  (/iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1));

export interface SwipeCallbacks {
  onswipeleft: () => void;
  onswiperight: () => void;
  /** Finger-follow paging (optional): see ios-touch-selection.ts. */
  onswipemove?: (dx: number, dy: number) => void;
  /** Return true when the gesture was consumed (the page followed the
   *  finger and settles by itself);
   *  otherwise the threshold swipe fires onswipeleft/right. */
  onswipeend?: (vx: number, vy: number) => boolean | void;
  /** The gesture will get no onswipeend (the touch was cancelled, a
   *  selection took it over, a new touch began): whatever followed the
   *  finger goes back. */
  onswipecancel?: () => void;
  /** A quick tap that was not a swipe (the caller checks for selection). */
  ontap?: () => void;
}

const SWIPE_THRESHOLD = 50;
const MOVE_THRESHOLD = 10;

export function setupSwipeNavigation(
  doc: Document,
  win: Window,
  callbacks: SwipeCallbacks,
) {
  let startX = 0;
  let startY = 0;
  let lastX = 0;
  let lastY = 0;
  let lastT = 0;
  let vx = 0;
  let vy = 0;
  let swiping = false;
  let active = false;

  const hasSelection = () => {
    const sel = win.getSelection();
    return !!sel && !sel.isCollapsed && sel.toString().trim() !== "";
  };

  doc.addEventListener(
    "touchstart",
    (e: TouchEvent) => {
      // A gesture that never got its release must not leave the page
      // where the finger dropped it.
      callbacks.onswipecancel?.();
      if (e.touches.length !== 1) {
        active = false;
        return;
      }
      const t = e.touches[0];
      startX = lastX = t.screenX;
      startY = lastY = t.screenY;
      lastT = e.timeStamp;
      vx = vy = 0;
      swiping = false;
      active = true;
    },
    { passive: true },
  );

  doc.addEventListener(
    "touchmove",
    (e: TouchEvent) => {
      if (!active) return;
      const t = e.touches[0];
      if (
        !swiping &&
        (Math.abs(t.screenX - startX) > MOVE_THRESHOLD ||
          Math.abs(t.screenY - startY) > MOVE_THRESHOLD)
      ) {
        swiping = true;
      }
      if (swiping && callbacks.onswipemove && !hasSelection()) {
        const dt = Math.max(1, e.timeStamp - lastT);
        const dx = lastX - t.screenX;
        const dy = lastY - t.screenY;
        vx = dx / dt;
        vy = dy / dt;
        lastX = t.screenX;
        lastY = t.screenY;
        lastT = e.timeStamp;
        callbacks.onswipemove(dx, dy);
      }
    },
    { passive: true },
  );

  doc.addEventListener(
    "touchend",
    (e: TouchEvent) => {
      if (!active) return;
      active = false;
      const endX = e.changedTouches[0]?.screenX ?? startX;
      const dx = endX - startX;
      if (!swiping) {
        callbacks.ontap?.();
        return;
      }
      // Don't turn the page out from under a selection in progress.
      if (hasSelection()) {
        callbacks.onswipecancel?.();
        return;
      }
      if (callbacks.onswipeend?.(vx, vy)) {
        // consumed by finger-follow paging
      } else if (Math.abs(dx) > SWIPE_THRESHOLD) {
        if (dx < 0) callbacks.onswipeleft();
        else callbacks.onswiperight();
      }
    },
    { passive: true },
  );
  doc.addEventListener("touchcancel", () => {
    active = false;
    callbacks.onswipecancel?.();
  });
}
