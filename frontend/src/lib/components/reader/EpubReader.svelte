<script lang="ts">
  import { onMount, onDestroy, tick } from "svelte";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import { cfiOf, locatorFromCfi } from "$lib/reading/locator";
  import {
    percentFromPosition,
    positionFromPercent,
    usableWeights,
  } from "$lib/reading/progress";
  import type { BookSource } from "$lib/reading/source";
  import type { ProgressSave, SyncBackend } from "$lib/reading/sync";
  import HighlightMenu from "./HighlightMenu.svelte";
  import HighlightNoteEditor from "./HighlightNoteEditor.svelte";
  import ImageViewer from "./ImageViewer.svelte";
  import FootnotePopup from "./FootnotePopup.svelte";
  import { setupIOSTouchSelection } from "./ios-touch-selection";
  import { updateIllustrationOverlays } from "./illustration-overlays";
  import { prefetchSections } from "./image-prefetch";
  import { findActiveTocHref, findTocLabelForHref } from "./toc-utils";
  import { snapRangeToWordBounds } from "./word-snap";
  import {
    HIGHLIGHT_COLORS,
    HIGHLIGHT_LINE_COLORS,
    parseHighlightColor,
  } from "./highlight-style";
  import {
    sectionIndexFromCfi,
    verifyHighlightAnchors,
  } from "./highlight-anchor";
  import {
    parseKosyncXpointer,
    resolveXpointerRange,
    xpointerFromRange,
  } from "./kosync-xpointer";
  import type { HighlightOut, IllustrationOut } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";

  let {
    bookId,
    source,
    sync,
    initialCfi = null,
    fontFamily = "serif",
    fontSize = 16,
    lineHeight = 1.8,
    pageMargin = 32,
    darkMode = false,
    isImageBook = false,
    offline = false,
    sectionWeights = null,
    aiBookId = null,
    onprogress,
    onactivity,
    ontitle,
    ontoc,
    ondirection,
    onhighlightschange,
    onillustrate,
    onillustrationschange,
    onillustrationclick,
    onshare,
    onhrefchange,
    onready,
    onerror,
    oncompanion,
    ontap,
    onatend,
    onbookend,
    onkosyncposition,
    onrestorefallback,
    onbrokenhighlights,
    onpeekchange,
  }: {
    bookId: string;
    /** Server identity for AI features (illustrations, companion) — the
     *  linked server id for local books, bookId itself for beepub books,
     *  null when AI is unavailable. */
    aiBookId?: string | null;
    /** Where the book's bytes come from (beepub server, later local/OPDS). */
    source: BookSource;
    /** Where the user's progress and highlights live. */
    sync: SyncBackend;
    initialCfi?: string | null;
    fontFamily?: string;
    fontSize?: number;
    lineHeight?: number;
    pageMargin?: number;
    darkMode?: boolean;
    isImageBook?: boolean;
    offline?: boolean;
    /** Per-spine-section text sizes (chars) from the book source; null
     *  falls back to uniform section weights. See $lib/reading/progress. */
    sectionWeights?: number[] | null;
    onprogress?: (detail: { cfi: string; percentage: number | null }) => void;
    /** Fires on user-driven relocations that count as active reading —
     *  the same signal the trackActivity save uses. */
    onactivity?: () => void;
    ontitle?: (title: string) => void;
    ontoc?: (toc: { label: string; href: string; subitems?: any[] }[]) => void;
    ondirection?: (isRtl: boolean) => void;
    onhighlightschange?: (highlights: HighlightOut[]) => void;
    onillustrate?: (detail: { cfiRange: string; text: string }) => void;
    onillustrationschange?: (illustrations: IllustrationOut[]) => void;
    onillustrationclick?: (illustration: IllustrationOut) => void;
    onshare?: (highlight: HighlightOut) => void;
    onhrefchange?: (href: string) => void;
    onready?: () => void;
    onerror?: (error: Error) => void;
    oncompanion?: (detail: { cfiRange: string; text: string }) => void;
    ontap?: () => void;
    onatend?: () => void;
    onbookend?: () => void;
    onkosyncposition?: (detail: {
      percentage: number;
      device: string | null;
      sectionIndex: number | null;
      xpointer: string | null;
      autoJumped: boolean;
      /** Where the reader actually sits (CFI-derived) — the page-level
       *  progress state may not have received a canonical value yet. */
      localPercentage?: number;
    }) => void;
    onrestorefallback?: (percentage: number) => void;
    onbrokenhighlights?: (ids: string[]) => void;
    onpeekchange?: (peek: { percentage: number | null } | null) => void;
  } = $props();

  let isRtl = $state(false);
  let isAtEnd = $state(false);

  let container: HTMLDivElement;
  let epubBook: any = $state(null);
  let rendition: any = $state(null);
  const isIOSDevice =
    typeof navigator !== "undefined" &&
    (/iPad|iPhone|iPod/.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1));
  let highlights: HighlightOut[] = $state([]);
  let illustrations: IllustrationOut[] = $state([]);

  // Highlight menu
  let showHighlightMenu = $state(false);
  let highlightMenuX = $state(0);
  let highlightMenuY = $state(0);
  let selectedCfi = $state("");
  let selectedText = $state("");
  let selectedPrefix = "";
  let selectedSuffix = "";
  let existingHighlight: HighlightOut | null = $state(null);
  let highlightMenuShownAt = 0;
  let highlightMenuEl: HTMLDivElement | undefined = $state();
  let longPressFired = false;
  // Height fallbacks before first render: single action bar vs. the
  // two-pill stack (picker + actions) shown on an existing highlight.
  const MENU_H = 44;
  const MENU_H_STACKED = 96;

  function setClampedMenuPosition(x: number, y: number, fallbackH = MENU_H) {
    const cw = container?.clientWidth ?? window.innerWidth;
    const menuW = highlightMenuEl?.offsetWidth ?? 0;
    if (menuW > 0) {
      // Menu is rendered, clamp based on actual width (centered via -translate-x-1/2)
      highlightMenuX = Math.max(menuW / 2 + 8, Math.min(cw - menuW / 2 - 8, x));
    } else {
      // Menu not yet rendered, use unclamped — will be corrected on next call
      highlightMenuX = x;
    }
    // If above viewport, show below selection. The menu remounts on every
    // open, so the measured height is only available on repositions.
    const menuH = highlightMenuEl?.offsetHeight || fallbackH;
    highlightMenuY = y < menuH + 8 ? y + menuH + 16 : y;
  }

  /** Dismiss highlight menu and clear iOS selection overlay */
  function dismissMenu() {
    showHighlightMenu = false;
    clearIOSSelection();
  }

  const QUOTE_CONTEXT = 48;

  /**
   * W3C TextQuoteSelector-style context around a selection, taken from the
   * boundary text nodes — the raw material for re-anchoring a highlight
   * whose CFI stops resolving after the book file is rewritten.
   */
  function quoteContext(range: Range): { prefix: string; suffix: string } {
    let prefix = "";
    let suffix = "";
    const sc = range.startContainer;
    if (sc.nodeType === 3) {
      const t = sc.textContent ?? "";
      prefix = t.slice(
        Math.max(0, range.startOffset - QUOTE_CONTEXT),
        range.startOffset,
      );
    }
    const ec = range.endContainer;
    if (ec.nodeType === 3) {
      const t = ec.textContent ?? "";
      suffix = t.slice(range.endOffset, range.endOffset + QUOTE_CONTEXT);
    }
    return { prefix, suffix };
  }

  /** Show highlight menu at a given range with scroll-offset correction */
  function showMenuAtRange(
    range: Range,
    text: string,
    cfiRange: string,
    existing: HighlightOut | null,
  ) {
    const rect = range.getBoundingClientRect();
    const mgr = rendition?.manager;
    const scrollLeft = mgr?.container?.scrollLeft ?? 0;
    const scrollTop = mgr?.container?.scrollTop ?? 0;
    selectedCfi = cfiRange;
    selectedText = text;
    const ctx = quoteContext(range);
    selectedPrefix = ctx.prefix;
    selectedSuffix = ctx.suffix;
    existingHighlight = existing;
    const menuX = rect.left - scrollLeft + rect.width / 2;
    const menuY = rect.top - scrollTop - 8;
    const fallbackH = existing ? MENU_H_STACKED : MENU_H;
    setClampedMenuPosition(menuX, menuY, fallbackH);
    showHighlightMenu = true;
    highlightMenuShownAt = Date.now();
    // The clamp needs the menu's measured size, and the menu remounts on
    // every open — at this point the element doesn't exist yet, so the
    // position set above is unclamped. tick() resolves after the mount
    // but before the browser paints: reclamping here lands in the same
    // frame, so an edge-of-screen menu never flashes at the overflowing
    // position (and single-shot openers like a desktop mark click, which
    // get no second call to correct it, are clamped at all).
    void tick().then(() => {
      if (showHighlightMenu) setClampedMenuPosition(menuX, menuY, fallbackH);
    });
  }

  // Image zoom viewer
  let zoomImageSrc: string | null = $state(null);

  // Footnote popup
  let showFootnote = $state(false);
  let footnoteContent = $state("");
  let footnoteOpenedThisClick = false;
  let footnoteSourcePath = $state("");

  // Progress tracking
  let currentCfi = "";
  let currentSectionIndex = 0;
  let currentSectionPage = 0;
  let currentPage = 0;
  let totalPages = 0;
  let currentPercentage = 0;
  let sectionPageCounts: number[] = [];
  // Fresh-auth-header function from the source's stream payload; null for
  // byte-loaded books or unauthenticated streams.
  let bookAuthHeader: (() => Record<string, string>) | null = null;
  // crengine-style xpointer for the current position, recomputed async on
  // each relocation from the pristine section DOM (the rendered iframe can
  // contain injected overlays that would skew child indices). Shipped with
  // progress saves so e-readers pulling through kosync land on the exact
  // paragraph; the cfi tag keeps a stale pointer from ever being shipped.
  let currentXpointer: string | null = null;
  let currentXpointerCfi = "";
  let lastLocation: any = null;
  let restoringProgress = false;

  // Position bridged from an e-reader (kosync), newer than the stored CFI.
  // Captured from the progress payload at open; resolved once the canonical
  // percentage is known (locations ready): jump when the book was never read
  // on the web, otherwise let the parent offer the jump.
  let kosyncMarker: {
    percentage: number;
    device: string | null;
    sectionIndex: number | null;
    xpointer: string | null;
  } | null = null;
  let kosyncAutoJump = false;
  // The CFI the restore targeted. After a device push the STORED percentage
  // is the device's (the bridge overwrites it — that's how the home screen
  // shows e-reader progress), so comparing the marker against
  // currentPercentage before the canonical recompute lands compares the
  // device position against itself and silently drops the prompt.
  let kosyncBaselineCfi: string | null = null;
  // Set on any user navigation. When locations finish late (large books)
  // the kosync auto-jump downgrades to an offer instead of yanking the
  // reader away from a position they have already started reading at.
  let userNavigated = false;
  // Degraded restore: the saved CFI no longer resolves (the file was
  // rewritten — calibre metadata edit, re-conversion) but a percentage
  // couldn't be applied yet because locations weren't ready. Resolved the
  // same way as kosyncMarker once they are.
  let restoreFallbackPct: number | null = null;
  // Peek: a highlight jump is a visit, not a move. Remember where the
  // reader was (pill offers the way back) and hold progress saves until
  // they either return, dismiss, or start reading here (page turn).
  let peekReturn: { cfi: string; percentage: number | null } | null = null;
  let peekSaveHold = false;

  // TOC tracking
  let tocData: { label: string; href: string; subitems?: any[] }[] = [];

  let progressTimer: ReturnType<typeof setInterval> | null = null;
  let saveDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  let handleVisibility: (() => void) | null = null;

  // The raw color string may carry a style suffix ("yellow:underline") —
  // see highlight-style.ts. This resolves it to annotation arguments: the
  // classic pastel fill, or a data.beepubStyle routed line mark (drawn by
  // BeepubLineMark in the epubjs fork's iframe.js).
  function highlightAnnotationArgs(raw: string): {
    data: Record<string, string>;
    styles: Record<string, string>;
  } {
    const { color, style } = parseHighlightColor(raw);
    if (style === "highlight") {
      return {
        data: {},
        styles: {
          fill: HIGHLIGHT_COLORS[color] ?? HIGHLIGHT_COLORS.yellow,
          "fill-opacity": "0.5",
        },
      };
    }
    return {
      data: { beepubStyle: style },
      styles: {
        stroke: HIGHLIGHT_LINE_COLORS[color] ?? HIGHLIGHT_LINE_COLORS.yellow,
        fill: "none",
        // The view merges in mix-blend-mode: multiply by default — fine
        // for pastel fills, but it erases a colored line on a dark page.
        "mix-blend-mode": "normal",
      },
    };
  }

  // Apple ships no Traditional-Chinese font that can rotate punctuation in
  // vertical writing: iOS's PingFang has no vertical alternates for the
  // rotation-class punctuation and Songti isn't installed there, so in
  // vertical-rl books ［］「」（） render unrotated. These faces (injected
  // per section in the content hook) are ~4KB Noto CJK TC subsets in
  // static/fonts holding ONLY that punctuation and its vert forms
  // (rebuild: scripts/build-vpunct-fonts.py). A physical subset rather
  // than local() aliasing to Hiragino: Safari leaks characters outside
  // unicode-range to a local() source (、。： came out Japanese-styled on
  // device), and a font that only contains the rotation class has
  // nothing to leak. 、。！？ stay on the book's fonts and keep the TC
  // centered style; — and － are excluded because Noto has no vert forms
  // for them. The subsets carry PingFang's hhea/OS-2 metrics, not Noto's:
  // Safari centers cross-font runs via ascent/descent, and stock Noto
  // metrics push the glyphs ~7% em off the column axis on iOS.
  const VPUNCT_SERIF = "BeePub VPunct Serif";
  const VPUNCT_SANS = "BeePub VPunct Sans";
  const VPUNCT_RANGE =
    "U+2015, U+2026, U+3008-3011, U+3014-301F, U+FF08-FF09, U+FF3B, U+FF3D, U+FF5B, U+FF5D, U+FF5E";
  const SERIF_FONTS = `"${VPUNCT_SERIF}", "Noto Serif CJK TC", "Source Han Serif TC", "Songti TC", "Songti SC", Georgia, "Times New Roman", serif`;
  const SANS_FONTS = `"${VPUNCT_SANS}", "Noto Sans CJK TC", "Source Han Sans TC", "PingFang TC", "PingFang SC", "Microsoft JhengHei", "Microsoft YaHei", system-ui, sans-serif`;

  function doPrefetch() {
    prefetchSections(epubBook, currentSectionIndex);
  }

  function emitProgress(percentage: number | null = currentPercentage) {
    onprogress?.({ cfi: currentCfi, percentage });
  }

  function clampPercentage(value: number): number {
    return Math.min(100, Math.max(0, Math.round(value)));
  }

  function updateSectionPageCount(sectionIndex: number, pageCount: number) {
    if (sectionIndex < 0 || pageCount < 1) return;
    if (sectionPageCounts[sectionIndex] === pageCount) return;
    const next = sectionPageCounts.slice();
    next[sectionIndex] = pageCount;
    sectionPageCounts = next;
  }

  function normalizeSectionPageCounts(value: unknown): number[] {
    if (!Array.isArray(value)) return [];
    return Array.from({ length: value.length }, (_, index) => {
      const count = value[index];
      return typeof count === "number" && Number.isFinite(count) && count > 0
        ? Math.round(count)
        : 0;
    });
  }

  function calculatePageProgress(location: any): {
    percentage: number;
    currentPage: number;
    totalPages: number;
  } {
    const totalSections = epubBook?.spine?.spineItems?.length ?? 1;
    const sectionIndex = location?.start?.index ?? currentSectionIndex;
    const page = Math.max(1, location?.start?.displayed?.page ?? 1);
    const displayedTotal = Math.max(1, location?.start?.displayed?.total ?? 1);
    updateSectionPageCount(sectionIndex, displayedTotal);

    let knownTotal = 0;
    let knownCount = 0;
    for (const count of sectionPageCounts) {
      if (count != null && count > 0) {
        knownTotal += count;
        knownCount += 1;
      }
    }

    const estimatedUnknownPages =
      knownCount > 0 ? Math.max(1, Math.round(knownTotal / knownCount)) : 1;
    let pagesBefore = 0;
    let estimatedTotalPages = 0;

    for (let i = 0; i < totalSections; i++) {
      const count = sectionPageCounts[i] ?? estimatedUnknownPages;
      if (i < sectionIndex) pagesBefore += count;
      estimatedTotalPages += count;
    }

    const pageWithinSection = Math.min(page, displayedTotal);
    const absolutePage = pagesBefore + pageWithinSection;
    const completedPages = pagesBefore + Math.max(0, pageWithinSection - 1);
    const percentage = location?.atEnd
      ? 100
      : clampPercentage(
          (completedPages / Math.max(1, estimatedTotalPages)) * 100,
        );

    return {
      percentage,
      currentPage: absolutePage,
      totalPages: estimatedTotalPages,
    };
  }

  /** Dense weights sized to the spine; uniform fallback when the source
   *  ships none (extraction pending, sideloads, image-only books). Cheap
   *  enough to rebuild per call — spines are a few hundred entries at most. */
  function progressWeights(): number[] {
    return usableWeights(
      sectionWeights,
      epubBook?.spine?.spineItems?.length ?? 0,
    );
  }

  function calculateProgress(location: any): {
    percentage: number;
    currentPage: number;
    totalPages: number;
  } {
    const pageProgress = calculatePageProgress(location);

    if (location?.atEnd) {
      return { ...pageProgress, percentage: 100 };
    }

    const weights = progressWeights();
    if (weights.length === 0) {
      return pageProgress;
    }
    const sectionIndex = location?.start?.index ?? currentSectionIndex;
    const page = Math.max(1, location?.start?.displayed?.page ?? 1);
    const total = Math.max(1, location?.start?.displayed?.total ?? 1);
    // Completed pages over the section's pages: monotone across the
    // section boundary (last page < 1, next section starts at its floor).
    const fraction = (page - 1) / total;
    return {
      ...pageProgress,
      percentage: clampPercentage(
        percentFromPosition(weights, sectionIndex, fraction),
      ),
    };
  }

  /**
   * Second half of the degraded restore: apply the stored percentage —
   * unless the user has already started reading from wherever the failed
   * restore left them.
   */
  async function resolveRestoreFallback() {
    if (restoreFallbackPct == null) return;
    const pct = restoreFallbackPct;
    restoreFallbackPct = null;
    if (!userNavigated && (await displayPercentage(pct))) {
      onrestorefallback?.(pct);
    }
  }

  /**
   * Act on an e-reader position bridged from kosync. Never read on the
   * web → adopt the device position outright; otherwise (positions
   * meaningfully apart) let the parent offer the jump — the web CFI stays
   * authoritative until the user accepts.
   */
  async function resolveKosyncMarker() {
    if (!kosyncMarker) return;
    const marker = kosyncMarker;
    kosyncMarker = null;
    if (kosyncAutoJump && !userNavigated) {
      if (
        await displayKosyncPosition(
          marker.percentage,
          marker.sectionIndex,
          marker.xpointer,
        )
      ) {
        onkosyncposition?.({ ...marker, autoJumped: true });
      }
      return;
    }
    // Compare against where the reader actually sits, derived from the CFI.
    // currentPercentage can still hold the bridge-written device percentage
    // when no relocated has recomputed it yet — and marker-vs-itself is
    // always "close enough", which ate the prompt. Deriving from the anchor
    // CFI's section is coarse (section start) but bridge-independent.
    let herePct = currentPercentage;
    const anchor = currentCfi || kosyncBaselineCfi;
    if (!currentCfi && anchor) {
      const index = sectionIndexFromCfi(anchor);
      if (index != null && index >= 0) {
        herePct = clampPercentage(
          percentFromPosition(progressWeights(), index, 0),
        );
      }
    }
    if (Math.abs(marker.percentage - herePct) > 1) {
      onkosyncposition?.({
        ...marker,
        autoJumped: false,
        localPercentage: herePct,
      });
    }
  }

  /**
   * Jump to an e-reader position, best anchor first:
   * 1. Walk the device xpointer through the section DOM — paragraph-level,
   *    immune to the renderers' diverging percentage scales.
   * 2. Percentage-derived CFI, but only when it lands in the hinted chapter.
   * 3. The hinted chapter's start — a right-chapter landing beats a
   *    wrong-chapter guess.
   * 4. Raw percentage (no usable hint at all).
   */
  export async function displayKosyncPosition(
    pct: number,
    sectionIndex: number | null,
    xpointer: string | null = null,
  ): Promise<boolean> {
    if (!isImageBook && xpointer && epubBook) {
      try {
        const cfi = await xpointerToCfi(xpointer);
        if (cfi) {
          await rendition?.display(cfi);
          return true;
        }
      } catch {
        // Best-effort — fall through to the coarser anchors.
      }
    }
    if (sectionIndex != null && !isImageBook) {
      // Trust the percentage only when it lands in the hinted chapter;
      // otherwise the right chapter's start beats a wrong-chapter guess.
      const landing = positionFromPercent(progressWeights(), pct);
      if (landing.sectionIndex === sectionIndex) {
        return displayPercentage(pct);
      }
      const href = epubBook?.spine?.get(sectionIndex)?.href;
      if (href) {
        await rendition?.display(href);
        return true;
      }
    }
    return displayPercentage(pct);
  }

  /** Resolve a device xpointer to a CFI via the section document. */
  async function xpointerToCfi(xpointer: string): Promise<string | null> {
    const parsed = parseKosyncXpointer(xpointer);
    if (!parsed) return null;
    const section = epubBook?.spine?.get(parsed.sectionIndex);
    if (!section) return null;
    await section.load(epubBook.load.bind(epubBook));
    const doc: Document | null = section.document ?? null;
    if (!doc) return null;
    const range = resolveXpointerRange(doc, parsed);
    if (!range) return null;
    return section.cfiFromRange(range) ?? null;
  }

  /** The reverse: cache a crengine-style xpointer for the current CFI so
   *  progress saves can carry it (kosync serves it to e-readers). */
  async function updateCurrentXpointer(cfi: string) {
    try {
      const index = sectionIndexFromCfi(cfi);
      const section = index != null ? epubBook?.spine?.get(index) : null;
      if (!section) {
        currentXpointer = null;
        return;
      }
      await section.load(epubBook.load.bind(epubBook));
      const doc: Document | null = section.document ?? null;
      const EpubCFI = (await import("$lib/epubjs/epubcfi")).default;
      const range: Range | null = doc ? new EpubCFI(cfi).toRange(doc) : null;
      const xp = range ? xpointerFromRange(range, index!) : null;
      // Another relocation may have raced this computation; only publish
      // if the position we computed for is still the current one.
      if (cfi === currentCfi) {
        currentXpointer = xp;
        currentXpointerCfi = cfi;
      }
    } catch {
      if (cfi === currentCfi) currentXpointer = null;
    }
  }

  function doFindActiveTocHref(sectionIndex: number): string {
    return findActiveTocHref(epubBook, rendition, tocData, sectionIndex);
  }

  onMount(() => {
    // Surface any failure in the load pipeline (corrupt file, 404/500 on
    // content, render error) instead of leaving the loading spinner forever.
    loadBook().catch((err) => {
      console.error("Failed to load EPUB:", err);
      onerror?.(err instanceof Error ? err : new Error(String(err)));
    });
  });

  async function loadBook() {
    const Epub = (await import("$lib/epubjs/epub.js")).default;

    const payload = await source.openBook(bookId);

    if (payload.kind === "bytes") {
      // Whole file in hand (native downloaded copy, later: local library)
      epubBook = Epub(payload.data, {});
    } else {
      // Stream resource-by-resource from the source's root URL
      bookAuthHeader = payload.authHeader;

      // When auth headers are needed (native mode), epub.js needs them on
      // every XHR request (chapter HTML, OPF, images, CSS). The epub.js
      // fork's substituteAsync mechanism fetches images via XHR and
      // replaces URLs with blob: URIs before DOM injection (see
      // docs/debug/023-ios-manga-lazy-image-loading.md). authHeader is a
      // function so that if the access token is refreshed mid-session,
      // subsequent XHR calls pick up the new token automatically.
      let nativeOpts = {};
      const authHeader = payload.authHeader;
      if (authHeader) {
        const defaultRequest = (await import("$lib/epubjs/utils/request"))
          .default;
        nativeOpts = {
          requestHeaders: authHeader(),
          replacements: "blobUrl",
          requestMethod: (
            url: string,
            type: string,
            withCredentials: boolean,
            headers: Record<string, string>,
          ) => {
            return defaultRequest(url, type, withCredentials, {
              ...authHeader(),
              ...(headers || {}),
            });
          },
        };
      }

      epubBook = Epub(payload.url, {
        openAs: "directory",
        ...nativeOpts,
      });
    }

    rendition = epubBook.renderTo(container, {
      width: "100%",
      height: "100%",
      spread: "none",
      allowScriptedContent: true,
      // Page margins ride the layout gap (margin = gap/2 per side): the
      // pagination math bakes the side padding into the page pitch, so
      // margins set any other way (e.g. theme CSS) shear the pages and
      // leave drawn highlights behind after a reflow.
      gap: pageMargin * 2,
    });

    // Debug handle, same spirit as the [split-diag] logs: reachable from a
    // device Web Inspector on live bug reports, and the only way e2e can
    // drive engine internals (nothing else crosses into the view manager).
    (window as { __beepubReader?: unknown }).__beepubReader = { rendition };

    // Apply theme
    applyTheme();

    // relocated handler: calculate percentage from section position
    rendition.on("relocated", (location: any) => {
      lastLocation = location;
      currentCfi = location.start.cfi;
      currentSectionIndex = location.start.index ?? 0;
      currentSectionPage = location.start.displayed?.page ?? 1;
      // Chapter tracking is pure UI — emit before the restore/locations
      // early-returns below, or the first rendered page never gets a
      // chapter label until the next relocation (e.g. a window resize).
      onhrefchange?.(doFindActiveTocHref(currentSectionIndex));
      void updateCurrentXpointer(currentCfi);
      const progress = calculateProgress(location);
      currentPage = progress.currentPage;
      totalPages = progress.totalPages;

      if (restoringProgress) {
        return;
      }

      // A degraded restore is still pending (waiting on locations): the
      // reader is parked at page 1 only as a placeholder. Don't persist it
      // over the position the fallback is about to recover — unless the
      // user actively reads on, which makes page 1 their real position.
      if (restoreFallbackPct != null && !userNavigated) {
        return;
      }

      // Persist every position change — the CFI is what restore uses.
      // Exception: while peeking at a highlight the position on screen is a
      // visit, not progress — the UI below still updates, only persistence
      // (server + localStorage) is held.
      if (!peekSaveHold) {
        debouncedSave();
        onactivity?.();
      }

      currentPercentage = progress.percentage;
      emitProgress();
      doUpdateOverlays();
      doPrefetch();

      // Track end-of-book state for series navigation
      const wasAtEnd = isAtEnd;
      isAtEnd = !!location.atEnd;
      if (isAtEnd && !wasAtEnd) {
        onatend?.();
      }

      // Cache progress in localStorage for offline/resume fallback
      if (peekSaveHold) return;
      try {
        localStorage.setItem(
          `reader-progress-${bookId}`,
          JSON.stringify({
            cfi: currentCfi,
            percentage: currentPercentage,
            currentPage,
            totalPages,
            sectionIndex: currentSectionIndex,
            sectionPage: currentSectionPage,
            sectionPageCounts: normalizeSectionPageCounts(sectionPageCounts),
            fontSize,
          }),
        );
      } catch {
        // localStorage full or unavailable
      }
    });

    rendition.on("keyup", handleKeyboard);
    document.addEventListener("keyup", handleKeyboard);

    // Scroll wheel navigation inside epub iframe
    rendition.hooks.content.register((contents: any) => {
      const doc = contents.document;
      doc.addEventListener("wheel", handleWheel, { passive: false });

      // Alias legacy Ming/Song bitmap-ish fonts (細明體, PMingLiU, Apple
      // LiSung 等) to 源流明體 GenRyuMin TC. These legacy fonts render with
      // bad aliasing on hi-dpi screens; @font-face re-routing the name
      // leaves books that pick other fonts untouched. Font files are served
      // from jsDelivr (ButTaiwan/genryu-font); browser HTTP cache means the
      // ~15MB OTFs only download once per session across iframes.
      if (!doc.getElementById("beepub-font-alias")) {
        const style = doc.createElement("style");
        style.id = "beepub-font-alias";
        const cdn =
          "https://cdn.jsdelivr.net/gh/ButTaiwan/genryu-font@master/otf/TC";
        const weights: [number, string][] = [
          [400, "R"],
          [500, "M"],
          [700, "B"],
        ];
        const aliases = [
          "細明體",
          "新細明體",
          "PMingLiU",
          "MingLiU",
          "Apple LiSung Light",
          "蘋果儷細宋",
        ];
        const faces = aliases.flatMap((name) =>
          weights.map(
            ([w, suffix]) => `@font-face {
  font-family: "${name}";
  font-weight: ${w};
  font-style: normal;
  src: url("${cdn}/GenRyuMin2TC-${suffix}.otf") format("opentype");
  font-display: swap;
}`,
          ),
        );
        style.textContent = faces.join("\n");
        doc.head.appendChild(style);
      }

      // Vertical-punctuation faces (see VPUNCT_RANGE). Inert until a
      // font-family list references them — the themed body stacks lead with
      // them, and vertical sections re-pin below.
      if (!doc.getElementById("beepub-vpunct")) {
        const style = doc.createElement("style");
        style.id = "beepub-vpunct";
        // Absolute URLs: the iframe's base resolves against the book's
        // content, not the app. HTTP cache shares the ~4KB files across
        // iframes.
        const fonts = window.location.origin + "/fonts";
        style.textContent = `@font-face {
  font-family: "${VPUNCT_SERIF}";
  src: url("${fonts}/beepub-vpunct-serif.woff2") format("woff2");
  unicode-range: ${VPUNCT_RANGE};
}
@font-face {
  font-family: "${VPUNCT_SANS}";
  src: url("${fonts}/beepub-vpunct-sans.woff2") format("woff2");
  unicode-range: ${VPUNCT_RANGE};
}`;
        doc.head.appendChild(style);
      }

      // Book CSS that sets font-family on elements (`p { font-family:
      // serif }` is common) bypasses the themed body stack, so those
      // elements never consult the punctuation face. In vertical sections,
      // prepend it to such elements' own stack via inline style — inline
      // wins at any specificity while the book's declared fonts stay
      // intact behind it. Elements that merely inherit are left alone;
      // they already follow the themed body stack.
      const writingMode: string = contents.writingMode?.() ?? "";
      const win = doc.defaultView;
      if (writingMode.startsWith("vertical") && doc.body && win) {
        const punctFamily = fontFamily === "serif" ? VPUNCT_SERIF : VPUNCT_SANS;
        const pinPunctFace = (el: Element, parentFonts: string) => {
          for (const child of Array.from(el.children)) {
            const fonts = win.getComputedStyle(child).fontFamily || "";
            if (
              fonts &&
              fonts !== parentFonts &&
              !fonts.includes("BeePub VPunct") &&
              child instanceof win.HTMLElement
            ) {
              (child as HTMLElement).style.fontFamily =
                `"${punctFamily}", ${fonts}`;
            }
            pinPunctFace(child, fonts);
          }
        };
        pinPunctFace(doc.body, win.getComputedStyle(doc.body).fontFamily || "");
      }

      // Image zoom: long-press (500ms) on both touch and mouse

      // Helper: extract image src from an event target
      function getImageSrc(target: HTMLElement): string | null {
        if (target.tagName === "IMG") {
          return (target as HTMLImageElement).src;
        }
        if (target.tagName === "image" || target.closest?.("image")) {
          const imageEl =
            target.tagName === "image" ? target : target.closest("image");
          let src =
            imageEl?.getAttribute("href") ||
            imageEl?.getAttributeNS("http://www.w3.org/1999/xlink", "href") ||
            null;
          if (src && !src.startsWith("http")) {
            src = new URL(src, contents.document.baseURI).href;
          }
          return src;
        }
        if (target.tagName === "svg" || target.closest?.("svg")) {
          const svg = target.tagName === "svg" ? target : target.closest("svg");
          const imageEl = svg?.querySelector("image");
          if (imageEl) {
            let src =
              imageEl.getAttribute("href") ||
              imageEl.getAttributeNS("http://www.w3.org/1999/xlink", "href") ||
              null;
            if (src && !src.startsWith("http")) {
              src = new URL(src, contents.document.baseURI).href;
            }
            return src;
          }
        }
        return null;
      }

      // Touch: long-press (500ms) to zoom image
      let longPressTimer: ReturnType<typeof setTimeout> | null = null;
      // longPressFired is at component scope (see below)

      doc.addEventListener(
        "touchstart",
        (e: TouchEvent) => {
          const target = e.target as HTMLElement;
          if (!target) return;
          const src = getImageSrc(target);
          if (!src) return;
          longPressFired = false;
          longPressTimer = setTimeout(() => {
            longPressFired = true;
            zoomImageSrc = src;
          }, 500);
        },
        { passive: true },
      );

      doc.addEventListener(
        "touchmove",
        () => {
          if (longPressTimer) {
            clearTimeout(longPressTimer);
            longPressTimer = null;
          }
        },
        { passive: true },
      );

      doc.addEventListener("touchend", () => {
        if (longPressTimer) {
          clearTimeout(longPressTimer);
          longPressTimer = null;
        }
      });

      // Mouse: long-press (500ms) to zoom image (same as touch)
      let mouseDownTimer: ReturnType<typeof setTimeout> | null = null;

      doc.addEventListener("mousedown", (e: MouseEvent) => {
        const target = e.target as HTMLElement;
        if (!target) return;
        const src = getImageSrc(target);
        if (!src) return;
        mouseDownTimer = setTimeout(() => {
          longPressFired = true;
          zoomImageSrc = src;
        }, 500);
      });

      doc.addEventListener("mousemove", () => {
        if (mouseDownTimer) {
          clearTimeout(mouseDownTimer);
          mouseDownTimer = null;
        }
      });

      doc.addEventListener("mouseup", () => {
        if (mouseDownTimer) {
          clearTimeout(mouseDownTimer);
          mouseDownTimer = null;
        }
      });

      // Highlight cursor: show pointer when hovering over a highlight
      doc.addEventListener("mousemove", (e: MouseEvent) => {
        const views = rendition?.manager?.views;
        if (!views?._views?.length) return;
        const view = views._views[0];
        if (!view?.highlights || !view?.iframe) return;
        // Convert iframe-local coords to parent-document coords
        const iframeRect = view.iframe.getBoundingClientRect();
        const px = e.clientX + iframeRect.left;
        const py = e.clientY + iframeRect.top;
        let overHighlight = false;
        for (const cfi in view.highlights) {
          const hl = view.highlights[cfi];
          if (!hl?.mark) continue;
          const rects = hl.mark.getClientRects();
          for (let i = 0; i < rects.length; i++) {
            const r = rects[i];
            if (
              px >= r.left &&
              px <= r.right &&
              py >= r.top &&
              py <= r.bottom
            ) {
              overHighlight = true;
              break;
            }
          }
          if (overHighlight) break;
        }
        doc.body.style.cursor = overHighlight ? "pointer" : "";
      });

      // Helper: show highlight menu from current selection. The range is
      // word-snapped silently (the native selection is left alone —
      // mutating it mid-drag corrupts the browser's drag anchor); the
      // saved highlight and its drawn annotation carry the full words.
      function tryShowMenuFromSelection() {
        if (showHighlightMenu) return;
        const sel = contents.window?.getSelection();
        if (!sel || sel.isCollapsed || !sel.toString().trim()) return;
        const snapped = snapRangeToWordBounds(sel.getRangeAt(0));
        const cfiRange = rendition?.manager
          ?.getContents?.()?.[0]
          ?.cfiFromRange?.(snapped);
        if (!cfiRange) return;
        const text = snapped.toString().trim();
        const existing =
          highlights.find((h: HighlightOut) => h.cfi_range === cfiRange) ??
          null;
        showMenuAtRange(snapped, text, cfiRange, existing);
      }

      if (isIOSDevice) {
        setupIOSTouchSelection(doc, contents.window, {
          onselect(range, text) {
            if (isImageBook) return;
            const cfi = rendition?.manager
              ?.getContents?.()?.[0]
              ?.cfiFromRange?.(range);
            if (!cfi) return;
            const existing =
              highlights.find((h: HighlightOut) => h.cfi_range === cfi) ?? null;
            showMenuAtRange(range, text, cfi, existing);
          },
          onswipeleft: () => (isRtl ? _doPrev() : _doNext()),
          onswiperight: () => (isRtl ? _doNext() : _doPrev()),
          ontapdismiss: () => {
            // Tapping an existing highlight opens the menu on touchstart
            // (the fork's marks emit markClicked for touchstart AND the
            // synthesized click), so by the time the SAME tap's touchend
            // reaches us the menu is already visible — without this guard
            // it reads as a dismissal tap and the menu blinks
            // open -> closed -> open (the click reopens it).
            if (Date.now() - highlightMenuShownAt < 500) return;
            dismissMenu();
          },
          isMenuVisible: () => showHighlightMenu,
          getSelectionTint: selectionTint,
        });
      } else {
        // === Non-iOS: use selectionchange + touchend fallback ===
        let selChangeTimer: ReturnType<typeof setTimeout> | null = null;
        doc.addEventListener("selectionchange", () => {
          if (selChangeTimer) clearTimeout(selChangeTimer);
          selChangeTimer = setTimeout(tryShowMenuFromSelection, 500);
        });

        // Swipe-to-turn-page for non-iOS touch devices
        let swipeStartX = 0;
        let swipeStartY = 0;
        let swiping = false;
        const SWIPE_THRESHOLD = 50;

        doc.addEventListener(
          "touchstart",
          (e: TouchEvent) => {
            if (e.touches.length !== 1) return;
            swipeStartX = e.touches[0].clientX;
            swipeStartY = e.touches[0].clientY;
            swiping = false;
          },
          { passive: true },
        );

        doc.addEventListener(
          "touchmove",
          (e: TouchEvent) => {
            const t = e.touches[0];
            if (
              Math.abs(t.clientX - swipeStartX) > 10 ||
              Math.abs(t.clientY - swipeStartY) > 10
            ) {
              swiping = true;
            }
          },
          { passive: true },
        );

        doc.addEventListener(
          "touchend",
          (e: TouchEvent) => {
            const endX = e.changedTouches[0]?.clientX ?? swipeStartX;
            const dx = endX - swipeStartX;

            if (swiping && Math.abs(dx) > SWIPE_THRESHOLD) {
              // Don't turn page if text is selected
              const sel = contents.window?.getSelection();
              if (sel && !sel.isCollapsed && sel.toString().trim()) return;

              const swipeLeft = dx < 0;
              if (swipeLeft) {
                isRtl ? _doPrev() : _doNext();
              } else {
                isRtl ? _doNext() : _doPrev();
              }
            } else if (!swiping) {
              // Tap (not swipe) — show highlight menu if text selected
              setTimeout(tryShowMenuFromSelection, 300);
            }
          },
          { passive: true },
        );
      }
    });
    container.addEventListener("wheel", handleWheel, { passive: false });

    rendition.on(
      "selected",
      (cfiRange: string, contents: { window: Window }) => {
        // On iOS, our custom touch handler manages selection and menu
        if (isIOSDevice) return;
        if (isImageBook) return;

        const selection = contents.window.getSelection();
        if (!selection || selection.toString().trim() === "") return;
        // Word-snap and recompute the CFI; fall back to epub.js's own
        // cfiRange if the snapped range can't be converted.
        const snapped = snapRangeToWordBounds(selection.getRangeAt(0));
        const snappedCfi =
          rendition?.manager?.getContents?.()?.[0]?.cfiFromRange?.(snapped) ??
          cfiRange;
        const text = snapped.toString().trim();
        const existing =
          highlights.find((h) => h.cfi_range === snappedCfi) ?? null;
        showMenuAtRange(snapped, text, snappedCfi, existing);
      },
    );

    rendition.on(
      "markClicked",
      (cfiRange: string, _data: any, contents: any) => {
        const hl = highlights.find(
          (h: HighlightOut) => h.cfi_range === cfiRange,
        );
        if (!hl) return;

        const range = contents?.range?.(cfiRange);
        if (!range) return;
        showMenuAtRange(range, hl.text, cfiRange, hl);
      },
    );

    rendition.on("click", () => {
      // Guard: on mobile, 'click' fires right after 'selected' and would
      // immediately dismiss the menu. Ignore clicks within 500ms of showing.
      if (Date.now() - highlightMenuShownAt < 500) return;

      // Only dismiss highlight menu if there's no active text selection
      const contents = rendition?.manager?.getContents?.();
      const sel = contents?.[0]?.window?.getSelection();
      if (!sel || sel.isCollapsed || sel.toString().trim() === "") {
        dismissMenu();
        // Don't close footnote if it was just opened by a link click in the same event cycle
        if (!footnoteOpenedThisClick) {
          showFootnote = false;
        }
        // Notify parent for bottom bar toggle (skip if long-press just zoomed an image)
        if (!longPressFired) ontap?.();
        longPressFired = false;
      }
    });

    rendition.on("link", async (linkEvent: any) => {
      const href: string = linkEvent.href;
      const hashIdx = href.indexOf("#");
      if (hashIdx === -1) {
        return;
      }

      const filePath = href.slice(0, hashIdx);
      const elementId = href.slice(hashIdx + 1);

      const section = epubBook.spine.get(filePath);
      if (!section) return;

      // If the link points to a different section, navigate there instead of showing a popup
      if (section.index !== currentSectionIndex) {
        linkEvent.preventDefault();
        await rendition?.display(href);
        return;
      }

      // Same-section link — check if it's a footnote or back-reference
      // Prevent default synchronously — async handler can't prevent after await
      linkEvent.preventDefault();
      // Flag to prevent the click handler (same event cycle) from closing the popup
      footnoteOpenedThisClick = true;
      setTimeout(() => {
        footnoteOpenedThisClick = false;
      }, 0);

      try {
        // Fetch section HTML independently (don't use section.load() which corrupts spine state)
        const sectionUrl = section.url;
        const response = await fetch(sectionUrl);
        const html = await response.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, "application/xhtml+xml");
        const el = doc.querySelector(`#${CSS.escape(elementId)}`);

        // Check if the target element has meaningful text content (not just a number/marker)
        const textLen = (el?.textContent ?? "").trim().length;
        if (!el || textLen < 2) {
          // Back-reference link or empty target — navigate instead of popup
          await rendition?.display(href);
          return;
        }

        footnoteSourcePath = filePath;
        footnoteContent = el.innerHTML;
        showFootnote = true;
      } catch {
        await rendition?.display(href);
      }
    });

    // Load highlights
    try {
      highlights = await sync.listHighlights(bookId);
      onhighlightschange?.(highlights);
    } catch {
      // ignore
    }

    // Load illustrations — a BeePub-exclusive AI feature, deliberately not
    // part of SyncBackend; aiBookId carries the server identity (linked
    // local books included) or null when AI is off.
    if (aiBookId) {
      try {
        illustrations = await booksApi.getIllustrations(aiBookId);
        onillustrationschange?.(illustrations);
      } catch {
        // ignore
      }
    }

    // Load saved progress & display. The SyncBackend speaks Locators; map
    // back to the wire-ish local shape here so the restore logic below
    // stays as-is (units: totalProgression 0..1 → percentage 0..100).
    let savedProgress: any = null;
    try {
      const state = await sync.getProgress(bookId);
      if (state) {
        const totalProgression = state.locator?.locations.totalProgression;
        savedProgress = {
          cfi: state.locator ? cfiOf(state.locator) : null,
          percentage: totalProgression == null ? null : totalProgression * 100,
          current_page: state.locator?.locations.position ?? null,
          font_size: state.fontSize,
          section_index: state.sectionIndex,
          section_page: state.sectionPage,
          section_page_counts: state.sectionPageCounts,
          total_pages: state.totalPages,
          devicePosition: state.devicePosition,
        };
      }
    } catch {
      // API unreachable (e.g. iOS PWA resume with no network) — try localStorage
      try {
        const cached = localStorage.getItem(`reader-progress-${bookId}`);
        if (cached) {
          const p = JSON.parse(cached);
          savedProgress = {
            cfi: p.cfi,
            percentage: p.percentage,
            current_page: p.currentPage,
            total_pages: p.totalPages,
            section_page: p.sectionPage,
            section_index: p.sectionIndex,
            section_page_counts: normalizeSectionPageCounts(
              p.sectionPageCounts,
            ),
            font_size: p.fontSize,
          };
        }
      } catch {
        // ignore
      }
    }
    const devicePos = savedProgress?.devicePosition;
    if (!initialCfi && typeof devicePos?.percentage === "number") {
      kosyncMarker = {
        percentage: devicePos.percentage,
        device: devicePos.device ?? null,
        sectionIndex: devicePos.sectionIndex ?? null,
        xpointer: devicePos.xpointer ?? null,
      };
      kosyncAutoJump = !savedProgress?.cfi;
      kosyncBaselineCfi = savedProgress?.cfi ?? null;
    }
    try {
      if (initialCfi) {
        // Explicit jump target (e.g. a highlight clicked on the detail
        // page) takes precedence over saved progress — but it's a visit:
        // keep the way back and don't overwrite the reading position.
        startPeek(
          savedProgress?.cfi ?? null,
          savedProgress?.percentage ?? null,
        );
        // The bar keeps showing reading progress (not the visit position)
        // until the visitor turns a page — peek semantics.
        if (savedProgress?.percentage != null) {
          currentPercentage = savedProgress.percentage;
        }
        emitProgress();
        restoringProgress = true;
        await rendition.display(initialCfi);
        await new Promise((resolve) => requestAnimationFrame(resolve));
        restoringProgress = false;
        rendition.reportLocation?.();
      } else if (savedProgress?.cfi) {
        if (savedProgress.percentage != null) {
          currentPercentage = savedProgress.percentage;
        }
        if (savedProgress.current_page != null)
          currentPage = savedProgress.current_page;
        if (savedProgress.total_pages != null)
          totalPages = savedProgress.total_pages;
        if (Array.isArray(savedProgress.section_page_counts))
          sectionPageCounts = normalizeSectionPageCounts(
            savedProgress.section_page_counts,
          );
        // Show the stored percentage immediately; the first relocated
        // recomputes it from the restored position.
        emitProgress();

        restoringProgress = true;
        if (
          savedProgress.section_page != null &&
          savedProgress.font_size === fontSize &&
          rendition.manager
        ) {
          rendition.manager._lastTargetPage = Math.max(
            0,
            savedProgress.section_page - 1,
          );
        }

        await rendition.display(savedProgress.cfi);

        // Page-based scroll correction: CFI-based restore loses character offset precision
        // causing off-by-one page errors. After display resolves (manager now exists),
        // override scroll position using the saved section page number.
        if (
          savedProgress.section_page != null &&
          savedProgress.font_size === fontSize &&
          rendition.manager
        ) {
          const mgr = rendition.manager;
          const targetPage = Math.max(0, savedProgress.section_page - 1); // 0-indexed
          mgr._lastTarget = null; // Prevent CFI-based re-scroll in afterResized
          mgr._lastTargetPage = targetPage;
          if (typeof mgr.scrollToPageIndex === "function") {
            const ok = mgr.scrollToPageIndex(targetPage);
            // For horizontal: clear only on success. If scrollWidth isn't
            // fully expanded yet, afterResized will retry with _lastTargetPage.
            // For vertical: never clear here because pageStep may change
            // after font/CSS load (e.g. 871 → 851). afterResized will
            // re-apply with the stable pageStep and clear it then.
            if (ok && mgr?.settings?.axis !== "vertical") {
              mgr._lastTargetPage = null;
            }
          }
          // else: afterResized will handle when scrollWidth/scrollHeight expands
        }
        await new Promise((resolve) => requestAnimationFrame(resolve));
        restoringProgress = false;
        rendition.reportLocation?.();
      } else {
        emitProgress();
        await rendition.display();
      }
    } catch {
      restoringProgress = false;
      // The saved CFI no longer resolves (the file was rewritten since it
      // was recorded). Degrade to the stored percentage instead of silently
      // opening at page 1 — now if locations are ready (image books always
      // are), otherwise once generation finishes. Explicit jump targets
      // (initialCfi) get no fallback: progress isn't where they asked to go.
      const fallbackPct = !initialCfi
        ? (savedProgress?.percentage ?? null)
        : null;
      if (fallbackPct != null && (await displayPercentage(fallbackPct))) {
        onrestorefallback?.(fallbackPct);
      } else {
        restoreFallbackPct = fallbackPct;
        await rendition.display();
      }
    }

    // Fix half-page offset on re-enter: snap scroll position after layout settles.
    // For vertical paginated, pageStep may change after CSS recalculation
    // (e.g. container 871 → 851 after font load) leaving scrollTop misaligned.
    setTimeout(() => {
      const mgr = rendition?.manager;
      if (mgr?.settings?.axis === "vertical" && mgr?.isPaginated) {
        const pageStep =
          typeof mgr.getPageStep === "function" ? mgr.getPageStep() : 0;
        const scrollTop = mgr.container?.scrollTop;
        if (pageStep > 0 && scrollTop != null) {
          const remainder = scrollTop % pageStep;
          if (remainder > 2 && pageStep - remainder > 2) {
            const page = Math.round(scrollTop / pageStep);
            if (typeof mgr.scrollToPageIndex === "function") {
              mgr.scrollToPageIndex(page);
            }
          }
        }
      } else if (mgr?.snap) {
        mgr.snap.snap(0);
      }
    }, 150);

    // Apply existing highlights & illustrations
    applyAllHighlights();
    // ...then verify their anchors in the background and heal the ones the
    // file rewrite moved (best-effort; never blocks reading).
    void healHighlights();
    applyAllIllustrations();

    // Get book title & TOC
    epubBook.loaded.metadata
      .then((meta: { title?: string; direction?: string }) => {
        if (meta.title) ontitle?.(meta.title);
        if (meta.direction === "rtl") {
          isRtl = true;
          ondirection?.(true);
        }
      })
      .catch(() => {});
    epubBook.loaded.navigation
      .then(
        (nav: { toc: { label: string; href: string; subitems?: any[] }[] }) => {
          tocData = nav.toc;
          ontoc?.(nav.toc);
          // The first relocated usually beats the TOC load and resolves to
          // an empty href; re-emit now that labels can resolve.
          if (lastLocation) {
            onhrefchange?.(doFindActiveTocHref(currentSectionIndex));
          }
        },
      )
      .catch(() => {});

    // Save progress every 30s as backup (without tracking reading activity)
    const PROGRESS_SAVE_INTERVAL_MS = 30000;
    progressTimer = setInterval(
      () => saveProgress(false),
      PROGRESS_SAVE_INTERVAL_MS,
    );
    window.addEventListener("beforeunload", handleBeforeUnload);

    // Both used to wait for locations generation; the weight-derived
    // percentage is available immediately, so resolve them right away.
    void resolveRestoreFallback().then(() => resolveKosyncMarker());

    // Fix layout offset when returning to the app (e.g. iOS task switcher)
    handleVisibility = () => {
      if (document.visibilityState === "visible" && rendition) {
        rendition.resize();
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);

    onready?.();
  }

  onDestroy(() => {
    if (progressTimer) clearInterval(progressTimer);
    if (saveDebounceTimer) clearTimeout(saveDebounceTimer);
    if (flashTimer) clearTimeout(flashTimer);
    saveProgress(false);
    window.removeEventListener("beforeunload", handleBeforeUnload);
    document.removeEventListener("keyup", handleKeyboard);
    if (handleVisibility)
      document.removeEventListener("visibilitychange", handleVisibility);
    rendition?.destroy();
    epubBook?.destroy();
    delete (window as { __beepubReader?: unknown }).__beepubReader;
  });

  function handleBeforeUnload() {
    if (!currentCfi) return;
    if (restoreFallbackPct != null && !userNavigated) return;
    if (peekSaveHold) return;
    sync.saveProgressBeacon(bookId, buildProgressSave(false));
  }

  function handleKeyboard(e: KeyboardEvent) {
    showFootnote = false;
    const tag = (e.target as HTMLElement)?.tagName;
    if (
      tag === "INPUT" ||
      tag === "TEXTAREA" ||
      (e.target as HTMLElement)?.isContentEditable
    )
      return;
    if (e.key === "ArrowLeft") isRtl ? _doNext() : _doPrev();
    if (e.key === "ArrowRight") isRtl ? _doPrev() : _doNext();
  }

  let wheelDebounce = 0;
  function handleWheel(e: WheelEvent) {
    e.preventDefault();
    const now = Date.now();
    if (now - wheelDebounce < 300) return;
    wheelDebounce = now;
    const nextByY = e.deltaY > 0;
    const prevByY = e.deltaY < 0;
    const nextByX = isRtl ? e.deltaX < 0 : e.deltaX > 0;
    const prevByX = isRtl ? e.deltaX > 0 : e.deltaX < 0;
    if (nextByY || nextByX) {
      _doNext();
    } else if (prevByY || prevByX) {
      _doPrev();
    }
  }

  function handleLeftTapNav() {
    if (showFootnote || showHighlightMenu) return;
    isRtl ? _doNext() : _doPrev();
  }

  function handleRightTapNav() {
    if (showFootnote || showHighlightMenu) return;
    isRtl ? _doPrev() : _doNext();
  }

  function debouncedSave() {
    if (saveDebounceTimer) clearTimeout(saveDebounceTimer);
    saveDebounceTimer = setTimeout(saveProgress, 2000);
  }

  /** One builder for both the normal save and the unload beacon so the
   *  two payloads can't drift. The weight-derived percentage is always
   *  available, so every save carries position and percentage together —
   *  a stored record can no longer hold a CFI that outran its percentage.
   *  Units: reader percentage is 0..100, locator totalProgression is 0..1. */
  function buildProgressSave(trackActivity: boolean): ProgressSave {
    return {
      locator: locatorFromCfi(currentCfi, {
        totalProgression: currentPercentage / 100,
        position: currentPage,
      }),
      fontSize,
      sectionIndex: currentSectionIndex,
      sectionPage: currentSectionPage,
      sectionPageCounts: normalizeSectionPageCounts(sectionPageCounts),
      totalPages,
      // Only ship the xpointer computed for exactly this CFI — a stale one
      // would point e-readers at the previous page's paragraph. Absent →
      // the server degrades to chapter-start synthesis.
      xpointer: currentXpointerCfi === currentCfi ? currentXpointer : null,
      trackActivity,
    };
  }

  async function saveProgress(trackActivity = true) {
    if (!currentCfi) return;
    if (restoreFallbackPct != null && !userNavigated) return;
    if (peekSaveHold) return;
    try {
      await sync.saveProgress(bookId, buildProgressSave(trackActivity));
    } catch {}
  }

  /** Parent-triggered save (the manual sync buttons): cancel the debounce
   *  and persist the current position through the backend right now. */
  export async function flushProgress(): Promise<void> {
    if (saveDebounceTimer) clearTimeout(saveDebounceTimer);
    await saveProgress(false);
  }

  function doUpdateOverlays() {
    updateIllustrationOverlays(rendition, illustrations, onillustrationclick);
  }

  // Single source for the selection tint: the theme's ::selection rule and
  // the iOS touch-selection overlay (which paints its own rects because
  // native selection is disabled there) must stay the same color.
  function selectionTint() {
    return darkMode
      ? { rgb: "245, 158, 11", opacity: 0.4 }
      : { rgb: "196, 146, 74", opacity: 0.3 };
  }

  function applyTheme() {
    if (!rendition) return;
    const selTint = selectionTint();
    rendition.themes.default({
      // Set the size on the root too, not just body: a book whose own CSS
      // targets `p { font-size: 1rem }` would otherwise win over the value
      // `p` inherits from body (a direct match beats inheritance, even with
      // !important on body). Sizing the root makes `rem` resolve to the
      // user's size, so rem-based book rules scale with the setting while
      // the book's relative hierarchy (em/%/headings) is preserved.
      html: {
        "font-size": `${fontSize}px !important`,
      },
      body: {
        "font-family": fontFamily === "serif" ? SERIF_FONTS : SANS_FONTS,
        "font-size": `${fontSize}px !important`,
        "line-height": `${lineHeight}`,
        "-webkit-text-size-adjust": "100%",
        "text-size-adjust": "100%",
        color: darkMode ? "#ece5da" : "#1a1a1a",
        background: darkMode ? "#171310" : "#ffffff",
      },
      // A book that colors text through element selectors (`p { color: #000 }`,
      // common in InDesign/Calibre output) beats the color set on body — a
      // direct match wins over inheritance. In dark mode force those elements
      // back to inherit so the themed color applies; class selectors
      // (intentionally colored spans) are more specific and still win, and
      // light mode leaves the book's palette untouched.
      ...(darkMode
        ? {
            "p, div, span, li, ul, ol, dl, dt, dd, table, tr, td, th, caption, h1, h2, h3, h4, h5, h6, blockquote, pre, code, section, article, aside, figure, figcaption, small, em, strong, b, i, u":
              {
                color: "inherit",
              },
            // Book CSS link colors (typically #0000ff) are unreadable on the
            // dark background; class-colored links still override this.
            a: {
              color: "#d8a558",
            },
          }
        : {}),
      // No padding here: page margins belong to the layout gap (see
      // renderTo) — epub.js pins them as inline !important styles that
      // a theme rule couldn't override on the pagination axis anyway.
      "::selection": {
        background: `rgba(${selTint.rgb}, ${selTint.opacity})`,
      },
    });
    rendition.themes.select("default");
  }

  function applyAllHighlights() {
    if (!rendition) return;
    for (const h of highlights) {
      addHighlightAnnotation(h.cfi_range, h.color);
    }
  }

  // Highlights whose anchor couldn't be verified or healed — surfaced in
  // the sidebar instead of silently never painting.
  let brokenHighlightIds = new Set<string>();

  /**
   * Verify every highlight's CFI against the actual book and heal the ones
   * the file rewrite moved: swap the annotation, persist the new anchor,
   * and report the rest as broken.
   */
  async function healHighlights() {
    if (isImageBook || !epubBook || highlights.length === 0) return;
    try {
      const report = await verifyHighlightAnchors(epubBook, highlights);
      for (const heal of report.healed) {
        const h = highlights.find((x) => x.id === heal.id);
        if (!h) continue;
        removeHighlightAnnotation(heal.oldCfi);
        h.cfi_range = heal.cfi;
        h.section_index = heal.sectionIndex;
        addHighlightAnnotation(heal.cfi, h.color);
        if (!offline) {
          // Silent by design: the writeback can 404 when the highlight was
          // deleted (tombstoned) on another device mid-heal.
          sync
            .updateHighlight(bookId, heal.id, {
              cfi_range: heal.cfi,
              section_index: heal.sectionIndex,
            })
            .catch(() => {});
        }
      }
      if (report.healed.length) {
        highlights = [...highlights];
        onhighlightschange?.(highlights);
      }
      brokenHighlightIds = new Set(report.broken);
      if (report.broken.length) {
        onbrokenhighlights?.(report.broken);
      }
    } catch {
      // Verification is best-effort; a failure here must never break reading.
    }
  }

  function applyAllIllustrations() {
    if (!rendition) return;
    for (const ill of illustrations) {
      if (ill.status === "completed") {
        addIllustrationAnnotation(ill);
      }
    }
  }

  export function addIllustrationAnnotation(ill: IllustrationOut) {
    if (!rendition) return;
    const exists = illustrations.some((x) => x.id === ill.id);
    if (exists) {
      illustrations = illustrations.map((x) => (x.id === ill.id ? ill : x));
    } else {
      illustrations = [...illustrations, ill];
    }
    doUpdateOverlays();
  }

  export function removeIllustrationAnnotation(cfiRange: string) {
    if (!rendition) return;
    illustrations = illustrations.filter((x) => x.cfi_range !== cfiRange);
    doUpdateOverlays();
  }

  export function updateIllustrations(newIllustrations: IllustrationOut[]) {
    illustrations = newIllustrations;
    onillustrationschange?.(illustrations);
    doUpdateOverlays();
  }

  function _doPrev() {
    showFootnote = false;
    userNavigated = true;
    peekSaveHold = false;
    rendition?.prev();
  }

  function _doNext() {
    if (isAtEnd) {
      onbookend?.();
      return;
    }
    showFootnote = false;
    userNavigated = true;
    peekSaveHold = false;
    rendition?.next();
  }

  export function prev() {
    _doPrev();
  }

  export function next() {
    _doNext();
  }

  // Accepts a TOC href or a spine index — rendition.display takes both.
  export function displayChapter(href: string | number) {
    restoringProgress = false;
    userNavigated = true;
    peekSaveHold = false;
    rendition?.display(href);
  }

  export async function displayPercentage(pct: number): Promise<boolean> {
    if (!rendition) return false;
    const weights = progressWeights();
    if (!weights.length) return false;
    const { sectionIndex, fraction } = positionFromPercent(weights, pct);
    const href = epubBook?.spine?.get(sectionIndex)?.href;
    if (!href) return false;
    await rendition.display(href);
    if (fraction > 0) {
      // Refine within the section once it has rendered: the manager knows
      // its page count only now. Same call user paging goes through — the
      // restore-specific _lastTargetPage machinery is not involved.
      const total = rendition.currentLocation?.()?.start?.displayed?.total;
      if (typeof total === "number" && total > 1) {
        const targetPage = Math.min(total - 1, Math.floor(fraction * total));
        if (targetPage > 0) {
          rendition.manager?.scrollToPageIndex?.(targetPage);
        }
      }
    }
    return true;
  }

  /** TOC label for the chapter a seek to `pct` would land in (scrub
   *  bubble). Skips the DOM refinement in findActiveTocHref by passing a
   *  null rendition — it can only inspect the currently rendered section,
   *  not the seek target. */
  export function chapterAtPercentage(pct: number): string | null {
    if (!epubBook) return null;
    const weights = progressWeights();
    if (!weights.length) return null;
    const index = positionFromPercent(weights, pct).sectionIndex;
    if (index < 0) return null;
    const href = findActiveTocHref(epubBook, null, tocData, index);
    return href ? findTocLabelForHref(tocData, href) : null;
  }

  export function displayCfi(cfi: string) {
    restoringProgress = false;
    userNavigated = true;
    rendition?.display(cfi)?.catch(() => {});
  }

  function startPeek(cfi: string | null, percentage: number | null) {
    if (!cfi) return; // nothing to lose — the book has no position yet
    peekReturn = { cfi, percentage };
    peekSaveHold = true;
    onpeekchange?.({ percentage });
  }

  /**
   * Jump to a highlight as a visit: the pre-jump position stays the saved
   * progress (and the pill's return target) until the reader turns a page.
   * A highlight known to be un-anchorable jumps to its section instead.
   */
  export function displayHighlight(hl: HighlightOut) {
    if (!peekSaveHold) {
      startPeek(currentCfi || null, currentPercentage);
    }
    if (brokenHighlightIds.has(hl.id)) {
      const index = hl.section_index ?? sectionIndexFromCfi(hl.cfi_range);
      const href = index != null ? epubBook?.spine?.get(index)?.href : null;
      if (href) {
        displayCfi(href);
        return;
      }
    }
    displayCfi(hl.cfi_range);
  }

  export async function returnFromPeek() {
    if (!peekReturn) return;
    const { cfi, percentage } = peekReturn;
    peekReturn = null;
    peekSaveHold = false;
    onpeekchange?.(null);
    restoringProgress = false;
    try {
      await rendition?.display(cfi);
    } catch {
      if (percentage != null) await displayPercentage(percentage);
    }
  }

  export function getCurrentCfi(): string {
    return currentCfi;
  }

  let flashCfi: string | null = null;
  let flashTimer: ReturnType<typeof setTimeout> | null = null;

  /**
   * Jump to a search result and briefly highlight the matched range so the
   * reader can spot the hit on the page.
   */
  export async function displaySearchResult(cfi: string) {
    restoringProgress = false;
    userNavigated = true;
    peekSaveHold = false;

    clearFlashHighlight();
    await rendition?.display(cfi);

    flashCfi = cfi;
    rendition?.annotations.highlight(cfi, {}, () => {}, "search-flash", {
      fill: HIGHLIGHT_COLORS.orange,
      "fill-opacity": "0.6",
    });
    flashTimer = setTimeout(clearFlashHighlight, 3000);
  }

  function clearFlashHighlight() {
    if (flashTimer) {
      clearTimeout(flashTimer);
      flashTimer = null;
    }
    if (flashCfi) {
      rendition?.annotations.remove(flashCfi, "highlight");
      flashCfi = null;
    }
  }

  export function addHighlightAnnotation(
    cfiRange: string,
    color: string = "yellow",
  ) {
    const { data, styles } = highlightAnnotationArgs(color);
    rendition?.annotations.highlight(cfiRange, data, () => {}, "hl", styles);
  }

  export function removeHighlightAnnotation(cfiRange: string) {
    rendition?.annotations.remove(cfiRange, "highlight");
  }

  export interface SearchResult {
    cfi: string;
    excerpt: string;
    sectionLabel: string;
    sectionIndex: number;
  }

  /**
   * Search the entire book for a query string.
   * Loads each spine section, runs section.find(), and yields results progressively.
   */
  export async function searchBook(
    query: string,
    onResults: (results: SearchResult[]) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    if (!epubBook?.spine) return;
    const allResults: SearchResult[] = [];
    const spineItems = epubBook.spine.spineItems;

    for (let i = 0; i < spineItems.length; i++) {
      if (signal?.aborted) return;
      const section = spineItems[i];
      try {
        await section.load(epubBook.load.bind(epubBook));
        const matches = section.find(query);
        if (matches.length > 0) {
          // Find section label from TOC (any nesting depth)
          const label =
            findTocLabelForHref(tocData, section.href) || `Section ${i + 1}`;

          for (const match of matches) {
            allResults.push({
              cfi: match.cfi,
              excerpt: match.excerpt,
              sectionLabel: label,
              sectionIndex: i,
            });
          }
          onResults([...allResults]);
        }
      } catch {
        // Skip sections that fail to load (e.g. image-only)
      }
    }
    // Final callback even if no new results in last sections
    onResults([...allResults]);
  }

  /** Clear iOS custom selection state (clear selection + overlay) */
  function clearIOSSelection() {
    const c = rendition?.manager?.getContents?.()?.[0];
    if (!c) return;
    c.document?.body?.classList?.remove("beepub-selecting");
    c.window?.getSelection()?.removeAllRanges();
    const overlay = c.document?.getElementById("beepub-sel-overlay");
    if (overlay) overlay.innerHTML = "";
  }

  $effect(() => {
    fontFamily;
    fontSize;
    lineHeight;
    darkMode;
    if (rendition) {
      applyTheme();
      // A theme change can reflow the text without changing the content's
      // size — no reframe, so the annotation panes never re-measure their
      // ranges and the drawn highlights drift off the words. Repaint them
      // once the reflow has settled.
      requestAnimationFrame(() => {
        rendition?.manager?.views?.forEach(
          (v: { pane?: { render: () => void } }) => v.pane?.render(),
        );
      });
    }
  });

  $effect(() => {
    pageMargin;
    applyPageMargin();
  });

  function applyPageMargin() {
    const mgr = rendition?.manager;
    if (!mgr?.settings) return;
    const gap = pageMargin * 2;
    if (mgr.settings.gap === gap) return;
    mgr.settings.gap = gap;
    dismissMenu();
    // resize() bails out when the stage size is unchanged — a margin
    // change relayouts at the same size, so drop the cached size first.
    // The resize clears and re-renders the views at the current location,
    // which also re-anchors every highlight annotation.
    mgr._stageSize = undefined;
    rendition.resize();
  }

  // Last-used color+style (raw encoded, e.g. "blue:underline") — the plain
  // highlighter button repeats it, the picker row overrides it.
  const HIGHLIGHT_STYLE_KEY = "reader-highlight-style";
  let lastHighlightRaw = $state(
    typeof localStorage !== "undefined"
      ? (localStorage.getItem(HIGHLIGHT_STYLE_KEY) ?? "yellow")
      : "yellow",
  );

  function rememberHighlightRaw(raw: string) {
    lastHighlightRaw = raw;
    try {
      localStorage.setItem(HIGHLIGHT_STYLE_KEY, raw);
    } catch {
      // private mode etc. — losing the preference is fine
    }
  }

  async function handleHighlight(raw?: string): Promise<HighlightOut | null> {
    dismissMenu();
    if (!selectedCfi || !selectedText) return null;
    const colorRaw = raw ?? lastHighlightRaw;
    rememberHighlightRaw(colorRaw);

    try {
      const created = await sync.createHighlight(bookId, {
        cfi_range: selectedCfi,
        text: selectedText,
        color: colorRaw,
        prefix: selectedPrefix || null,
        suffix: selectedSuffix || null,
        section_index: sectionIndexFromCfi(selectedCfi) ?? currentSectionIndex,
      });
      highlights = [...highlights, created];

      addHighlightAnnotation(selectedCfi, colorRaw);
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
      await sync.updateHighlight(bookId, target.id, { color: raw });
      target.color = raw;
      highlights = [...highlights];
      removeHighlightAnnotation(target.cfi_range);
      addHighlightAnnotation(target.cfi_range, raw);
      onhighlightschange?.(highlights);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  // Note editing
  let noteEditorHighlight = $state<HighlightOut | null>(null);

  async function handleNote() {
    if (existingHighlight) {
      dismissMenu();
      noteEditorHighlight = existingHighlight;
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
      const updated = await sync.updateHighlight(bookId, target.id, {
        note,
      });
      highlights = highlights.map((h) => (h.id === updated.id ? updated : h));
      onhighlightschange?.(highlights);
      toastStore.success(m.highlight_note_saved());
      noteEditorHighlight = null;
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function handleShare() {
    dismissMenu();
    if (!existingHighlight) return;
    onshare?.(existingHighlight);
  }

  async function handleCopy() {
    dismissMenu();
    if (!selectedText) return;
    try {
      await navigator.clipboard.writeText(selectedText);
      toastStore.success(m.highlight_copied());
    } catch {
      toastStore.error(m.highlight_copy_failed());
    }
  }

  function handleIllustrate() {
    dismissMenu();
    if (!selectedCfi || !selectedText) return;
    onillustrate?.({ cfiRange: selectedCfi, text: selectedText });
  }

  function handleCompanion() {
    dismissMenu();
    if (!selectedCfi || !selectedText) return;
    oncompanion?.({ cfiRange: selectedCfi, text: selectedText });
  }

  async function handleRemoveHighlight() {
    dismissMenu();
    if (!existingHighlight) return;
    try {
      await sync.deleteHighlight(bookId, existingHighlight.id);
      highlights = highlights.filter((h) => h.id !== existingHighlight!.id);
      rendition?.annotations.remove(selectedCfi, "highlight");
      onhighlightschange?.(highlights);
      toastStore.success(m.book_highlight_removed());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<div
  class="relative w-full h-full overflow-hidden touch-manipulation {darkMode
    ? 'bg-ink-900'
    : 'bg-white'}"
  style="-webkit-touch-callout: none; -webkit-user-select: none; user-select: none;"
>
  <div
    bind:this={container}
    class="w-full h-full overflow-hidden {darkMode ? 'bg-ink-900' : 'bg-white'}"
  ></div>

  <!-- Tap-to-turn zones sized to the page margin so they never cover
       text: at narrow margins a 48px zone would swallow the first line's
       taps (and long-presses) on each edge. -->
  <button
    type="button"
    class="absolute inset-y-0 left-0 z-10"
    style="width: {Math.min(48, pageMargin)}px"
    aria-label={m.reader_prev_page()}
    onclick={handleLeftTapNav}
  ></button>
  <button
    type="button"
    class="absolute inset-y-0 right-0 z-10"
    style="width: {Math.min(48, pageMargin)}px"
    aria-label={m.reader_next_page()}
    onclick={handleRightTapNav}
  ></button>

  {#if showHighlightMenu}
    <div
      bind:this={highlightMenuEl}
      data-testid="highlight-menu"
      class="absolute z-20 transform -translate-x-1/2 -translate-y-full"
      style="left: {highlightMenuX}px; top: {highlightMenuY}px;"
    >
      <HighlightMenu
        hasExisting={!!existingHighlight}
        activeRaw={existingHighlight?.color ?? lastHighlightRaw}
        {offline}
        showAi={aiBookId != null}
        onhighlight={handleHighlight}
        onrestyle={handleRestyle}
        onnote={handleNote}
        onremove={handleRemoveHighlight}
        onillustrate={handleIllustrate}
        oncompanion={handleCompanion}
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

  {#if zoomImageSrc}
    <ImageViewer
      src={zoomImageSrc}
      {darkMode}
      onclose={() => (zoomImageSrc = null)}
    />
  {/if}

  {#if showFootnote}
    <FootnotePopup
      content={footnoteContent}
      {darkMode}
      {fontSize}
      {isRtl}
      sourcePath={footnoteSourcePath}
      onclose={() => (showFootnote = false)}
      onnavigate={(href) => rendition?.display(href)}
    />
  {/if}
</div>
