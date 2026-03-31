/**
 * iOS Touch Selection State Machine
 *
 * Implements custom long-press → word selection → drag-to-extend on iOS,
 * where native selection is disabled to avoid callout menus and unreliable
 * selectionchange events.
 *
 * State transitions: IDLE → WAITING → SELECTING | SWIPING
 */

export interface IOSTouchCallbacks {
  /** Called when a word/range is selected or extended via drag */
  onselect: (range: Range, text: string) => void;
  /** Called on horizontal swipe (dx > threshold) */
  onswipeleft: () => void;
  onswiperight: () => void;
  /** Called on quick tap while menu is visible */
  ontapdismiss: () => void;
  /** Whether the highlight menu is currently shown */
  isMenuVisible: () => boolean;
}

const isCJK = (ch: string) =>
  /[\u3040-\u309F\u30A0-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uAC00-\uD7AF\uF900-\uFAFF]/.test(
    ch,
  );
const isLatinWord = (ch: string) => /[\w\u00C0-\u024F\u0400-\u04FF]/.test(ch);

const SWIPE_THRESHOLD = 50;
const LONG_PRESS_MS = 300;
const MOVE_THRESHOLD = 10;
const DRAG_THRESHOLD = 15;

/**
 * Attach iOS touch selection handlers to an epub iframe document.
 * Injects required styles and CSP, registers touch listeners.
 */
