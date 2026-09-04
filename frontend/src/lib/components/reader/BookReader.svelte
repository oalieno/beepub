<script lang="ts">
  /**
   * BookReader — the thinnest Svelte container around ReaderCore. Mounts
   * the paginator into a full-size div, feeds it theme CSS and layout
   * parameters, forwards relocations, and owns the gesture layer: tap
   * zones, swipe, the page-turn mode, text selection with its menu, and
   * the saved highlights drawn on the section overlayer. Product-shaped
   * state above that (progress, sidebars) is layered on in later gates;
   * this component stays engine-facing.
   *
   * Must sit inside the reader root div: .reader-light / .reader-dark
   * scope the theme tokens the chrome around it uses.
   */
  import { onDestroy, onMount, tick } from "svelte";
  import type {
    Book,
    LayoutParams,
    NavInput,
    PageTurnMode,
    ReaderCore,
    Relocation,
  } from "$lib/reader/core";
  import { AnnotationLayer, type Annotation } from "$lib/reader/annotations";
  import { verifyAnchors } from "$lib/reader/anchor";
  import type { BookSource } from "$lib/reading/source";
  import type { SyncBackend } from "$lib/reading/sync";
  import type { HighlightOut } from "$lib/types";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";
  import HighlightMenu from "./HighlightMenu.svelte";
  import HighlightNoteEditor from "./HighlightNoteEditor.svelte";
  import { sectionIndexFromCfi } from "./highlight-anchor";
  import {
    HIGHLIGHT_COLORS,
    HIGHLIGHT_LINE_COLORS,
    parseHighlightColor,
  } from "./highlight-style";
  import { setupIOSTouchSelection } from "./ios-touch-selection";
  import { isIOSDevice, setupSwipeNavigation } from "./touch-navigation";
  import { snapRangeToWordBounds } from "./word-snap";

  let {
    bookId,
    source,
    sync,
    initialCfi = null,
    fontFamily = "serif",
    fontSize = 16,
    lineHeight = 1.8,
    darkMode = false,
    layout = {},
    pageTurn = "instant",
    onbook,
    onready,
    onerror,
    onrelocate,
    ontap,
    onhighlightschange,
    onbrokenhighlights,
    onshare,
  }: {
    bookId: string;
    source: BookSource;
    /** Where the user's highlights (and, later, progress) live. */
    sync: SyncBackend;
    initialCfi?: string | null;
    fontFamily?: string;
    fontSize?: number;
    lineHeight?: number;
    darkMode?: boolean;
    layout?: LayoutParams;
    pageTurn?: PageTurnMode;
    onbook?: (book: Book) => void;
    /** First section rendered. */
    onready?: () => void;
    onerror?: (error: Error) => void;
    onrelocate?: (location: Relocation) => void;
    /** A plain tap on the page (no selection, no menu) — the chrome toggle. */
    ontap?: () => void;
    onhighlightschange?: (highlights: HighlightOut[]) => void;
    /** Highlights whose anchor no longer resolves and could not be healed. */
    onbrokenhighlights?: (ids: string[]) => void;
    onshare?: (highlight: HighlightOut) => void;
  } = $props();

  let wrapper: HTMLDivElement;
  let container: HTMLDivElement;
  let core: ReaderCore | null = $state(null);
  let destroyed = false;

  // Apple ships no Traditional-Chinese font that rotates punctuation in
  // vertical writing; these ~4KB Noto CJK TC subsets hold only the
  // rotation-class punctuation and its vert forms (see EpubReader.svelte
  // for the full history; rebuild: scripts/build-vpunct-fonts.py). Inert
  // until a font-family list names them — the themed stacks lead with them.
  const VPUNCT_SERIF = "BeePub VPunct Serif";
  const VPUNCT_SANS = "BeePub VPunct Sans";
  const VPUNCT_RANGE =
    "U+2015, U+2026, U+3008-3011, U+3014-301F, U+FF08-FF09, U+FF3B, U+FF3D, U+FF5B, U+FF5D, U+FF5E";
  const SERIF_FONTS = `"${VPUNCT_SERIF}", "Noto Serif CJK TC", "Source Han Serif TC", "Songti TC", "Songti SC", Georgia, "Times New Roman", serif`;
  const SANS_FONTS = `"${VPUNCT_SANS}", "Noto Sans CJK TC", "Source Han Sans TC", "PingFang TC", "PingFang SC", "Microsoft JhengHei", "Microsoft YaHei", system-ui, sans-serif`;

  function fontFaceCss(): string {
    // Absolute URLs: section documents are blob: URLs, so a relative path
    // would resolve against nothing.
    const fonts = window.location.origin + "/fonts";
    return `@font-face {
  font-family: "${VPUNCT_SERIF}";
  src: url("${fonts}/beepub-vpunct-serif.woff2") format("woff2");
  unicode-range: ${VPUNCT_RANGE};
}
@font-face {
  font-family: "${VPUNCT_SANS}";
  src: url("${fonts}/beepub-vpunct-sans.woff2") format("woff2");
  unicode-range: ${VPUNCT_RANGE};
}`;
  }

  function selectionTint() {
    return darkMode
      ? { rgb: "245, 158, 11", opacity: 0.4 }
      : { rgb: "196, 146, 74", opacity: 0.3 };
  }

  // Port of EpubReader's applyTheme() as plain CSS. Sizing the root too
  // makes rem-based book rules follow the setting while the book's own
  // em/% hierarchy is preserved.
  function themeCss(): string {
    const dark = darkMode;
    const tint = selectionTint();
    const darkOverrides = dark
      ? `p, div, span, li, ul, ol, dl, dt, dd, table, tr, td, th, caption, h1, h2, h3, h4, h5, h6, blockquote, pre, code, section, article, aside, figure, figcaption, small, em, strong, b, i, u { color: inherit; }
a { color: #d8a558; }`
      : "";
    return `html { font-size: ${fontSize}px !important; }
body {
  font-family: ${fontFamily === "serif" ? SERIF_FONTS : SANS_FONTS};
  font-size: ${fontSize}px !important;
  line-height: ${lineHeight};
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
  color: ${dark ? "#ece5da" : "#1a1a1a"};
  background: ${dark ? "#171310" : "#ffffff"};
}
${darkOverrides}
::selection { background: rgba(${tint.rgb}, ${tint.opacity}); }`;
  }

  function styles(): [string, string] {
    return [fontFaceCss(), themeCss()];
  }

  // Book CSS that sets font-family on elements (`p { font-family: serif }`
  // is common) bypasses the themed body stack, so those elements never
  // consult the punctuation face. In vertical sections, prepend it to such
  // elements' own stack via inline style — inline wins at any specificity
  // while the book's declared fonts stay intact behind it. Elements that
  // merely inherit are left alone; they already follow the body stack.
  function pinVerticalPunctuation(doc: Document) {
    const win = doc.defaultView;
    if (!win || !doc.body) return;
    const punctFamily = fontFamily === "serif" ? VPUNCT_SERIF : VPUNCT_SANS;
    const pin = (el: Element, parentFonts: string) => {
      for (const child of Array.from(el.children)) {
        const fonts = win.getComputedStyle(child).fontFamily || "";
        if (
          fonts &&
          fonts !== parentFonts &&
          !fonts.includes("BeePub VPunct") &&
          child instanceof win.HTMLElement
        ) {
          child.style.fontFamily = `"${punctFamily}", ${fonts}`;
        }
        pin(child, fonts);
      }
    };
    pin(doc.body, win.getComputedStyle(doc.body).fontFamily || "");
  }

  // ------------------------------------------------------------ paging

  function turn(side: "left" | "right") {
    const c = core;
    if (!c) return;
    dismissMenu();
    void (side === "left" ? c.goLeft() : c.goRight());
  }

  // Tap zones: the left and right quarters of the reader turn the page,
  // the middle is the chrome tap. Decided in the section document from the
  // tap's own click, so they are independent of the page margins (a zero
  // margin used to leave nothing to tap) and never block long-press
  // selection at the edges — the state machine already tells a tap from a
  // hold. Links and saved highlights in a zone still win.
  const TAP_ZONE = 0.25;

  function tapZone(
    clientX: number,
    frame: Element | null,
  ): "left" | "right" | "middle" {
    const wr = wrapper.getBoundingClientRect();
    const frameLeft = frame?.getBoundingClientRect().left ?? wr.left;
    const x = clientX + frameLeft - wr.left;
    if (x < wr.width * TAP_ZONE) return "left";
    if (x > wr.width * (1 - TAP_ZONE)) return "right";
    return "middle";
  }

  function handleKey(e: KeyboardEvent) {
    const c = core;
    if (!c || e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target as HTMLElement | null;
    if (
      t &&
      (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)
    )
      return;
    switch (e.key) {
      case "ArrowLeft":
        e.preventDefault();
        turn("left");
        break;
      case "ArrowRight":
        e.preventDefault();
        turn("right");
        break;
      case "ArrowUp":
      case "PageUp":
        e.preventDefault();
        dismissMenu();
        void c.prev();
        break;
      case "ArrowDown":
      case "PageDown":
      case " ":
        e.preventDefault();
        dismissMenu();
        void c.next();
        break;
    }
  }

  // ---------------------------------------------------------- highlights

  let highlights: HighlightOut[] = $state([]);
  // Anchors that neither resolve nor heal — a jump goes to the section.
  let brokenHighlightIds = new Set<string>();
  let noteEditorHighlight: HighlightOut | null = $state(null);
  let layer: AnnotationLayer | null = null;
  let healAbort: AbortController | null = null;

  // Last-used color+style (raw encoded, e.g. "blue:underline") — the plain
  // highlighter button repeats it, the picker row overrides it. Same key
  // as the current reader: one preference for both.
  const HIGHLIGHT_STYLE_KEY = "reader-highlight-style";
  let lastHighlightRaw = $state("yellow");

  function rememberHighlightRaw(raw: string) {
    lastHighlightRaw = raw;
    try {
      localStorage.setItem(HIGHLIGHT_STYLE_KEY, raw);
    } catch {
      // private mode etc. — losing the preference is fine
    }
  }

  // The stored color string may carry a style suffix ("yellow:underline",
  // see highlight-style.ts); resolve it to what the overlayer paints.
  function annotationOf(h: HighlightOut): Annotation {
    const { color, style } = parseHighlightColor(h.color);
    const palette =
      style === "highlight" ? HIGHLIGHT_COLORS : HIGHLIGHT_LINE_COLORS;
    return {
      key: h.id,
      cfi: h.cfi_range,
      style: { kind: style, color: palette[color] ?? palette.yellow },
    };
  }

  function sectionIndexOf(
    h: Pick<HighlightOut, "cfi_range" | "section_index">,
  ) {
    return h.section_index ?? sectionIndexFromCfi(h.cfi_range);
  }

  function applyHighlights(list: HighlightOut[]) {
    highlights = list;
    layer?.replaceAll(list.map(annotationOf));
    onhighlightschange?.(list);
  }

  /**
   * Verify every highlight's anchor against the book and heal the ones the
   * file rewrite moved: redraw, persist the new anchor, and report the
   * rest as broken so the list can say so.
   */
  async function healHighlights() {
    const c = core;
    const book = c?.book;
    if (!c || !book || highlights.length === 0) return;
    healAbort?.abort();
    const controller = new AbortController();
    healAbort = controller;
    const liveDocs = new Map<number, Document>();
    for (const { index, doc } of c.getContents()) liveDocs.set(index, doc);
    try {
      const report = await verifyAnchors(
        book,
        highlights.map((h) => ({
          id: h.id,
          cfi: h.cfi_range,
          text: h.text,
          prefix: h.prefix,
          suffix: h.suffix,
          sectionIndex: h.section_index,
        })),
        { liveDocs, signal: controller.signal },
      );
      if (controller.signal.aborted || destroyed) return;
      for (const heal of report.healed) {
        const h = highlights.find((x) => x.id === heal.id);
        if (!h) continue;
        h.cfi_range = heal.cfi;
        h.section_index = heal.sectionIndex;
        layer?.set(annotationOf(h));
        // Silent by design: the writeback can 404 when the highlight was
        // deleted elsewhere meanwhile; the healed anchor still draws.
        sync
          .updateHighlight(bookId, heal.id, {
            cfi_range: heal.cfi,
            section_index: heal.sectionIndex,
          })
          .catch(() => {});
      }
      if (report.healed.length) {
        highlights = [...highlights];
        onhighlightschange?.(highlights);
      }
      brokenHighlightIds = new Set(report.broken);
      if (report.broken.length) onbrokenhighlights?.(report.broken);
    } catch (e) {
      console.error(e);
    }
  }

  const QUOTE_CONTEXT = 48;

  /** W3C TextQuoteSelector-style context around a selection, taken from
   *  the boundary text nodes — what re-anchors a highlight whose CFI
   *  stops resolving after the book file is rewritten. */
  function quoteContext(range: Range): { prefix: string; suffix: string } {
    let prefix = "";
    let suffix = "";
    const sc = range.startContainer;
    if (sc.nodeType === Node.TEXT_NODE) {
      const t = sc.textContent ?? "";
      prefix = t.slice(
        Math.max(0, range.startOffset - QUOTE_CONTEXT),
        range.startOffset,
      );
    }
    const ec = range.endContainer;
    if (ec.nodeType === Node.TEXT_NODE) {
      const t = ec.textContent ?? "";
      suffix = t.slice(range.endOffset, range.endOffset + QUOTE_CONTEXT);
    }
    return { prefix, suffix };
  }

  async function handleHighlight(raw?: string): Promise<HighlightOut | null> {
    const cfi = selectedCfi;
    const text = selectedText;
    const prefix = selectedPrefix;
    const suffix = selectedSuffix;
    const index = core?.currentIndex() ?? null;
    dismissMenu();
    if (!cfi || !text) return null;
    const colorRaw = raw ?? lastHighlightRaw;
    rememberHighlightRaw(colorRaw);
    try {
      const created = await sync.createHighlight(bookId, {
        cfi_range: cfi,
        text,
        color: colorRaw,
        prefix: prefix || null,
        suffix: suffix || null,
        section_index: index ?? sectionIndexFromCfi(cfi),
      });
      highlights = [...highlights, created];
      layer?.set(annotationOf(created));
      onhighlightschange?.(highlights);
      toastStore.success(m.highlight_saved());
      return created;
    } catch (e) {
      toastStore.error((e as Error).message);
      return null;
    }
  }

  /** Change color/style of the existing highlight under the menu. */
  async function handleRestyle(raw: string) {
    const target = existingHighlight;
    dismissMenu();
    if (!target || target.color === raw) return;
    rememberHighlightRaw(raw);
    try {
      const updated = await sync.updateHighlight(bookId, target.id, {
        color: raw,
      });
      highlights = highlights.map((h) => (h.id === updated.id ? updated : h));
      layer?.set(annotationOf(updated));
      onhighlightschange?.(highlights);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleNote() {
    if (existingHighlight) {
      const target = existingHighlight;
      dismissMenu();
      noteEditorHighlight = target;
      return;
    }
    // New selection: create the highlight first, then attach the note.
    const created = await handleHighlight();
    if (created) noteEditorHighlight = created;
  }

  async function handleNoteSave(note: string) {
    const target = noteEditorHighlight;
    if (!target) return;
    try {
      // Empty string clears the note (backend excludes only None).
      const updated = await sync.updateHighlight(bookId, target.id, { note });
      highlights = highlights.map((h) => (h.id === updated.id ? updated : h));
      onhighlightschange?.(highlights);
      toastStore.success(m.highlight_note_saved());
      noteEditorHighlight = null;
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function handleShare() {
    const target = existingHighlight;
    dismissMenu();
    if (target) onshare?.(target);
  }

  async function handleRemoveHighlight() {
    const target = existingHighlight;
    dismissMenu();
    if (!target) return;
    try {
      await removeHighlight(target);
      toastStore.success(m.book_highlight_removed());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  /** Delete a highlight: the mark and the list entry go first and come
   *  back if the delete fails (the error is rethrown for the caller). */
  export async function removeHighlight(hl: HighlightOut) {
    const prev = highlights;
    highlights = highlights.filter((h) => h.id !== hl.id);
    layer?.delete(hl.id);
    onhighlightschange?.(highlights);
    try {
      await sync.deleteHighlight(bookId, hl.id);
    } catch (e) {
      highlights = prev;
      layer?.set(annotationOf(hl));
      onhighlightschange?.(highlights);
      throw e;
    }
  }

  /** Jump to a highlight. One known to be un-anchorable jumps to its
   *  section instead. */
  export function displayHighlight(hl: HighlightOut) {
    dismissMenu();
    if (brokenHighlightIds.has(hl.id)) {
      const index = sectionIndexOf(hl);
      if (index != null) return core?.goTo(index);
    }
    return core?.goTo(hl.cfi_range);
  }

  // --------------------------------------------------- selection + menu

  let showMenu = $state(false);
  let menuX = $state(0);
  let menuY = $state(0);
  let menuEl: HTMLDivElement | undefined = $state();
  let menuShownAt = 0;
  // A tap that dismissed the menu (touchend) is followed by the browser's
  // synthesized click: that click must not read as a chrome toggle.
  let menuDismissedAt = 0;
  let selectedText = $state("");
  let selectedRange: Range | null = null;
  let selectedCfi = "";
  let selectedPrefix = "";
  let selectedSuffix = "";
  /** The saved highlight the menu is on (restyle/remove), or null for a
   *  fresh selection. */
  let existingHighlight: HighlightOut | null = $state(null);
  // Height fallbacks before the first render: the single action bar, or
  // the two-pill stack (picker + actions) shown on an existing highlight.
  const MENU_H = 44;
  const MENU_H_STACKED = 96;

  function setClampedMenuPosition(x: number, y: number) {
    const cw = wrapper?.clientWidth ?? window.innerWidth;
    const menuW = menuEl?.offsetWidth ?? 0;
    // Centered via -translate-x-1/2; clamp once the width is measurable.
    menuX =
      menuW > 0 ? Math.max(menuW / 2 + 8, Math.min(cw - menuW / 2 - 8, x)) : x;
    // Above the viewport → show below the selection instead.
    const fallbackH = existingHighlight ? MENU_H_STACKED : MENU_H;
    const menuH = menuEl?.offsetHeight || fallbackH;
    menuY = y < menuH + 8 ? y + menuH + 16 : y;
  }

  /** Show the menu above a range in a section document. Range rects are in
   *  iframe coordinates; the iframe element's rect (which already reflects
   *  the container's scroll) maps them into the wrapper. `existing` is the
   *  saved highlight the range belongs to; a fresh selection that exactly
   *  matches a saved one counts as that one. */
  function showMenuFor(
    doc: Document,
    range: Range,
    text: string,
    existing: HighlightOut | null = null,
  ) {
    const frame = doc.defaultView?.frameElement;
    const fr = frame?.getBoundingClientRect();
    const wr = wrapper.getBoundingClientRect();
    const rect = range.getBoundingClientRect();
    const x = rect.left + rect.width / 2 + (fr?.left ?? 0) - wr.left;
    const y = rect.top - 8 + (fr?.top ?? 0) - wr.top;
    const c = core;
    const index = c?.currentIndex();
    let cfi = "";
    try {
      cfi = c && index != null ? c.cfiOf(index, range) : "";
    } catch {
      cfi = "";
    }
    selectedRange = range;
    selectedText = text;
    selectedCfi = cfi;
    const ctx = quoteContext(range);
    selectedPrefix = ctx.prefix;
    selectedSuffix = ctx.suffix;
    existingHighlight =
      existing ?? highlights.find((h) => h.cfi_range === cfi) ?? null;
    setClampedMenuPosition(x, y);
    showMenu = true;
    menuShownAt = Date.now();
    // The clamp needs the menu's measured size and the menu remounts on
    // every open: tick() resolves after the mount but before paint, so the
    // first frame drawn is already clamped.
    void tick().then(() => {
      if (showMenu) setClampedMenuPosition(x, y);
    });
  }

  function hasLiveSelection(win: Window) {
    const sel = win.getSelection();
    return !!sel && !sel.isCollapsed && sel.toString().trim() !== "";
  }

  /** Non-iOS: the native selection is the source of truth. */
  function tryShowMenuFromSelection(doc: Document, win: Window) {
    if (!hasLiveSelection(win)) return;
    const sel = win.getSelection()!;
    const snapped = snapRangeToWordBounds(sel.getRangeAt(0));
    const text = snapped.toString().trim();
    if (!text) return;
    showMenuFor(doc, snapped, text);
  }

  function clearSelectionIn(doc: Document | undefined) {
    if (!doc) return;
    doc.body?.classList.remove("beepub-selecting");
    doc.defaultView?.getSelection()?.removeAllRanges();
    const overlay = doc.getElementById("beepub-sel-overlay");
    if (overlay) overlay.innerHTML = "";
  }

  function dismissMenu() {
    if (!showMenu && !selectedRange) return;
    menuDismissedAt = Date.now();
    showMenu = false;
    selectedRange = null;
    existingHighlight = null;
    clearSelectionIn(core?.getContents()[0]?.doc);
  }

  async function handleCopy() {
    const text = selectedText;
    dismissMenu();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      toastStore.success(m.highlight_copied());
    } catch {
      toastStore.error(m.highlight_copy_failed());
    }
  }

  // ------------------------------------------------------------ gestures

  /** The saved highlight under a point of the section document, if any. */
  function highlightAt(x: number, y: number) {
    const key = layer?.hitTest(x, y);
    if (!key) return null;
    const hl = highlights.find((h) => h.id === key);
    const range = layer?.rangeOf(key);
    return hl && range ? { hl, range } : null;
  }

  function attachGestures(doc: Document) {
    const win = doc.defaultView;
    if (!win) return;
    const c = core;
    if (!c) return;

    // The click that follows a touch (or a mouse click): a long-press
    // selection's residue is swallowed upstream (capture listener in
    // ios-touch-selection); what reaches here is a deliberate tap — open
    // the menu on a saved highlight, dismiss the menu, or act on its zone.
    doc.addEventListener("click", (e: MouseEvent) => {
      const now = Date.now();
      if (now - menuShownAt < 500 || now - menuDismissedAt < 700) return;
      if (hasLiveSelection(win)) return;
      const hit = highlightAt(e.clientX, e.clientY);
      if (hit) {
        showMenuFor(doc, hit.range, hit.hl.text, hit.hl);
        return;
      }
      if (showMenu) {
        dismissMenu();
        return;
      }
      if ((e.target as Element | null)?.closest?.("a[href]")) return;
      const zone = tapZone(e.clientX, win.frameElement);
      if (zone === "middle") ontap?.();
      else turn(zone);
    });

    const swipe = {
      // Finger moving left pulls in the page on the right.
      onswipeleft: () => turn("right"),
      onswiperight: () => turn("left"),
      onswipemove: (dx: number, dy: number) => {
        if (pageTurn === "follow") c.scrollBy(dx, dy);
      },
      onswipeend: (vx: number, vy: number) => {
        if (pageTurn !== "follow") return false;
        dismissMenu();
        c.snap(vx, vy);
        return true;
      },
    };

    if (isIOSDevice()) {
      setupIOSTouchSelection(doc, win, {
        ...swipe,
        onselect: (range, text) => showMenuFor(doc, range, text),
        ontapdismiss: () => {
          if (Date.now() - menuShownAt < 500) return;
          dismissMenu();
        },
        isMenuVisible: () => showMenu,
        getSelectionTint: selectionTint,
      });
    } else {
      setupSwipeNavigation(doc, win, {
        ...swipe,
        ontap: () => setTimeout(() => tryShowMenuFromSelection(doc, win), 300),
      });
      doc.addEventListener("mouseup", () =>
        setTimeout(() => tryShowMenuFromSelection(doc, win), 0),
      );
      // Saved highlights are click targets: say so with the cursor.
      doc.addEventListener("mousemove", (e: MouseEvent) => {
        if (!doc.body) return;
        const over = !!layer?.hitTest(e.clientX, e.clientY);
        doc.body.style.cursor = over ? "pointer" : "";
      });
    }
  }

  function handleLoad({ doc }: { doc: Document }) {
    doc.addEventListener("keydown", handleKey);
    if (core?.vertical) pinVerticalPunctuation(doc);
    attachGestures(doc);
  }

  // ------------------------------------------------------------ lifecycle

  onMount(async () => {
    try {
      lastHighlightRaw = localStorage.getItem(HIGHLIGHT_STYLE_KEY) ?? "yellow";
    } catch {
      // storage unavailable: the default stands
    }
    // Dynamic import: the paginator registers a custom element at module
    // evaluation, which has no meaning during SSR.
    const { ReaderCore } = await import("$lib/reader/core");
    if (destroyed) return;
    const c = new ReaderCore(container, {
      onload: handleLoad,
      onrelocate: (location) => onrelocate?.(location),
      onoverlayer: ({ doc, index, overlayer }) =>
        layer?.attach(overlayer, doc, index),
    });
    core = c;
    layer = new AnnotationLayer((cfi) => c.resolve(cfi));
    // Debug handle — the only way e2e probes and a device Web Inspector
    // reach engine internals (same convention as __beepubReader).
    (window as unknown as { __beepubReaderNG?: unknown }).__beepubReaderNG = {
      core: c,
      paginator: c.paginator,
      annotations: layer,
    };
    try {
      const payload = await source.openBook(bookId);
      const { loaderFromPayload } = await import("$lib/reader/loaders/server");
      const loader = loaderFromPayload(payload);
      // The list loads alongside the book; a failure leaves the page
      // readable without marks rather than blocking it.
      const listing = sync.listHighlights(bookId).catch((e: unknown) => {
        console.error(e);
        return [] as HighlightOut[];
      });
      c.setLayout(layout);
      c.setPageTurn(pageTurn);
      c.setStyles(styles());
      const book = await c.open(loader, initialCfi);
      if (destroyed) return;
      onbook?.(book);
      onready?.();
      const list = await listing;
      if (destroyed) return;
      applyHighlights(list);
      void healHighlights();
    } catch (e) {
      console.error(e);
      onerror?.(e instanceof Error ? e : new Error(String(e)));
    }
  });

  // Settings flow one way: props → CSS/attributes → the paginator's own
  // ResizeObserver / attributeChangedCallback re-render and re-anchor.
  $effect(() => {
    const css = styles();
    core?.setStyles(css);
  });
  $effect(() => {
    const next = { ...layout };
    core?.setLayout(next);
  });
  $effect(() => {
    const mode = pageTurn;
    core?.setPageTurn(mode);
  });

  onDestroy(() => {
    destroyed = true;
    healAbort?.abort();
    layer?.detach();
    layer = null;
    core?.destroy();
    core = null;
  });

  export function prev() {
    dismissMenu();
    return core?.prev();
  }
  export function next() {
    dismissMenu();
    return core?.next();
  }
  export function goTo(target: NavInput) {
    dismissMenu();
    return core?.goTo(target);
  }
  export function getCore(): ReaderCore | null {
    return core;
  }
</script>

<svelte:window onkeydown={handleKey} />

<div
  bind:this={wrapper}
  data-testid="book-reader"
  class="relative h-full w-full"
  style="-webkit-touch-callout: none; -webkit-user-select: none; user-select: none;"
>
  <div bind:this={container} class="h-full w-full"></div>

  {#if showMenu}
    <div
      bind:this={menuEl}
      data-testid="highlight-menu"
      class="absolute z-20 transform -translate-x-1/2 -translate-y-full"
      style="left: {menuX}px; top: {menuY}px;"
    >
      <HighlightMenu
        hasExisting={!!existingHighlight}
        activeRaw={existingHighlight?.color ?? lastHighlightRaw}
        showAi={false}
        onhighlight={handleHighlight}
        onrestyle={handleRestyle}
        onnote={handleNote}
        onremove={handleRemoveHighlight}
        oncopy={handleCopy}
        onshare={handleShare}
      />
    </div>
  {/if}

  {#if noteEditorHighlight}
    <HighlightNoteEditor
      note={noteEditorHighlight.note ?? ""}
      text={noteEditorHighlight.text}
      {darkMode}
      onsave={handleNoteSave}
      onclose={() => (noteEditorHighlight = null)}
    />
  {/if}
</div>
