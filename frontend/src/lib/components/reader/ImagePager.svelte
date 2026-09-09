<script lang="ts">
  /**
   * ImagePager — the renderer for pre-paginated image books (comics packed
   * from a CBZ, bought image-only manga EPUBs). It never lays the wrapper
   * XHTML out: the book's pages are read as a list of images and drawn
   * straight into <img> elements, so a page is one picture fitted to the
   * screen, two pictures side by side on a wide screen, or every picture
   * stacked in a vertical scroll for webtoons.
   *
   * Position is the page: the stored CFI is the page's body, the same shape
   * the current reader restores from, and the percentage is the page's
   * place in the book. Progress saves, the restore chain and the chrome
   * callbacks mirror BookReader so the page around it needs no branches
   * beyond choosing which one to mount.
   *
   * Must sit inside the reader root div (.reader-light / .reader-dark).
   */
  import { onDestroy, onMount, tick } from "svelte";
  import type { Book, NavInput, TocItem } from "$lib/reader/core";
  import type { BookLoader } from "$lib/reader/loaders/types";
  import { PageImageCache } from "$lib/reader/page-images";
  import {
    buildSpreads,
    displayOrder,
    pageFromPercent,
    pagePercent,
    readPages,
    spreadIndexOf,
    type PageEntry,
    type PagerDirection,
    type PagerMode,
  } from "$lib/reader/pages";
  import {
    flattenToc,
    tocLabelForSection,
    type TocEntry,
  } from "$lib/reader/toc";
  import { cfiOf as cfiOfLocator, locatorFromCfi } from "$lib/reading/locator";
  import type { ProgressSave, SyncBackend } from "$lib/reading/sync";
  import * as m from "$lib/paraglide/messages.js";
  import Spinner from "$lib/components/Spinner.svelte";

  let {
    bookId,
    sync,
    book,
    loader,
    initialCfi = null,
    darkMode = false,
    mode = "single",
    direction = "auto",
    onready,
    onerror,
    ontap,
    ontoc,
    onchapter,
    onprogress,
    onactivity,
    onticks,
    ondirection,
    onrestorefallback,
    onatend,
    onbookend,
  }: {
    bookId: string;
    sync: SyncBackend;
    /** The parsed book, handed over by BookReader when it found the layout
     *  pre-paginated; the pager reads its spine and never renders it. */
    book: Book;
    loader: BookLoader;
    initialCfi?: string | null;
    darkMode?: boolean;
    mode?: PagerMode;
    /** Overrides the book's page-progression direction. */
    direction?: PagerDirection;
    /** First page shown. */
    onready?: () => void;
    onerror?: (error: Error) => void;
    /** A tap outside the page-turn zones (the chrome toggles). */
    ontap?: () => void;
    ontoc?: (toc: TocItem[]) => void;
    onchapter?: (chapter: {
      href: string | null;
      label: string | null;
    }) => void;
    onprogress?: (p: { cfi: string; percentage: number }) => void;
    /** A user move (reading activity). */
    onactivity?: () => void;
    onticks?: (ticks: number[]) => void;
    ondirection?: (rtl: boolean, vertical: boolean) => void;
    onrestorefallback?: (percentage: number) => void;
    /** The last page is on screen. */
    onatend?: () => void;
    /** A forward turn past the last page. */
    onbookend?: () => void;
  } = $props();

  const SAVE_DEBOUNCE_MS = 2000;
  const PROGRESS_SAVE_INTERVAL_MS = 30_000;
  const TAP_ZONE = 0.25;
  const SWIPE_THRESHOLD = 50;
  const MOVE_THRESHOLD = 10;
  const DOUBLE_TAP_MS = 300;
  const MAX_SCALE = 5;
  const ZOOM_STEP = 2.5;

  let pages = $state<PageEntry[]>([]);
  let pageIndex = $state(0);
  let container = $state<HTMLDivElement | null>(null);
  let scroller = $state<HTMLDivElement | null>(null);
  let containerWidth = $state(0);
  let containerHeight = $state(0);
  let urls = $state<Record<number, string>>({});
  let failed = $state<Record<number, boolean>>({});
  let pageEls: Record<number, HTMLElement> = {};
  let tocEntries: TocEntry[] = [];
  let cache: PageImageCache | null = null;
  let destroyed = false;
  let restoring = false;
  let started = $state(false);
  let progressTimer: ReturnType<typeof setInterval> | null = null;
  let saveDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  let scrollFrame: number | null = null;
  let resizeObserver: ResizeObserver | null = null;
  let quietScrollUntil = 0;
  let quietTimer: ReturnType<typeof setTimeout> | null = null;

  const rtl = $derived(
    direction === "auto" ? book.dir === "rtl" : direction === "rtl",
  );
  const flow = $derived(mode === "scroll" ? "scroll" : "paged");
  const total = $derived(pages.length);
  const twoPage = $derived(mode === "double");
  const spreads = $derived(buildSpreads(pages, twoPage, rtl));
  const spreadIndex = $derived(spreadIndexOf(spreads, pageIndex));
  const current = $derived(spreads[spreadIndex] ?? []);
  const shown = $derived(displayOrder(current, rtl));
  const atEnd = $derived(total > 0 && spreadIndex >= spreads.length - 1);
  // Whole percents: the chrome prints this number.
  const percentage = $derived(Math.round(pagePercent(pageIndex, total)));

  // ----------------------------------------------------------------- zoom

  let scale = $state(1);
  let tx = $state(0);
  let ty = $state(0);

  function resetZoom() {
    scale = 1;
    tx = 0;
    ty = 0;
  }

  function clampPan() {
    const maxX = ((scale - 1) * containerWidth) / 2;
    const maxY = ((scale - 1) * containerHeight) / 2;
    tx = Math.min(maxX, Math.max(-maxX, tx));
    ty = Math.min(maxY, Math.max(-maxY, ty));
  }

  /** Zoom to `next` keeping the point under (px, py) — container-relative,
   *  measured from its centre — where it is. */
  function zoomAt(next: number, px: number, py: number) {
    const target = Math.min(MAX_SCALE, Math.max(1, next));
    const ratio = target / scale;
    tx = px - (px - tx) * ratio;
    ty = py - (py - ty) * ratio;
    scale = target;
    if (scale === 1) {
      tx = 0;
      ty = 0;
    } else clampPan();
  }

  function centreRelative(clientX: number, clientY: number): [number, number] {
    const rect = container?.getBoundingClientRect();
    if (!rect) return [0, 0];
    return [
      clientX - rect.left - rect.width / 2,
      clientY - rect.top - rect.height / 2,
    ];
  }

  // ------------------------------------------------------------ navigation

  function pageAt(index: number): PageEntry | null {
    return pages[Math.min(total - 1, Math.max(0, index))] ?? null;
  }

  function labelFor(index: number, spread: readonly PageEntry[]): string {
    const first = spread[0]?.index ?? index;
    const last = spread[spread.length - 1]?.index ?? index;
    const range = first === last ? `${first + 1}` : `${first + 1}–${last + 1}`;
    const chapter = tocLabelForSection(
      tocEntries,
      pageAt(index)?.sectionIndex ?? 0,
    );
    const counter = `${range} / ${total}`;
    return chapter ? `${chapter} · ${counter}` : counter;
  }

  function emitPosition() {
    const page = pageAt(pageIndex);
    if (!page) return;
    onprogress?.({ cfi: page.cfi, percentage });
    onchapter?.({ href: page.href, label: labelFor(pageIndex, current) });
  }

  /** Land on a page: a user move counts as reading, a restore does not. */
  function goToPage(index: number, reason: "user" | "restore") {
    if (!total) return;
    const clamped = Math.min(total - 1, Math.max(0, index));
    // A pair opens on its first page in reading order so the spread it
    // belongs to is stable across resizes.
    const spread = spreads[spreadIndexOf(spreads, clamped)];
    const wasAtEnd = atEnd;
    pageIndex = spread?.[0]?.index ?? clamped;
    resetZoom();
    emitPosition();
    if (flow === "scroll") scrollToPage(pageIndex);
    if (reason === "user") {
      onactivity?.();
      debouncedSave();
    }
    if (atEnd && !wasAtEnd) onatend?.();
  }

  export function next() {
    if (spreadIndex >= spreads.length - 1) {
      onbookend?.();
      return;
    }
    goToPage(spreads[spreadIndex + 1][0].index, "user");
  }

  export function prev() {
    if (spreadIndex <= 0) return;
    goToPage(spreads[spreadIndex - 1][0].index, "user");
  }

  /** The page on the left / right of the screen: reading direction decides
   *  which one is "forward". */
  function goLeft() {
    if (rtl) next();
    else prev();
  }
  function goRight() {
    if (rtl) prev();
    else next();
  }

  function pageForCfi(cfi: string): number | null {
    try {
      const index = book.resolveCFI(cfi)?.index;
      if (typeof index !== "number") return null;
      return pages.find((p) => p.sectionIndex === index)?.index ?? null;
    } catch {
      return null;
    }
  }

  function pageForTarget(target: NavInput | string): number | null {
    if (typeof target === "number")
      return pages.find((p) => p.sectionIndex === target)?.index ?? null;
    if (typeof target === "object")
      return pages.find((p) => p.sectionIndex === target.index)?.index ?? null;
    if (target.startsWith("epubcfi(")) return pageForCfi(target);
    try {
      const index = book.resolveHref(target)?.index;
      if (typeof index !== "number") return null;
      return pages.find((p) => p.sectionIndex === index)?.index ?? null;
    } catch {
      return null;
    }
  }

  /** Jump to a CFI, a TOC href or a spine index. Resolves to whether the
   *  target was found. */
  export function goTo(target: NavInput | string): boolean {
    const index = pageForTarget(target);
    if (index == null) return false;
    goToPage(index, "user");
    return true;
  }

  export function displayChapter(target: NavInput | string) {
    goTo(target);
  }

  export async function displayPercentage(pct: number): Promise<boolean> {
    if (!total) return false;
    goToPage(pageFromPercent(pct, total), "restore");
    return true;
  }

  /** The scrubber: a seek is the reader choosing to read elsewhere. */
  export async function seekPercentage(pct: number): Promise<boolean> {
    if (!total) return false;
    goToPage(pageFromPercent(pct, total), "user");
    return true;
  }

  export function chapterAtPercentage(pct: number): string | null {
    if (!total) return null;
    const index = pageFromPercent(pct, total);
    return labelFor(index, spreads[spreadIndexOf(spreads, index)] ?? []);
  }

  export function getCurrentCfi(): string {
    return pageAt(pageIndex)?.cfi ?? "";
  }

  // ---------------------------------------------------------------- images

  async function loadImage(page: PageEntry) {
    if (!cache || !page.image || urls[page.index] || failed[page.index]) return;
    try {
      const url = await cache.get(page.image);
      if (destroyed) return;
      urls[page.index] = url;
    } catch {
      if (!destroyed) failed[page.index] = true;
    }
  }

  /** A revoked or broken object URL: drop it so the next look reloads. */
  function handleImageError(page: PageEntry) {
    delete urls[page.index];
    void loadImage(page);
  }

  // Paged: the pages on screen, then the neighbours either side.
  $effect(() => {
    if (flow !== "paged" || !started) return;
    const wanted = [...current];
    for (const p of wanted) void loadImage(p);
    const ahead = spreads[spreadIndex + 1] ?? [];
    const behind = spreads[spreadIndex - 1] ?? [];
    const further = spreads[spreadIndex + 2] ?? [];
    cache?.prefetch([...ahead, ...behind, ...further].map((p) => p.image));
  });

  // Scroll: pages near the viewport, tracked by an IntersectionObserver.
  let observer: IntersectionObserver | null = null;
  $effect(() => {
    if (flow !== "scroll" || !started || !scroller) return;
    const root = scroller;
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const index = Number((entry.target as HTMLElement).dataset.page);
          const page = pageAt(index);
          if (page) void loadImage(page);
        }
      },
      { root, rootMargin: "150% 0px" },
    );
    observer = io;
    for (const el of Object.values(pageEls)) io.observe(el);
    return () => {
      io.disconnect();
      observer = null;
    };
  });

  function registerPage(el: HTMLElement, index: number) {
    pageEls[index] = el;
    observer?.observe(el);
    return {
      destroy() {
        observer?.unobserve(el);
        delete pageEls[index];
      },
    };
  }

  function scrollToPage(index: number) {
    const el = pageEls[index];
    const root = scroller;
    if (!el || !root) return;
    quietScrollUntil = performance.now() + 600;
    root.scrollTop = el.offsetTop;
  }

  /** The page under the middle of the viewport becomes the position. A
   *  programmatic scroll (restore, flow switch) is quiet for a moment; a
   *  scroll landing inside that window is re-read once it closes. */
  function handleScroll() {
    if (scrollFrame != null) return;
    scrollFrame = requestAnimationFrame(() => {
      scrollFrame = null;
      readScrollPosition();
    });
  }

  function readScrollPosition() {
    const root = scroller;
    if (!root) return;
    const wait = quietScrollUntil - performance.now();
    if (wait > 0) {
      if (quietTimer == null)
        quietTimer = setTimeout(() => {
          quietTimer = null;
          readScrollPosition();
        }, wait + 20);
      return;
    }
    const middle = root.scrollTop + root.clientHeight / 2;
    let found = pageIndex;
    for (const [key, el] of Object.entries(pageEls)) {
      if (el.offsetTop <= middle && el.offsetTop + el.offsetHeight > middle) {
        found = Number(key);
        break;
      }
    }
    if (found !== pageIndex) {
      const wasAtEnd = atEnd;
      pageIndex = found;
      emitPosition();
      onactivity?.();
      debouncedSave();
      if (atEnd && !wasAtEnd) onatend?.();
    }
  }

  function aspectRatio(page: PageEntry): string {
    return page.width && page.height
      ? `${page.width} / ${page.height}`
      : "2 / 3";
  }

  // -------------------------------------------------------------- gestures

  interface PointerPoint {
    x: number;
    y: number;
  }
  const pointers = new Map<number, PointerPoint>();
  let gesture: {
    startX: number;
    startY: number;
    startTx: number;
    startTy: number;
    startScale: number;
    startDist: number;
    moved: boolean;
    startedAt: number;
    pinched: boolean;
  } | null = null;
  let lastTap: { at: number; x: number; y: number } | null = null;
  let wheelLockUntil = 0;

  function distance(a: PointerPoint, b: PointerPoint) {
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  function handlePointerDown(e: PointerEvent) {
    if (e.button !== 0 && e.pointerType === "mouse") return;
    pointers.set(e.pointerId, { x: e.screenX, y: e.screenY });
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    if (pointers.size === 1) {
      gesture = {
        startX: e.screenX,
        startY: e.screenY,
        startTx: tx,
        startTy: ty,
        startScale: scale,
        startDist: 0,
        moved: false,
        startedAt: performance.now(),
        pinched: false,
      };
    } else if (pointers.size === 2 && gesture) {
      const [a, b] = [...pointers.values()];
      gesture.startDist = distance(a, b);
      gesture.startScale = scale;
      gesture.pinched = true;
    }
  }

  function handlePointerMove(e: PointerEvent) {
    if (!pointers.has(e.pointerId) || !gesture) return;
    pointers.set(e.pointerId, { x: e.screenX, y: e.screenY });
    if (pointers.size >= 2) {
      const [a, b] = [...pointers.values()];
      const dist = distance(a, b);
      if (gesture.startDist > 0) {
        const mid = centreRelative(
          (a.x + b.x) / 2 - (e.screenX - e.clientX),
          (a.y + b.y) / 2 - (e.screenY - e.clientY),
        );
        zoomAt((gesture.startScale * dist) / gesture.startDist, mid[0], mid[1]);
      }
      gesture.moved = true;
      return;
    }
    const dx = e.screenX - gesture.startX;
    const dy = e.screenY - gesture.startY;
    if (Math.abs(dx) > MOVE_THRESHOLD || Math.abs(dy) > MOVE_THRESHOLD)
      gesture.moved = true;
    if (scale > 1) {
      tx = gesture.startTx + dx;
      ty = gesture.startTy + dy;
      clampPan();
    }
  }

  function handlePointerUp(e: PointerEvent) {
    if (!pointers.has(e.pointerId)) return;
    pointers.delete(e.pointerId);
    if (pointers.size > 0 || !gesture) return;
    const g = gesture;
    gesture = null;
    if (g.pinched) {
      if (scale < 1.05) resetZoom();
      return;
    }
    const dx = e.screenX - g.startX;
    const dy = e.screenY - g.startY;
    if (scale === 1 && g.moved) {
      // A horizontal swipe turns the page; the content follows the finger.
      if (Math.abs(dx) >= SWIPE_THRESHOLD && Math.abs(dx) > Math.abs(dy)) {
        if (dx < 0) goRight();
        else goLeft();
      }
      return;
    }
    if (g.moved) return;
    // A tap. Two in quick succession toggle the zoom.
    const now = performance.now();
    const [px, py] = centreRelative(e.clientX, e.clientY);
    if (
      lastTap &&
      now - lastTap.at < DOUBLE_TAP_MS &&
      Math.hypot(lastTap.x - e.clientX, lastTap.y - e.clientY) < 30
    ) {
      lastTap = null;
      if (scale > 1) resetZoom();
      else zoomAt(ZOOM_STEP, px, py);
      return;
    }
    lastTap = { at: now, x: e.clientX, y: e.clientY };
    if (scale > 1) {
      ontap?.();
      return;
    }
    const rect = container?.getBoundingClientRect();
    if (!rect) return;
    const x = e.clientX - rect.left;
    if (x < rect.width * TAP_ZONE) goLeft();
    else if (x > rect.width * (1 - TAP_ZONE)) goRight();
    else ontap?.();
  }

  function handlePointerCancel(e: PointerEvent) {
    pointers.delete(e.pointerId);
    if (pointers.size === 0) gesture = null;
  }

  function handleWheel(e: WheelEvent) {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const [px, py] = centreRelative(e.clientX, e.clientY);
      zoomAt(scale * (e.deltaY < 0 ? 1.1 : 0.9), px, py);
      return;
    }
    if (scale > 1) {
      e.preventDefault();
      tx -= e.deltaX;
      ty -= e.deltaY;
      clampPan();
      return;
    }
    e.preventDefault();
    const now = performance.now();
    if (now < wheelLockUntil) return;
    if (Math.abs(e.deltaY) < 4 && Math.abs(e.deltaX) < 4) return;
    wheelLockUntil = now + 300;
    const forward =
      Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY > 0 : e.deltaX > 0;
    if (forward) next();
    else prev();
  }

  /** Scroll flow: a tap anywhere toggles the chrome (the wheel and the
   *  finger scroll the pages themselves). */
  let scrollTapStart: PointerPoint | null = null;
  function handleScrollPointerDown(e: PointerEvent) {
    scrollTapStart = { x: e.screenX, y: e.screenY };
  }
  function handleScrollPointerUp(e: PointerEvent) {
    const start = scrollTapStart;
    scrollTapStart = null;
    if (!start) return;
    if (Math.hypot(e.screenX - start.x, e.screenY - start.y) > MOVE_THRESHOLD)
      return;
    ontap?.();
  }

  function handleKey(e: KeyboardEvent) {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
    const target = e.target as HTMLElement | null;
    if (target && /^(input|textarea|select)$/i.test(target.tagName)) return;
    if (target?.isContentEditable) return;
    switch (e.key) {
      case "ArrowLeft":
        goLeft();
        break;
      case "ArrowRight":
        goRight();
        break;
      case " ":
      case "PageDown":
        if (flow === "scroll") return;
        next();
        break;
      case "PageUp":
        if (flow === "scroll") return;
        prev();
        break;
      case "ArrowDown":
        if (flow === "scroll") return;
        next();
        break;
      case "ArrowUp":
        if (flow === "scroll") return;
        prev();
        break;
      case "Home":
        goToPage(0, "user");
        break;
      case "End":
        goToPage(total - 1, "user");
        break;
      default:
        return;
    }
    e.preventDefault();
  }

  // -------------------------------------------------------------- progress

  function buildProgressSave(trackActivity: boolean): ProgressSave {
    const page = pageAt(pageIndex)!;
    return {
      locator: locatorFromCfi(page.cfi, {
        totalProgression: percentage / 100,
        position: pageIndex + 1,
      }),
      // No text to size; the wire field is required.
      fontSize: 16,
      sectionIndex: page.sectionIndex,
      sectionPage: 1,
      sectionPageCounts: pages.map(() => 1),
      totalPages: total,
      xpointer: null,
      trackActivity,
    };
  }

  function canSave() {
    return started && total > 0 && !restoring;
  }

  async function saveProgress(trackActivity = true) {
    if (!canSave()) return;
    try {
      await sync.saveProgress(bookId, buildProgressSave(trackActivity));
    } catch {
      // the next move or the interval retries
    }
  }

  function debouncedSave() {
    if (saveDebounceTimer) clearTimeout(saveDebounceTimer);
    saveDebounceTimer = setTimeout(() => void saveProgress(), SAVE_DEBOUNCE_MS);
  }

  export async function flushProgress(): Promise<void> {
    if (saveDebounceTimer) clearTimeout(saveDebounceTimer);
    await saveProgress(false);
  }

  function handleBeforeUnload() {
    if (!canSave()) return;
    sync.saveProgressBeacon(bookId, buildProgressSave(false));
  }

  async function loadSaved(): Promise<{
    cfi: string | null;
    percentage: number | null;
  } | null> {
    try {
      const state = await sync.getProgress(bookId);
      if (!state) return null;
      const totalProgression = state.locator?.locations.totalProgression;
      return {
        cfi: state.locator ? cfiOfLocator(state.locator) : null,
        percentage: totalProgression == null ? null : totalProgression * 100,
      };
    } catch {
      return null;
    }
  }

  // -------------------------------------------------------------- lifecycle

  onMount(async () => {
    const el = container;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      containerWidth = el.clientWidth;
      containerHeight = el.clientHeight;
    });
    ro.observe(el);
    resizeObserver = ro;
    containerWidth = el.clientWidth;
    containerHeight = el.clientHeight;
    cache = new PageImageCache(loader, 32);
    try {
      const [list, saved] = await Promise.all([
        readPages(book, loader),
        loadSaved(),
      ]);
      if (destroyed) return;
      if (!list.length) throw new Error("The book has no pages");
      pages = list;
      tocEntries = flattenToc(book, book.toc);
      ontoc?.(book.toc ?? []);
      ondirection?.(rtl, false);
      onticks?.([]);
      // Open at the saved page: the explicit target, else the saved CFI,
      // else (the file was rewritten since) the stored percentage, else
      // the first page.
      restoring = true;
      let target: number | null = null;
      if (initialCfi) target = pageForCfi(initialCfi);
      if (target == null && saved?.cfi) target = pageForCfi(saved.cfi);
      if (target == null && saved?.percentage != null) {
        target = pageFromPercent(saved.percentage, list.length);
        if (saved.cfi) onrestorefallback?.(saved.percentage);
      }
      started = true;
      goToPage(target ?? 0, "restore");
      restoring = false;
      await tick();
      await Promise.all(current.map((p) => loadImage(p)));
      if (destroyed) return;
      if (flow === "scroll") scrollToPage(pageIndex);
      onready?.();
      progressTimer = setInterval(
        () => void saveProgress(false),
        PROGRESS_SAVE_INTERVAL_MS,
      );
      window.addEventListener("beforeunload", handleBeforeUnload);
      // Debug handle — the only way e2e probes and a device Web Inspector
      // reach the pager (same convention as __beepubReaderNG.core).
      (window as unknown as { __beepubReaderNG?: unknown }).__beepubReaderNG = {
        pager: {
          get page() {
            return pageIndex;
          },
          get total() {
            return total;
          },
          get shown() {
            return shown.map((p) => p.index);
          },
          get twoPage() {
            return twoPage;
          },
          get mode() {
            return mode;
          },
          get flow() {
            return flow;
          },
          get rtl() {
            return rtl;
          },
          get scale() {
            return scale;
          },
          get cfi() {
            return getCurrentCfi();
          },
          get loaded() {
            return current.every((p) => !!urls[p.index]);
          },
          goTo: (index: number) => goToPage(index, "user"),
          next,
          prev,
        },
      };
    } catch (e) {
      console.error(e);
      onerror?.(e instanceof Error ? e : new Error(String(e)));
    }
  });

  // A forced direction flips the tap zones and the scrubber.
  $effect(() => {
    if (started) ondirection?.(rtl, false);
  });

  // Switching into the scroll flow lands on the current page.
  $effect(() => {
    if (flow === "scroll" && started) {
      void tick().then(() => scrollToPage(pageIndex));
    }
  });

  onDestroy(() => {
    destroyed = true;
    if (progressTimer) clearInterval(progressTimer);
    if (saveDebounceTimer) clearTimeout(saveDebounceTimer);
    if (scrollFrame != null) cancelAnimationFrame(scrollFrame);
    if (quietTimer != null) clearTimeout(quietTimer);
    window.removeEventListener("beforeunload", handleBeforeUnload);
    resizeObserver?.disconnect();
    void saveProgress(false);
    cache?.destroy();
    cache = null;
  });
