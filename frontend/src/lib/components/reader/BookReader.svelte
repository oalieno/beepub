<script lang="ts">
  /**
   * BookReader — the thinnest Svelte container around ReaderCore. Mounts
   * the paginator into a full-size div, feeds it theme CSS and layout
   * parameters, and forwards relocations. Everything product-shaped
   * (progress, highlights, gestures, sidebars) is layered on top of this
   * in later gates; this component must stay engine-facing.
   *
   * Must sit inside the reader root div: .reader-light / .reader-dark
   * scope the theme tokens the chrome around it uses.
   */
  import { onDestroy, onMount } from "svelte";
  import type {
    Book,
    LayoutParams,
    NavInput,
    ReaderCore,
    Relocation,
  } from "$lib/reader/core";
  import type { BookSource } from "$lib/reading/source";

  let {
    bookId,
    source,
    initialCfi = null,
    fontFamily = "serif",
    fontSize = 16,
    lineHeight = 1.8,
    darkMode = false,
    layout = {},
    onbook,
    onready,
    onerror,
    onrelocate,
  }: {
    bookId: string;
    source: BookSource;
    initialCfi?: string | null;
    fontFamily?: string;
    fontSize?: number;
    lineHeight?: number;
    darkMode?: boolean;
    layout?: LayoutParams;
    onbook?: (book: Book) => void;
    /** First section rendered. */
    onready?: () => void;
    onerror?: (error: Error) => void;
    onrelocate?: (location: Relocation) => void;
  } = $props();

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

  // Port of EpubReader's applyTheme() as plain CSS. Sizing the root too
  // makes rem-based book rules follow the setting while the book's own
  // em/% hierarchy is preserved.
  function themeCss(): string {
    const dark = darkMode;
    const tint = dark ? "245, 158, 11, 0.4" : "196, 146, 74, 0.3";
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
::selection { background: rgba(${tint}); }`;
  }

  function styles(): [string, string] {
    return [fontFaceCss(), themeCss()];
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
        void c.goLeft();
        break;
      case "ArrowRight":
        e.preventDefault();
        void c.goRight();
        break;
      case "ArrowUp":
      case "PageUp":
        e.preventDefault();
        void c.prev();
        break;
      case "ArrowDown":
      case "PageDown":
      case " ":
        e.preventDefault();
        void c.next();
        break;
    }
  }

  onMount(async () => {
    // Dynamic import: the paginator registers a custom element at module
    // evaluation, which has no meaning during SSR.
    const { ReaderCore } = await import("$lib/reader/core");
    if (destroyed) return;
    const c = new ReaderCore(container, {
      onload: ({ doc }) => doc.addEventListener("keydown", handleKey),
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

  onDestroy(() => {
    destroyed = true;
    core?.destroy();
    core = null;
  });

  export function prev() {
    return core?.prev();
  }
  export function next() {
    return core?.next();
  }
  export function goTo(target: NavInput) {
    return core?.goTo(target);
  }
  export function getCore(): ReaderCore | null {
    return core;
  }
</script>

<svelte:window onkeydown={handleKey} />

<div
  bind:this={container}
  class="h-full w-full"
  data-testid="book-reader"
></div>