export function setupIOSTouchSelection(
  doc: Document,
  win: Window,
  callbacks: IOSTouchCallbacks,
) {
  // Inject styles to disable native selection, enable it only during programmatic select
  const style = doc.createElement("style");
  style.textContent = [
    "* { -webkit-touch-callout: none !important; }",
    "body { -webkit-user-select: none !important; user-select: none !important; touch-action: pan-x pan-y; }",
    "body.beepub-selecting { -webkit-user-select: text !important; user-select: text !important; }",
    "::selection { background: rgba(59, 130, 246, 0.35) !important; }",
  ].join("\n");
  doc.head.appendChild(style);

  // Block epub inline scripts via CSP
  const cspMeta = doc.createElement("meta");
  cspMeta.setAttribute("http-equiv", "Content-Security-Policy");
  cspMeta.setAttribute("content", "script-src 'none'");
  doc.head.insertBefore(cspMeta, doc.head.firstChild);

  // Selection overlay: draw blue rectangles over selected text
  let overlayContainer: HTMLDivElement | null = null;

  function updateSelectionOverlay(range: Range | null) {
    let overlay: HTMLDivElement;
    if (!overlayContainer) {
      overlay = doc.createElement("div");
      overlay.id = "beepub-sel-overlay";
      overlay.style.cssText =
        "position:absolute;top:0;left:0;pointer-events:none;z-index:9999;";
      doc.body.appendChild(overlay);
      overlayContainer = overlay;
    } else {
      overlay = overlayContainer;
    }
    overlay.innerHTML = "";
    if (!range) return;
    const rects = range.getClientRects();
    const scrollX = win.scrollX || 0;
    const scrollY = win.scrollY || 0;
    for (let i = 0; i < rects.length; i++) {
      const r = rects[i];
      const div = doc.createElement("div");
      div.style.cssText = `position:absolute;left:${r.left + scrollX}px;top:${r.top + scrollY}px;width:${r.width}px;height:${r.height}px;background:rgba(59,130,246,0.3);border-radius:2px;`;
      overlay.appendChild(div);
    }
  }

  // Touch state machine
  type TouchState = "idle" | "waiting" | "selecting" | "swiping";
  let touchState: TouchState = "idle";
  let lpTimer: ReturnType<typeof setTimeout> | null = null;
  let startX = 0;
  let startY = 0;
  let anchorNode: Node | null = null;
  let anchorOffset = 0;
  let didDragSelect = false;
  let currentRange: Range | null = null;
  let currentRangeText = "";

  function selectWordAt(x: number, y: number): Range | null {
    doc.body.classList.add("beepub-selecting");
    const caretRange = doc.caretRangeFromPoint(x, y);
    if (!caretRange) {
      doc.body.classList.remove("beepub-selecting");
      return null;
    }
    const node = caretRange.startContainer;
    if (node.nodeType !== Node.TEXT_NODE) {
      doc.body.classList.remove("beepub-selecting");
      return null;
    }
    const nodeText = node.textContent || "";
    let s = caretRange.startOffset;
    let e = caretRange.startOffset;
    if (s < nodeText.length && isCJK(nodeText[s])) {
      e = s + 1;
    } else if (s < nodeText.length && isLatinWord(nodeText[s])) {
      while (s > 0 && isLatinWord(nodeText[s - 1])) s--;
      while (e < nodeText.length && isLatinWord(nodeText[e])) e++;
    } else if (e < nodeText.length) {
      e++;
    }
    if (s === e) {
      doc.body.classList.remove("beepub-selecting");
      return null;
    }
    caretRange.setStart(node, s);
    caretRange.setEnd(node, e);
    const sel = win.getSelection();
    sel?.removeAllRanges();
    sel?.addRange(caretRange);
    currentRange = caretRange.cloneRange();
    currentRangeText = sel?.toString().trim() ?? "";
    doc.body.classList.remove("beepub-selecting");
    updateSelectionOverlay(caretRange);
    return caretRange;
  }

  function extendSelectionTo(x: number, y: number) {
    if (!anchorNode) return;
    doc.body.classList.add("beepub-selecting");
    const caretRange = doc.caretRangeFromPoint(x, y);
    if (!caretRange) {
      doc.body.classList.remove("beepub-selecting");
      return;
    }
    const sel = win.getSelection();
    if (!sel) {
      doc.body.classList.remove("beepub-selecting");
      return;
    }
    const range = doc.createRange();
    const focusNode = caretRange.startContainer;
    const focusOffset = caretRange.startOffset;
    const cmp = anchorNode.compareDocumentPosition(focusNode);
    const isBefore =
      cmp & Node.DOCUMENT_POSITION_PRECEDING ||
      (anchorNode === focusNode && focusOffset < anchorOffset);
    if (isBefore) {
      range.setStart(focusNode, focusOffset);
      range.setEnd(anchorNode, anchorOffset);
    } else {
      range.setStart(anchorNode, anchorOffset);
      range.setEnd(focusNode, focusOffset);
    }
    sel.removeAllRanges();
    sel.addRange(range);
    currentRange = range.cloneRange();
    currentRangeText = sel.toString().trim();
    doc.body.classList.remove("beepub-selecting");
    updateSelectionOverlay(range);
  }

  function emitCurrentRange() {
    if (currentRange && currentRangeText) {
      callbacks.onselect(currentRange, currentRangeText);
    }
  }

  doc.addEventListener(
    "touchstart",
    (e: TouchEvent) => {
      if (e.touches.length !== 1) return;
      const t = e.touches[0];
      startX = t.clientX;
      startY = t.clientY;
      touchState = "waiting";

      lpTimer = setTimeout(() => {
        lpTimer = null;
        const range = selectWordAt(startX, startY);
        if (range) {
          anchorNode = range.startContainer;
          anchorOffset = range.startOffset;
          touchState = "selecting";
          didDragSelect = false;
          emitCurrentRange();
        } else {
          touchState = "idle";
        }
      }, LONG_PRESS_MS);
    },
    { passive: true },
  );

  doc.addEventListener(
    "touchmove",
    (e: TouchEvent) => {
      const t = e.touches[0];
      if (touchState === "waiting") {
        if (
          Math.abs(t.clientX - startX) > MOVE_THRESHOLD ||
          Math.abs(t.clientY - startY) > MOVE_THRESHOLD
        ) {
          if (lpTimer) {
            clearTimeout(lpTimer);
            lpTimer = null;
          }
          touchState = "swiping";
        }
      } else if (touchState === "selecting") {
        if (
          Math.abs(t.clientX - startX) > DRAG_THRESHOLD ||
          Math.abs(t.clientY - startY) > DRAG_THRESHOLD
        ) {
          didDragSelect = true;
          extendSelectionTo(t.clientX, t.clientY);
        }
      }
    },
    { passive: true },
  );

  doc.addEventListener(
    "touchend",
    (e: TouchEvent) => {
      if (lpTimer) {
        clearTimeout(lpTimer);
        lpTimer = null;
      }
      const endX = e.changedTouches[0]?.clientX ?? startX;
      const dx = endX - startX;

      if (touchState === "selecting") {
        if (didDragSelect) emitCurrentRange();
      } else if (touchState === "swiping") {
        if (Math.abs(dx) > SWIPE_THRESHOLD) {
          if (dx < 0) {
            callbacks.onswipeleft();
          } else {
            callbacks.onswiperight();
          }
        }
      } else if (touchState === "waiting" && callbacks.isMenuVisible()) {
        callbacks.ontapdismiss();
      }
      touchState = "idle";
      anchorNode = null;
    },
    { passive: true },
  );
}