</script>

<svelte:window onkeydown={handleKey} />

<div
  bind:this={container}
  class="relative h-full w-full select-none overflow-hidden {darkMode
    ? 'bg-ink-900'
    : 'bg-background'}"
  data-testid="image-pager"
  data-flow={flow}
>
  {#if flow === "scroll"}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      bind:this={scroller}
      class="relative h-full w-full overflow-y-auto overflow-x-hidden overscroll-contain"
      onscroll={handleScroll}
      onpointerdown={handleScrollPointerDown}
      onpointerup={handleScrollPointerUp}
    >
      <div class="mx-auto w-full max-w-[900px]">
        {#each pages as page (page.index)}
          <div
            class="relative w-full"
            style="aspect-ratio: {aspectRatio(page)};"
            data-page={page.index}
            use:registerPage={page.index}
          >
            {#if urls[page.index]}
              <img
                src={urls[page.index]}
                alt=""
                draggable="false"
                class="block h-full w-full object-contain"
                onerror={() => handleImageError(page)}
              />
            {:else if failed[page.index] || !page.image}
              <div
                class="flex h-full w-full items-center justify-center text-sm {darkMode
                  ? 'text-ink-500'
                  : 'text-muted-foreground'}"
              >
                {m.reader_pager_image_failed()}
              </div>
            {:else}
              <div class="flex h-full w-full items-center justify-center">
                <Spinner class={darkMode ? "border-ink-400" : ""} />
              </div>
            {/if}
          </div>
        {/each}
      </div>
    </div>
  {:else}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="h-full w-full touch-none"
      style="cursor: {scale > 1 ? 'grab' : 'default'};"
      onpointerdown={handlePointerDown}
      onpointermove={handlePointerMove}
      onpointerup={handlePointerUp}
      onpointercancel={handlePointerCancel}
      onwheel={handleWheel}
    >
      <div
        class="flex h-full w-full items-center justify-center will-change-transform"
        style="transform: translate({tx}px, {ty}px) scale({scale}); transform-origin: center center;"
      >
        {#each shown as page, i (page.index)}
          <div
            class="flex h-full items-center {shown.length > 1
              ? `w-1/2 ${i === 0 ? 'justify-end' : 'justify-start'}`
              : 'w-full justify-center'}"
            data-page={page.index}
          >
            {#if urls[page.index]}
              <img
                src={urls[page.index]}
                alt=""
                draggable="false"
                class="block h-full max-h-full w-auto max-w-full object-contain"
                onerror={() => handleImageError(page)}
              />
            {:else if failed[page.index] || !page.image}
              <div
                class="flex h-full w-full items-center justify-center text-sm {darkMode
                  ? 'text-ink-500'
                  : 'text-muted-foreground'}"
              >
                {m.reader_pager_image_failed()}
              </div>
            {:else}
              <div class="flex h-full w-full items-center justify-center">
                <Spinner class={darkMode ? "border-ink-400" : ""} />
              </div>
            {/if}
          </div>
        {/each}
      </div>
    </div>
  {/if}
</div>
