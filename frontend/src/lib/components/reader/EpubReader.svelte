<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { booksApi } from "$lib/api/books";
  import { apiBase, getAuthHeader } from "$lib/api/client";
  import { isNative } from "$lib/platform";
  import { toastStore } from "$lib/stores/toast";
  import { isBookDownloaded, readLocalBook } from "$lib/services/offline";
  import HighlightMenu from "./HighlightMenu.svelte";
  import ImageViewer from "./ImageViewer.svelte";
  import FootnotePopup from "./FootnotePopup.svelte";
  import { setupIOSTouchSelection } from "./ios-touch-selection";
  import { updateIllustrationOverlays } from "./illustration-overlays";
  import { prefetchSections } from "./image-prefetch";
  import { findActiveTocHref } from "./toc-utils";
  import type { HighlightOut, IllustrationOut } from "$lib/types";

  let {
    bookId,
    fontFamily = "serif",
    fontSize = 16,
    darkMode = false,
    isImageBook = false,
    offline = false,
    onprogress,
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
    oncompanion,
    ontap,
    onatend,
    onbookend,
  }: {
    bookId: string;
    fontFamily?: string;
    fontSize?: number;
    darkMode?: boolean;
    isImageBook?: boolean;
    offline?: boolean;
    onprogress?: (detail: { cfi: string; percentage: number }) => void;
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
    oncompanion?: (detail: { cfiRange: string; text: string }) => void;
    ontap?: () => void;
    onatend?: () => void;
    onbookend?: () => void;
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
  let existingHighlight: HighlightOut | null = $state(null);
  let highlightMenuShownAt = 0;
  let highlightMenuEl: HTMLDivElement | undefined = $state();
  let longPressFired = false;
  const MENU_H = 44;

  function setClampedMenuPosition(x: number, y: number) {
    const cw = container?.clientWidth ?? window.innerWidth;
    const menuW = highlightMenuEl?.offsetWidth ?? 0;
    if (menuW > 0) {
      // Menu is rendered, clamp based on actual width (centered via -translate-x-1/2)
      highlightMenuX = Math.max(menuW / 2 + 8, Math.min(cw - menuW / 2 - 8, x));
    } else {
      // Menu not yet rendered, use unclamped — will be corrected on next call
      highlightMenuX = x;
    }
    // If above viewport, show below selection
    highlightMenuY = y < MENU_H + 8 ? y + MENU_H + 16 : y;
  }

  /** Dismiss highlight menu and clear iOS selection overlay */
  function dismissMenu() {
    showHighlightMenu = false;
    clearIOSSelection();
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
    existingHighlight = existing;
    setClampedMenuPosition(
      rect.left - scrollLeft + rect.width / 2,
      rect.top - scrollTop - 8,
    );
    showHighlightMenu = true;
    highlightMenuShownAt = Date.now();
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
  let currentPercentage = 0;

  // TOC tracking
  let tocData: { label: string; href: string; subitems?: any[] }[] = [];

  let progressTimer: ReturnType<typeof setInterval> | null = null;
  let saveDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  let handleVisibility: (() => void) | null = null;

  const HIGHLIGHT_COLORS: Record<string, string> = {
    yellow: "#fef08a",
    green: "#bbf7d0",
    blue: "#bfdbfe",
    pink: "#fbcfe8",
    orange: "#fed7aa",
  };

  const SERIF_FONTS =
    '"Noto Serif CJK TC", "Source Han Serif TC", "Songti TC", "Songti SC", Georgia, "Times New Roman", serif';
  const SANS_FONTS =
    '"Noto Sans CJK TC", "Source Han Sans TC", "PingFang TC", "PingFang SC", "Microsoft JhengHei", "Microsoft YaHei", system-ui, sans-serif';

  function doPrefetch() {
    prefetchSections(epubBook, currentSectionIndex);
  }

  function emitProgress() {
    onprogress?.({ cfi: currentCfi, percentage: currentPercentage });
  }

  function doFindActiveTocHref(sectionIndex: number): string {
    return findActiveTocHref(epubBook, rendition, tocData, sectionIndex);
  }

  onMount(async () => {
    const Epub = (await import("$lib/epubjs/epub.js")).default;

    // Check for offline copy first (native only)
    let localArrayBuffer: ArrayBuffer | null = null;
    if (isNative()) {
      try {
        if (await isBookDownloaded(bookId)) {
          localArrayBuffer = await readLocalBook(bookId);
        }
      } catch {
        // Fall through to online mode
      }
    }

    if (localArrayBuffer) {
      // Offline: load from local ArrayBuffer
      epubBook = Epub(localArrayBuffer, {});
    } else {
      // Online: stream page-by-page from server
      const authHeaders = getAuthHeader();
      const hasAuth = Object.keys(authHeaders).length > 0;

      // In native mode, epub.js needs auth headers on XHR requests for
      // chapter HTML, OPF, etc. Images/CSS in iframes are authenticated
      // via WKWebView's cookie store (login sets an HttpOnly cookie).
      // replacements: "blobUrl" ensures CSS/fonts are fetched via XHR
      // (with auth) and blob-replaced; images are skipped by our patched
      // resources.replacements() and load directly via cookie auth.
      let nativeOpts = {};
      if (hasAuth) {
        const defaultRequest = (await import("$lib/epubjs/utils/request"))
          .default;
        nativeOpts = {
          requestHeaders: authHeaders,
          replacements: "blobUrl",
          requestMethod: (
            url: string,
            type: string,
            withCredentials: boolean,
            headers: Record<string, string>,
          ) => {
            return defaultRequest(url, type, withCredentials, {
              ...authHeaders,
              ...(headers || {}),
            });
          },
        };
      }

      epubBook = Epub(`${apiBase()}/books/${bookId}/content/`, {
        openAs: "directory",
        ...nativeOpts,
      });
    }

    rendition = epubBook.renderTo(container, {
      width: "100%",
      height: "100%",
      spread: "none",
      allowScriptedContent: true,
    });

    // Apply theme
    applyTheme();

    // relocated handler: calculate percentage from section position
    rendition.on("relocated", (location: any) => {
      currentCfi = location.start.cfi;
      currentSectionIndex = location.start.index ?? 0;
      currentSectionPage = location.start.displayed?.page ?? 1;
      const displayedTotal = location.start.displayed?.total ?? 1;
      const totalSections = epubBook?.spine?.spineItems?.length ?? 1;
      currentPercentage = Math.min(
        100,
        Math.max(
          0,
          Math.round(
            ((currentSectionIndex + currentSectionPage / displayedTotal) /
              totalSections) *
              100,
          ),
        ),
      );
      emitProgress();
      onhrefchange?.(doFindActiveTocHref(currentSectionIndex));
      debouncedSave();
      doUpdateOverlays();
      doPrefetch();

      // Track end-of-book state for series navigation
      const wasAtEnd = isAtEnd;
      isAtEnd = !!location.atEnd;
      if (isAtEnd && !wasAtEnd) {
        onatend?.();
      }

      // Cache progress in localStorage for offline/resume fallback
      try {
        localStorage.setItem(
          `reader-progress-${bookId}`,
          JSON.stringify({
            cfi: currentCfi,
            percentage: currentPercentage,
            sectionIndex: currentSectionIndex,
            sectionPage: currentSectionPage,
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

      // Helper: show highlight menu from current selection
      function tryShowMenuFromSelection() {
        if (showHighlightMenu) return;
        const sel = contents.window?.getSelection();
        if (!sel || sel.isCollapsed || !sel.toString().trim()) return;
        const cfiRange = rendition?.manager
          ?.getContents?.()?.[0]
          ?.cfiFromRange?.(sel.getRangeAt(0));
        if (!cfiRange) return;
        const text = sel.toString().trim();
        const existing =
          highlights.find((h: HighlightOut) => h.cfi_range === cfiRange) ??
          null;
        showMenuAtRange(sel.getRangeAt(0), text, cfiRange, existing);
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
          ontapdismiss: dismissMenu,
          isMenuVisible: () => showHighlightMenu,
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
        const text = selection.toString().trim();
        const existing =
          highlights.find((h) => h.cfi_range === cfiRange) ?? null;
        showMenuAtRange(selection.getRangeAt(0), text, cfiRange, existing);
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
      highlights = await booksApi.getHighlights(bookId);
      onhighlightschange?.(highlights);
    } catch {
      // ignore
    }

    // Load illustrations
    try {
      illustrations = await booksApi.getIllustrations(bookId);
      onillustrationschange?.(illustrations);
    } catch {
      // ignore
    }

    // Load saved progress & display
    let savedProgress: any = null;
    try {
      savedProgress = await booksApi.getProgress(bookId);
    } catch {
      // API unreachable (e.g. iOS PWA resume with no network) — try localStorage
      try {
        const cached = localStorage.getItem(`reader-progress-${bookId}`);
        if (cached) {
          const p = JSON.parse(cached);
          savedProgress = {
            cfi: p.cfi,
            percentage: p.percentage,
            section_page: p.sectionPage,
            section_index: p.sectionIndex,
            font_size: p.fontSize,
          };
        }
      } catch {
        // ignore
      }
    }
    try {
      if (savedProgress?.cfi) {
        // Show saved percentage immediately while loading
        if (savedProgress.percentage != null)
          currentPercentage = savedProgress.percentage;
        emitProgress();

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
      } else {
        await rendition.display();
      }
    } catch {
      await rendition.display();
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
    applyAllIllustrations();

    // Get book title & TOC
    epubBook.loaded.metadata.then(
      (meta: { title?: string; direction?: string }) => {
        if (meta.title) ontitle?.(meta.title);
        if (meta.direction === "rtl") {
          isRtl = true;
          ondirection?.(true);
        }
      },
    );
    epubBook.loaded.navigation.then(
      (nav: { toc: { label: string; href: string; subitems?: any[] }[] }) => {
        tocData = nav.toc;
        ontoc?.(nav.toc);
      },
    );

    // Save progress every 30s as backup (without tracking reading activity)
    const PROGRESS_SAVE_INTERVAL_MS = 30000;
    progressTimer = setInterval(
      () => saveProgress(false),
      PROGRESS_SAVE_INTERVAL_MS,
    );
    window.addEventListener("beforeunload", handleBeforeUnload);

    // Fix layout offset when returning to the app (e.g. iOS task switcher)
    handleVisibility = () => {
      if (document.visibilityState === "visible" && rendition) {
        rendition.resize();
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);

    onready?.();
  });

  onDestroy(() => {
    if (progressTimer) clearInterval(progressTimer);
    if (saveDebounceTimer) clearTimeout(saveDebounceTimer);
    saveProgress(false);
    window.removeEventListener("beforeunload", handleBeforeUnload);
    document.removeEventListener("keyup", handleKeyboard);
    if (handleVisibility)
      document.removeEventListener("visibilitychange", handleVisibility);
    rendition?.destroy();
    epubBook?.destroy();
  });

  function handleBeforeUnload() {
    if (!currentCfi) return;
    const data = {
      cfi: currentCfi,
      percentage: currentPercentage,
      font_size: fontSize,
      section_index: currentSectionIndex,
      section_page: currentSectionPage,
      track_activity: false,
    };
    fetch(`${apiBase()}/books/${bookId}/progress`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify(data),
      keepalive: true,
    });
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

  async function saveProgress(trackActivity = true) {
    if (!currentCfi) return;
    try {
      await booksApi.updateProgress(bookId, {
        cfi: currentCfi,
        percentage: currentPercentage,
        font_size: fontSize,
        section_index: currentSectionIndex,
        section_page: currentSectionPage,
        track_activity: trackActivity,
      });
    } catch {}
  }

  function doUpdateOverlays() {
    updateIllustrationOverlays(rendition, illustrations, onillustrationclick);
  }

  function applyTheme() {
    if (!rendition) return;
    rendition.themes.default({
      body: {
        "font-family": fontFamily === "serif" ? SERIF_FONTS : SANS_FONTS,
        "font-size": `${fontSize}px !important`,
        "line-height": "1.8",
        "-webkit-text-size-adjust": "100%",
        "text-size-adjust": "100%",
        color: darkMode ? "#e5e7eb" : "#1a1a1a",
        background: darkMode ? "#111827" : "#ffffff",
        padding: "2rem !important",
      },
      "::selection": {
        background: darkMode
          ? "rgba(245, 158, 11, 0.4)"
          : "rgba(196, 146, 74, 0.3)",
      },
    });
    rendition.themes.select("default");
  }

  function applyAllHighlights() {
    if (!rendition) return;
    for (const h of highlights) {
      const color = HIGHLIGHT_COLORS[h.color] ?? HIGHLIGHT_COLORS.yellow;
      rendition.annotations.highlight(h.cfi_range, {}, () => {}, "hl", {
        fill: color,
        "fill-opacity": "0.5",
      });
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
    rendition?.prev();
  }

  function _doNext() {
    if (isAtEnd) {
      onbookend?.();
      return;
    }
    showFootnote = false;
    rendition?.next();
  }

  export function prev() {
    _doPrev();
  }

  export function next() {
    _doNext();
  }

  export function displayChapter(href: string) {
    rendition?.display(href);
  }

  export function displayCfi(cfi: string) {
    rendition?.display(cfi);
  }

  export function getCurrentCfi(): string {
    return currentCfi;
  }

  export function addHighlightAnnotation(
    cfiRange: string,
    color: string = "yellow",
  ) {
    const fill = HIGHLIGHT_COLORS[color] ?? HIGHLIGHT_COLORS.yellow;
    rendition?.annotations.highlight(cfiRange, {}, () => {}, "hl", {
      fill,
      "fill-opacity": "0.5",
    });
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
          // Find section label from TOC
          const label =
            tocData.find((t) => {
              const tocHref = t.href.split("#")[0];
              const sectionHref = section.href.split("#")[0];
              return tocHref === sectionHref;
            })?.label || `Section ${i + 1}`;

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
    darkMode;
    if (rendition) {
      applyTheme();
    }
  });

  async function handleHighlight() {
    dismissMenu();
    if (!selectedCfi || !selectedText) return;

    try {
      const created = await booksApi.createHighlight(bookId, {
        cfi_range: selectedCfi,
        text: selectedText,
        color: "yellow",
      });
      highlights = [...highlights, created];

      rendition?.annotations.highlight(selectedCfi, {}, () => {}, "hl", {
        fill: HIGHLIGHT_COLORS.yellow,
        "fill-opacity": "0.5",
      });
      onhighlightschange?.(highlights);
      toastStore.success("Highlight saved");
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
      toastStore.success("Copied");
    } catch {
      toastStore.error("Copy failed");
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
      await booksApi.deleteHighlight(bookId, existingHighlight.id);
      highlights = highlights.filter((h) => h.id !== existingHighlight!.id);
      rendition?.annotations.remove(selectedCfi, "highlight");
      onhighlightschange?.(highlights);
      toastStore.success("Highlight removed");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<div
  class="relative w-full h-full overflow-hidden touch-manipulation {darkMode
    ? 'bg-gray-900'
    : 'bg-white'}"
  style="-webkit-touch-callout: none; -webkit-user-select: none; user-select: none;"
>
  <div
    bind:this={container}
    class="w-full h-full overflow-hidden {darkMode
      ? 'bg-gray-900'
      : 'bg-white'}"
  ></div>

  <button
    type="button"
    class="absolute inset-y-0 left-0 z-10 w-12"
    aria-label="Previous page"
    onclick={handleLeftTapNav}
  ></button>
  <button
    type="button"
    class="absolute inset-y-0 right-0 z-10 w-12"
    aria-label="Next page"
    onclick={handleRightTapNav}
  ></button>

  {#if showHighlightMenu}
    <div
      bind:this={highlightMenuEl}
      class="absolute z-20 transform -translate-x-1/2 -translate-y-full"
      style="left: {highlightMenuX}px; top: {highlightMenuY}px;"
    >
      <HighlightMenu
        hasExisting={!!existingHighlight}
        {offline}
        onhighlight={handleHighlight}
        onremove={handleRemoveHighlight}
        onillustrate={handleIllustrate}
        oncompanion={handleCompanion}
        oncopy={handleCopy}
        onshare={handleShare}
        onclose={dismissMenu}
      />
    </div>
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
