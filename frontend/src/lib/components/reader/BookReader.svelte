<script lang="ts">
  /**
   * BookReader — the thinnest Svelte container around ReaderCore. Mounts
   * the paginator into a full-size div, feeds it theme CSS and layout
   * parameters, forwards relocations, and owns the gesture layer: edge tap
   * zones, swipe, the page-turn mode, and text selection with its menu.
   * Product-shaped state (progress, saved highlights, sidebars) is layered
   * on top of this in later gates; this component stays engine-facing.
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
  import type { BookSource } from "$lib/reading/source";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";
  import HighlightMenu from "./HighlightMenu.svelte";
  import { setupIOSTouchSelection } from "./ios-touch-selection";
  import { isIOSDevice, setupSwipeNavigation } from "./touch-navigation";
  import { snapRangeToWordBounds } from "./word-snap";

  let {
    bookId,
    source,
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
  }: {
    bookId: string;
    source: BookSource;
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

  // Tap-to-turn zones live in the parent document, so touches there never
  // reach the iframe. Sized to the page's own inset (foliate's outer
  // half-gap plus the inner padding come to roughly gap% of the reader)
  // and capped at 48px, so they never sit on text.
  let zonePercent = $derived(layout.gap ?? 7);

  function edgeTap(side: "left" | "right") {
    if (showMenu) return;
    turn(side);
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
  // Height fallback before the first render (single action bar).
  const MENU_H = 44;

  function setClampedMenuPosition(x: number, y: number) {
    const cw = wrapper?.clientWidth ?? window.innerWidth;
    const menuW = menuEl?.offsetWidth ?? 0;
    // Centered via -translate-x-1/2; clamp once the width is measurable.
    menuX =
      menuW > 0 ? Math.max(menuW / 2 + 8, Math.min(cw - menuW / 2 - 8, x)) : x;
    // Above the viewport → show below the selection instead.
    const menuH = menuEl?.offsetHeight || MENU_H;
    menuY = y < menuH + 8 ? y + menuH + 16 : y;
  }

  /** Show the menu above a range in a section document. Range rects are in
   *  iframe coordinates; the iframe element's rect (which already reflects
   *  the container's scroll) maps them into the wrapper. */
  function showMenuFor(doc: Document, range: Range, text: string) {
    const frame = doc.defaultView?.frameElement;
    const fr = frame?.getBoundingClientRect();
    const wr = wrapper.getBoundingClientRect();
    const rect = range.getBoundingClientRect();
    const x = rect.left + rect.width / 2 + (fr?.left ?? 0) - wr.left;
    const y = rect.top - 8 + (fr?.top ?? 0) - wr.top;
    selectedRange = range;
    selectedText = text;
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

  // Saving highlights, notes and the AI actions arrive with the pipeline
  // gate (G2); until then the menu offers copy.
  function notYet() {
    dismissMenu();
  }

  // ------------------------------------------------------------ gestures

  function attachGestures(doc: Document) {
    const win = doc.defaultView;
    if (!win) return;
    const c = core;
    if (!c) return;

    // The click that follows a touch: a long-press selection's residue is
    // swallowed upstream (capture listener in ios-touch-selection); what
    // reaches here is a deliberate tap — dismiss the menu, or toggle chrome.
    doc.addEventListener("click", () => {
      const now = Date.now();
      if (now - menuShownAt < 500 || now - menuDismissedAt < 700) return;
      if (showMenu) {
        if (!hasLiveSelection(win)) dismissMenu();
        return;
      }
      ontap?.();
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
    }
  }

  function handleLoad({ doc }: { doc: Document }) {
    doc.addEventListener("keydown", handleKey);
    if (core?.vertical) pinVerticalPunctuation(doc);
    attachGestures(doc);
  }

  // ------------------------------------------------------------ lifecycle

  onMount(async () => {
    // Dynamic import: the paginator registers a custom element at module
    // evaluation, which has no meaning during SSR.
    const { ReaderCore } = await import("$lib/reader/core");
    if (destroyed) return;
    const c = new ReaderCore(container, {
      onload: handleLoad,
      onrelocate: (location) => onrelocate?.(location),
    });
    core = c;
    // Debug handle — the only way e2e probes and a device Web Inspector
    // reach engine internals (same convention as __beepubReader).
    (window as unknown as { __beepubReaderNG?: unknown }).__beepubReaderNG = {
      core: c,
      paginator: c.paginator,
    };
    try {
      const payload = await source.openBook(bookId);
      const { loaderFromPayload } = await import("$lib/reader/loaders/server");
      const loader = loaderFromPayload(payload);
      c.setLayout(layout);
      c.setPageTurn(pageTurn);
      c.setStyles(styles());
      const book = await c.open(loader, initialCfi);
      if (destroyed) return;
      onbook?.(book);
      onready?.();
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

  <button
    type="button"
    class="absolute inset-y-0 left-0 z-10"
    style="width: min(48px, {zonePercent}%)"
    aria-label={m.reader_prev_page()}
    onclick={() => edgeTap("left")}
  ></button>
  <button
    type="button"
    class="absolute inset-y-0 right-0 z-10"
    style="width: min(48px, {zonePercent}%)"
    aria-label={m.reader_next_page()}
    onclick={() => edgeTap("right")}
  ></button>

  {#if showMenu}
    <div
      bind:this={menuEl}
      data-testid="highlight-menu"
      class="absolute z-20 transform -translate-x-1/2 -translate-y-full"
      style="left: {menuX}px; top: {menuY}px;"
    >
      <HighlightMenu
        hasExisting={false}
        showAi={false}
        oncopy={handleCopy}
        onhighlight={notYet}
        onnote={notYet}
        onshare={notYet}
      />
    </div>
  {/if}
</div>
