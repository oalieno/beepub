/**
 * Illustration overlay rendering for the epub reader.
 *
 * Renders clickable gradient overlays on top of text ranges that have
 * associated AI-generated illustrations.
 */

import type { IllustrationOut } from "$lib/types";

const OVERLAY_ID = "beepub-illustration-overlay";
const GRADIENT =
  "linear-gradient(135deg, rgba(168,85,247,0.30), rgba(59,130,246,0.30), rgba(236,72,153,0.30))";

/** Extract spine index from a CFI string. e.g. "epubcfi(/6/28!/4/2...)" → 13 */
export function cfiSpineIndex(cfi: string): number {
  const m = cfi.match(/^epubcfi\(\/6\/(\d+)/);
  return m ? Math.floor(parseInt(m[1], 10) / 2) - 1 : -1;
}

/** Deduplicate overlapping rects — discard the larger when overlap > 50% of smaller */
function deduplicateRects(rects: DOMRect[]): DOMRect[] {
  const nonEmpty = rects.filter((r) => r.width > 0 && r.height > 0);
  const discard = new Set<number>();
  for (let i = 0; i < nonEmpty.length; i++) {
    if (discard.has(i)) continue;
    for (let j = i + 1; j < nonEmpty.length; j++) {
      if (discard.has(j)) continue;
      const a = nonEmpty[i],
        b = nonEmpty[j];
      const ox = Math.max(
        0,
        Math.min(a.right, b.right) - Math.max(a.left, b.left),
      );
      const oy = Math.max(
        0,
        Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top),
      );
      const overlap = ox * oy;
      if (overlap <= 0) continue;
      const areaA = a.width * a.height;
      const areaB = b.width * b.height;
      const smaller = Math.min(areaA, areaB);
      if (overlap > smaller * 0.5) {
        discard.add(areaA >= areaB ? i : j);
      }
    }
  }
  return nonEmpty.filter((_r, idx) => !discard.has(idx));
}

function ensureOverlayRoot(contents: any): HTMLDivElement | null {
  const doc = contents?.document;
  if (!doc?.body) return null;

  let root = doc.getElementById(OVERLAY_ID) as HTMLDivElement | null;
  if (!root) {
    root = doc.createElement("div") as HTMLDivElement;
    root.id = OVERLAY_ID;
    root.style.cssText =
      "position:absolute;top:0;left:0;width:0;height:0;overflow:visible;pointer-events:none;z-index:9998;writing-mode:horizontal-tb;";
    doc.body.appendChild(root);
  }
  return root;
}

/** Render illustration overlays for all visible views */
export function updateIllustrationOverlays(
  rendition: any,
  illustrations: IllustrationOut[],
  onillustrationclick?: (ill: IllustrationOut) => void,
) {
  if (!rendition) return;

  const viewsResult = rendition.views?.();
  const views: any[] =
    viewsResult?._views ?? (Array.isArray(viewsResult) ? viewsResult : []);
  if (views.length === 0) return;

  for (const view of views) {
    const contents = view?.contents;
    const doc = contents?.document;
    const win = contents?.window;
    if (!doc || !win) continue;

    const viewSpineIndex: number = view.index ?? view.section?.index ?? -1;

    const root = ensureOverlayRoot(contents);
    if (!root) continue;
    root.innerHTML = "";

    const scrollX = win.scrollX || 0;
    const scrollY = win.scrollY || 0;

    for (const ill of illustrations) {
      if (ill.status !== "completed" && ill.status !== "generating") continue;

      const illSpine = cfiSpineIndex(ill.cfi_range);
      if (viewSpineIndex >= 0 && illSpine !== viewSpineIndex) continue;

      try {
        const range = contents.range(ill.cfi_range);
        if (!range) continue;

        const allRects = Array.from(range.getClientRects()) as DOMRect[];
        const rects = deduplicateRects(allRects);
        const isGenerating = ill.status === "generating";

        for (const rect of rects) {
          const overlay = doc.createElement("button");
          overlay.type = "button";
          overlay.title = isGenerating ? "Generating..." : "View illustration";
          overlay.setAttribute("aria-label", overlay.title);
          overlay.style.cssText = [
            "position:absolute",
            `left:${rect.left + scrollX}px`,
            `top:${rect.top + scrollY}px`,
            `width:${rect.width}px`,
            `height:${rect.height}px`,
            `background:${GRADIENT}`,
            "border:none",
            "border-radius:4px",
            "padding:0",
            "margin:0",
            isGenerating ? "cursor:wait" : "cursor:pointer",
            "pointer-events:auto",
            "box-shadow: inset 0 0 0 1px rgba(255,255,255,0.10)",
            "mix-blend-mode:multiply",
            "touch-action:manipulation",
            isGenerating
              ? "animation:beepub-pulse 2s ease-in-out infinite"
              : "",
          ].join(";");
          if (!isGenerating) {
            overlay.addEventListener("click", (e: Event) => {
              e.preventDefault();
              e.stopPropagation();
              onillustrationclick?.(ill);
            });
          }
          root.appendChild(overlay);
        }

        if (isGenerating && !doc.getElementById("beepub-pulse-style")) {
          const style = doc.createElement("style");
          style.id = "beepub-pulse-style";
          style.textContent = `@keyframes beepub-pulse { 0%,100% { opacity:1 } 50% { opacity:0.4 } }`;
          doc.head.appendChild(style);
        }
      } catch {}
    }
  }
}
