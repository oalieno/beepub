<script lang="ts">
  /**
   * read-ng — the route for the new reader engine (reader-ng). Loads a
   * book through BookReader and wraps it in the product chrome the
   * current reader has: the desktop toolbar and the phone top bar, the
   * tap-toggled phone bottom bar, the four sidebars (TOC with recap,
   * search, highlights + illustrations, AI companion), the settings sheet
   * with the kosync pull/push row, the share card, the desktop scrubber
   * with the peek pill, the kosync offer, the AI illustration flow
   * (prompt modal, generation poll, viewer), the automatic reading status
   * (currently reading after a while, finished at the end, both undoable),
   * the book-end overlay with series navigation, the load-error screen,
   * and the local-first sync triggers around a session. Every piece of
   * chrome is the shared component the current reader renders; only the
   * engine behind it differs.
   *
   * Settings persist under the reader-* keys the epub.js reader uses
   * (font, size, line height, theme are shared; the two gutters, letter
   * spacing and page-turn mode have their own keys, and the old single
   * margin seeds both gutters). Query params override for this session
   * only — probes and e2e open at a known geometry — and are not written
   * back: ?font=sans|serif&size=18&lh=1.8&ls=0&mx=32&my=32&dark=1
   * &turn=instant|animated|follow.
   */
  import { onDestroy, onMount } from "svelte";
  import { browser } from "$app/environment";
  import { page } from "$app/state";
  import { booksApi } from "$lib/api/books";
  import { aiApi } from "$lib/api/bookshelves";
  import { coverUrl, hasServerUrl, isLocalMode } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import {
    emptyLocalInteraction,
    readLocalInteraction,
    setLocalReadingStatus,
    type LocalInteractionRecord,
  } from "$lib/reading/local";
  import { resolveReading } from "$lib/reading/resolve";
  import type { BookSource } from "$lib/reading/source";
  import type { SyncBackend } from "$lib/reading/sync";
  import type { LocalBookEntry } from "$lib/services/localLibrary";
  import { getIsOnline, isOnline } from "$lib/services/network";
  import { authStore } from "$lib/stores/auth";
  import { confirmDialog } from "$lib/stores/confirm";
  import { toastStore } from "$lib/stores/toast";
  import {
    UserRole,
    type AiStatus,
    type HighlightOut,
    type IllustrationOut,
    type InteractionOut,
    type SeriesNeighborsOut,
    type StylePromptOut,
  } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";
  import type { Book, PageTurnMode, TocItem } from "$lib/reader/core";
  import type { BookLoader } from "$lib/reader/loaders";
  import {
    isPrePaginated,
    readPages,
    type PageEntry,
    type PagerDirection,
    type PagerMode,
  } from "$lib/reader/pages";
  import BookReader from "$lib/components/reader/BookReader.svelte";
  import ImagePager from "$lib/components/reader/ImagePager.svelte";
  import CompanionSidebar from "$lib/components/reader/CompanionSidebar.svelte";
  import GestureHintOverlay from "$lib/components/reader/GestureHintOverlay.svelte";
  import HighlightSidebar from "$lib/components/reader/HighlightSidebar.svelte";
  import IllustrationPromptModal from "$lib/components/reader/IllustrationPromptModal.svelte";
  import IllustrationViewer from "$lib/components/reader/IllustrationViewer.svelte";
  import ProgressScrubber from "$lib/components/reader/ProgressScrubber.svelte";
  import ReaderBottomBar from "$lib/components/reader/ReaderBottomBar.svelte";
  import ReaderSettingsSheet from "$lib/components/reader/ReaderSettingsSheet.svelte";
  import ReaderTopBar from "$lib/components/reader/ReaderTopBar.svelte";
  import SearchSidebar from "$lib/components/reader/SearchSidebar.svelte";
  import TocSidebar from "$lib/components/reader/TocSidebar.svelte";
  import Toolbar from "$lib/components/reader/Toolbar.svelte";
  import ShareHighlightModal from "$lib/components/ShareHighlightModal.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { BookX, Check, Undo2 } from "@lucide/svelte";

  let bookId = $derived(page.params.id as string);
  let initialCfi = $derived(page.url.searchParams.get("cfi"));

  let source = $state<BookSource | null>(null);
  let sync = $state<SyncBackend | null>(null);
  let localEntry = $state<LocalBookEntry | null>(null);
  let isBeepub = $derived(sync?.kind === "beepub");
  let isKosync = $derived(sync?.kind === "kosync");
  let kosyncBusy = $state<"pull" | "push" | null>(null);
  // Digest-linked server identity of a local book — AI features keep
  // working on downloaded/imported copies while online.
  let serverBookId = $state<string | null>(null);
  let aiEnabled = $derived(
    isBeepub || (!!localEntry && $isOnline && !!serverBookId),
  );
  let aiBookId = $derived(isBeepub ? bookId : serverBookId);
  let aiStatus = $state<AiStatus>({
    companion: false,
    tag: false,
    image: false,
    embedding: false,
  });
  let title = $state("");
  // The record's display title wins over the file's own.
  let hasDbTitle = false;
  let authors = $state<string[]>([]);
  let isImageBook = $state(false);
  let sectionWeights = $state<number[] | null>(null);
  let ready = $state(false);
  let rendered = $state(false);
  let loadError = $state(false);
  let reader: BookReader | undefined = $state();
  let pager: ImagePager | undefined = $state();
  /** Whichever renderer is mounted: the chrome's page turns, seeks and
   *  chapter jumps go to it. */
  const activeReader = () => reader ?? pager;
  /** A pre-paginated book claimed from BookReader before it rendered:
   *  the image pager takes the parsed book and the loader over. */
  let claimed = $state<{
    book: Book;
    loader: BookLoader;
    pages: PageEntry[] | null;
  } | null>(null);
  /** Two ways in: the OPF declares pre-paginated (bought manga, packed
   *  CBZ), or the library classified the book an image book and every
   *  spine item turns out to be a picture — an older image-only EPUB
   *  that never declared its layout. A short text book (a small fixture)
   *  has no images, so it stays with the text reader. */
  async function claimImageBook(b: Book, l: BookLoader): Promise<boolean> {
    if (isPrePaginated(b)) {
      claimed = { book: b, loader: l, pages: null };
      isImageBook = true;
      return true;
    }
    if (!isImageBook) return false;
    const pages = await readPages(b, l);
    if (!pages.length || !pages.every((p) => p.image)) return false;
    claimed = { book: b, loader: l, pages };
    return true;
  }
  // Retry remounts the reader; the watchdog turns a book that never
  // renders into the error state instead of an endless spinner.
  let readerKey = $state(0);
  const LOAD_TIMEOUT_MS = 30_000;
  $effect(() => {
    void readerKey;
    if (!ready || rendered || loadError) return;
    const timer = setTimeout(() => {
      loadError = true;
    }, LOAD_TIMEOUT_MS);
    return () => clearTimeout(timer);
  });
  function retryLoad() {
    loadError = false;
    rendered = false;
    claimed = null;
    readerKey += 1;
  }

  // Auto reading status. Beepub books track it on the server interaction;
  // local books keep a device record that LWW-syncs once linked (and just
  // accumulates while serverless).
  let interaction: InteractionOut | null = $state(null);
  let localInteraction = $state<LocalInteractionRecord | null>(null);
  let readingTimer: ReturnType<typeof setTimeout> | null = null;
  let destroyed = false;
  const READING_DEBOUNCE_MS = 2 * 60 * 1000; // 2 minutes
  let autoReadTriggered = false;
  // Set when the user undoes an auto-"read" mark: they've said no, so don't
  // auto-mark again for the rest of this reading session.
  let autoReadSuppressed = false;
  let reachedEnd = $state(false);

  // Book-end overlay: shown when paging past the last page. Carries the
  // "marked as finished" feedback (a toast here would sit on top of the
  // text and fight the safe area) plus series navigation when available.
  let seriesNeighbors: SeriesNeighborsOut | null = $state(null);
  let seriesFetchPromise: Promise<void> | null = null;
  let showEndOverlay = $state(false);
  // Set when auto-mark-as-read fires; lets the end overlay offer undo.
  let autoReadUndo = $state<{
    status: InteractionOut["reading_status"];
    startedAt: string | null;
    finishedAt: string | null;
  } | null>(null);
  let autoReadReverted = $state(false);

  // AI illustrations: the reader draws the markers and reports the list;
  // the page runs the prompt modal, the generation poll and the viewer.
  let illustrations = $state<IllustrationOut[]>([]);
  let stylePrompts = $state<StylePromptOut[]>([]);
  let showIllustrationModal = $state(false);
  let illustrationModalCfi = $state("");
  let illustrationModalText = $state("");
  let viewingIllustration = $state<IllustrationOut | null>(null);

  // Table of contents: the reader parses it and tracks which entry the
  // page is under; the page shows both.
  let toc = $state<TocItem[]>([]);
  let currentHref = $state("");
  let chapterLabel = $state<string | null>(null);

  // Highlights: BookReader owns the list and the marks; the page shows
  // the sidebar and the share card.
  let highlights = $state<HighlightOut[]>([]);
  let brokenHighlightIds = $state<Set<string>>(new Set());
  let shareHighlight = $state<HighlightOut | null>(null);

  // Progress: the reader owns position and percentage; the page shows
  // them (header, desktop scrubber) and the peek pill's way back.
  let percentage = $state<number | null>(null);
  let isRtl = $state(false);
  // Vertical text on screen: the slide / finger-follow modes don't apply.
  let isVertical = $state(false);
  let sectionTicks = $state<number[]>([]);
  let peekReturn = $state<{ percentage: number | null } | null>(null);
  const peekLabel = $derived(
    peekReturn
      ? peekReturn.percentage != null
        ? m.reader_peek_return_pct({
            percentage: Math.round(peekReturn.percentage),
          })
        : m.reader_peek_return()
      : null,
  );

  // One sidebar at a time; opening one folds the phone bottom bar.
  type Sidebar = "highlights" | "toc" | "search" | "companion";
  let activeSidebar = $state<Sidebar | null>(null);
  let showMobileBottomBar = $state(false);
  let showSettings = $state(false);
  let companionSelectedText = $state<string | null>(null);
  let companionSelectedCfi = $state<string | null>(null);

  function toggleSidebar(name: Sidebar) {
    activeSidebar = activeSidebar === name ? null : name;
    if (activeSidebar) showMobileBottomBar = false;
  }

  function openCompanion(selection?: { cfiRange: string; text: string }) {
    companionSelectedText = selection?.text ?? null;
    companionSelectedCfi = selection?.cfiRange ?? null;
    activeSidebar = "companion";
    showMobileBottomBar = false;
  }

  // A plain tap on the page (not a page turn, not a selection) shows and
  // hides the phone bottom bar — a fixed overlay, so the text never
  // reflows under it.
  function handleReaderTap() {
    if (activeSidebar) return;
    showMobileBottomBar = !showMobileBottomBar;
  }

  // Escape closes the topmost page-level overlay. The settings sheet,
  // share modal and gesture hint own their Escape handling, as do the
  // footnote popup and highlight menu inside the reader.
  function handleGlobalKeydown(e: KeyboardEvent) {
    if (e.key !== "Escape" || e.defaultPrevented) return;
    if (showSettings || shareHighlight || showGestureHint) return;
    if (viewingIllustration) viewingIllustration = null;
    else if (showIllustrationModal) showIllustrationModal = false;
    else if (showEndOverlay) showEndOverlay = false;
    else if (activeSidebar) activeSidebar = null;
  }

  // One-time gesture coach mark on the first book open (shared key with
  // the current reader: seen there is seen here).
  let showGestureHint = $state(false);
  $effect(() => {
    if (!rendered) return;
    try {
      if (!localStorage.getItem("reader-gestures-seen")) showGestureHint = true;
    } catch {
      // private browsing — skip the hint
    }
  });
  function dismissGestureHint() {
    showGestureHint = false;
    try {
      localStorage.setItem("reader-gestures-seen", "1");
    } catch {
      /* ignore */
    }
  }

  // ------------------------------------------------------------ settings

  const KEY = {
    font: "reader-font",
    size: "reader-size",
    lineHeight: "reader-lineheight",
    letterSpacing: "reader-letter-spacing",
    marginX: "reader-margin-x",
    marginY: "reader-margin-y",
    /** The epub.js reader's single inline-padding preset; seeds both
     *  gutters when the split keys are absent. */
    legacyMargin: "reader-margin",
    pageTurn: "reader-page-turn",
    dark: "reader-dark",
    pagerMode: "reader-pager-mode",
    pagerDirection: "reader-pager-direction",
    pagerPadding: "reader-pager-padding",
    /** Per book (suffixed with the id): whether its pairs are staggered
     *  is a fact about the file, not a preference. */
    pagerShift: "reader-pager-shift",
  } as const;

  function stored(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      return null; // private browsing
    }
  }
  function store(key: string, value: string) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* private browsing — the setting holds for this session */
    }
  }

  const q = page.url.searchParams;
  function queryNum(key: string): number | null {
    if (!q.has(key)) return null;
    const v = Number(q.get(key));
    return Number.isFinite(v) ? v : null;
  }
  function storedNum(key: string): number | null {
    const raw = stored(key);
    if (raw == null) return null;
    const v = Number(raw);
    return Number.isFinite(v) ? v : null;
  }
  function pick(queryKey: string, keys: string[], fallback: number): number {
    const fromQuery = queryNum(queryKey);
    if (fromQuery != null) return fromQuery;
    for (const key of keys) {
      const v = storedNum(key);
      if (v != null) return v;
    }
    return fallback;
  }

  function initialFont(): string {
    const fromQuery = q.get("font");
    if (fromQuery === "sans") return "sans-serif";
    if (fromQuery === "serif") return "serif";
    return stored(KEY.font) ?? "serif";
  }
  function initialPageTurn(): PageTurnMode {
    const raw = q.get("turn") ?? stored(KEY.pageTurn);
    return raw === "animated" || raw === "follow" ? raw : "instant";
  }
  // Synchronous (fall back to the app theme) so dark-mode readers don't
  // get a white flash before onMount runs.
  function initialDark(): boolean {
    if (!browser) return false;
    if (q.has("dark")) return q.get("dark") === "1";
    const saved = stored(KEY.dark);
    if (saved !== null) return saved === "1";
    return document.documentElement.classList.contains("dark");
  }

  let fontFamily = $state(browser ? initialFont() : "serif");
  let fontSize = $state(browser ? pick("size", [KEY.size], 16) : 16);
  let lineHeight = $state(browser ? pick("lh", [KEY.lineHeight], 1.8) : 1.8);
  let letterSpacing = $state(browser ? pick("ls", [KEY.letterSpacing], 0) : 0);
  let marginX = $state(
    browser ? pick("mx", [KEY.marginX, KEY.legacyMargin], 32) : 32,
  );
  let marginY = $state(
    browser ? pick("my", [KEY.marginY, KEY.legacyMargin], 32) : 32,
  );
  let pageTurn = $state<PageTurnMode>(browser ? initialPageTurn() : "instant");
  function initialPagerMode(): PagerMode {
    const v = stored(KEY.pagerMode);
    return v === "double" ||
      v === "vertical" ||
      v === "horizontal" ||
      v === "webtoon"
      ? v
      : "single";
  }
  function initialPagerDirection(): PagerDirection {
    const v = stored(KEY.pagerDirection);
    return v === "ltr" || v === "rtl" ? v : "auto";
  }
  let pagerMode = $state<PagerMode>(browser ? initialPagerMode() : "single");
  let pagerDirection = $state<PagerDirection>(
    browser ? initialPagerDirection() : "auto",
  );
  function handlePagerModeChange(value: PagerMode) {
    pagerMode = value;
    store(KEY.pagerMode, value);
  }
  function handlePagerDirectionChange(value: PagerDirection) {
    pagerDirection = value;
    store(KEY.pagerDirection, value);
  }
  const pagerShiftKey = $derived(`${KEY.pagerShift}:${bookId}`);
  let pagerShift = $state(false);
  $effect(() => {
    pagerShift = stored(pagerShiftKey) === "1";
  });
  function handlePagerShiftChange(value: boolean) {
    pagerShift = value;
    store(pagerShiftKey, value ? "1" : "0");
  }
  let pagerPadding = $state(
    browser ? Math.max(0, storedNum(KEY.pagerPadding) ?? 0) : 0,
  );
  function handlePagerPaddingChange(value: number) {
    pagerPadding = value;
    store(KEY.pagerPadding, String(value));
  }
  let darkMode = $state(initialDark());

  function handleFontToggle() {
    fontFamily = fontFamily === "serif" ? "sans-serif" : "serif";
    store(KEY.font, fontFamily);
  }
  function handleFontIncrease() {
    if (fontSize >= 32) return;
    fontSize += 2;
    store(KEY.size, String(fontSize));
  }
  function handleFontDecrease() {
    if (fontSize <= 10) return;
    fontSize -= 2;
    store(KEY.size, String(fontSize));
  }
  function handleLineHeightChange(value: number) {
    lineHeight = value;
    store(KEY.lineHeight, String(value));
  }
  function handleLetterSpacingChange(value: number) {
    letterSpacing = value;
    store(KEY.letterSpacing, String(value));
  }
  function handleMarginXChange(value: number) {
    marginX = value;
    store(KEY.marginX, String(value));
  }
  function handleMarginYChange(value: number) {
    marginY = value;
    store(KEY.marginY, String(value));
  }
  function handlePageTurnChange(value: PageTurnMode) {
    pageTurn = value;
    store(KEY.pageTurn, value);
  }
  function handleThemeToggle() {
    darkMode = !darkMode;
    store(KEY.dark, darkMode ? "1" : "0");
  }

  // ------------------------------------------------------------ kosync

  // Progress bridged from an e-reader (KOReader/Readest via kosync). The
  // reader auto-jumps when the book was never read here; otherwise the
  // jump is a real decision tied to opening the book, so it gets a dialog
  // (the KOReader/Readest convention), not a dismissable toast.
  async function handleKosyncPosition(detail: {
    percentage: number;
    device: string | null;
    sectionIndex: number | null;
    xpointer: string | null;
    autoJumped: boolean;
    localPercentage?: number;
  }) {
    const device = detail.device || "KOReader";
    const pct = Math.round(detail.percentage);
    if (detail.autoJumped) {
      toastStore.info(m.reader_kosync_jumped({ device, percentage: pct }));
      return;
    }
    const jump = await confirmDialog({
      title: m.reader_kosync_dialog_title(),
      description: m.reader_kosync_dialog_body({
        device,
        remote: pct,
        local: Math.round(detail.localPercentage ?? percentage ?? 0),
      }),
      confirmLabel: m.reader_kosync_jump(),
      cancelLabel: m.reader_kosync_dialog_stay(),
    });
    if (jump)
      void reader?.displayKosyncPosition(
        detail.percentage,
        detail.sectionIndex,
        detail.xpointer,
      );
  }

  function kosyncErrorToast(err: unknown) {
    // Manual actions get visible errors, unlike the silent auto path.
    void import("$lib/kosync/client").then(({ KosyncError }) => {
      toastStore.error(
        err instanceof KosyncError && err.kind === "auth"
          ? m.kosync_error_auth()
          : m.kosync_error_network(),
      );
    });
  }

  async function handleKosyncPull() {
    const entry = localEntry;
    if (!entry || kosyncBusy) return;
    kosyncBusy = "pull";
    try {
      const { getKosyncAccount } = await import("$lib/services/kosyncAccount");
      const account = await getKosyncAccount();
      if (!account) return;
      const { manualKosyncPull } = await import("$lib/reading/kosync");
      const result = await manualKosyncPull(account, entry.digest);
      if (result.kind === "none") {
        toastStore.info(m.kosync_pull_none());
      } else if (result.kind === "own") {
        toastStore.info(m.kosync_pull_own());
      } else {
        showSettings = false;
        await handleKosyncPosition({
          percentage: result.position.percentage ?? 0,
          device: result.position.device,
          sectionIndex: result.position.sectionIndex,
          xpointer: result.position.xpointer,
          autoJumped: false,
        });
      }
    } catch (err) {
      kosyncErrorToast(err);
    } finally {
      kosyncBusy = null;
    }
  }

  async function handleKosyncPush() {
    const entry = localEntry;
    if (!entry || kosyncBusy) return;
    kosyncBusy = "push";
    try {
      // Land the current position in the backend first, then force it out.
      await activeReader()?.flushProgress();
      const { manualKosyncPush } = await import("$lib/reading/kosync");
      const pushed = await manualKosyncPush(entry.digest);
      if (pushed) toastStore.success(m.kosync_pushed());
      else toastStore.info(m.kosync_push_not_ready());
    } catch (err) {
      kosyncErrorToast(err);
    } finally {
      kosyncBusy = null;
    }
  }

  // ------------------------------------------------------ reading status

  async function fetchInteractionAndStartTimer() {
    try {
      interaction = await booksApi.getInteraction(bookId);
    } catch {
      /* ignore */
    }
    // Only escalate none / want_to_read.
    if (
      !interaction?.reading_status ||
      interaction.reading_status === "want_to_read"
    ) {
      readingTimer = setTimeout(async () => {
        const prevStatus = interaction?.reading_status ?? null;
        const prevStartedAt = interaction?.started_at ?? null;
        const today = new Date().toISOString().slice(0, 10);
        try {
          await booksApi.updateReadingStatus(bookId, {
            reading_status: "currently_reading",
            started_at: today,
          });
          if (interaction) {
            interaction.reading_status = "currently_reading";
            interaction.started_at = today;
          }
          toastStore.info(m.reader_auto_marked_reading(), {
            duration: 6000,
            action: {
              label: m.common_undo(),
              onclick: () =>
                revertStatus(
                  prevStatus,
                  prevStartedAt,
                  interaction?.finished_at ?? null,
                ),
            },
          });
        } catch {
          /* ignore */
        }
      }, READING_DEBOUNCE_MS);
    }
  }

  // Fire-and-forget push of a local status edit; serverless/unlinked is a
  // silent no-op inside syncLocalBook and the stamped record ships on the
  // next sync opportunity instead.
  function pushLocalInteraction() {
    void import("$lib/services/readingSync").then(({ syncLocalBook }) =>
      syncLocalBook(bookId).catch(() => {}),
    );
  }

  function startLocalReadingTimer() {
    // Same rule as the beepub timer: only escalate none/want_to_read.
    const status = localInteraction?.reading_status;
    if (status && status !== "want_to_read") return;
    readingTimer = setTimeout(async () => {
      const prev = localInteraction ?? emptyLocalInteraction();
      const today = new Date().toISOString().slice(0, 10);
      localInteraction = await setLocalReadingStatus(
        bookId,
        "currently_reading",
        today,
        null,
      );
      pushLocalInteraction();
      toastStore.info(m.reader_auto_marked_reading(), {
        duration: 6000,
        action: {
          label: m.common_undo(),
          onclick: () =>
            revertStatus(
              prev.reading_status,
              prev.started_at,
              prev.finished_at,
            ),
        },
      });
    }, READING_DEBOUNCE_MS);
  }

  async function revertStatus(
    status: InteractionOut["reading_status"],
    startedAt: string | null,
    finishedAt: string | null,
  ) {
    if (localEntry) {
      // The undo is itself a device edit — it gets a fresh stamp and
      // propagates like any other.
      localInteraction = await setLocalReadingStatus(
        bookId,
        status,
        startedAt,
        finishedAt,
      );
      pushLocalInteraction();
      return;
    }
    try {
      await booksApi.updateReadingStatus(bookId, {
        reading_status: status,
        started_at: startedAt,
        finished_at: finishedAt,
      });
      if (interaction) {
        interaction.reading_status = status;
        interaction.started_at = startedAt;
        interaction.finished_at = finishedAt;
      }
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function autoMarkAsRead() {
    const current = localEntry ? localInteraction : interaction;
    if (!current) return;
    if (
      current.reading_status === "read" ||
      current.reading_status === "did_not_finish"
    )
      return;
    const prevStatus = current.reading_status;
    const prevStartedAt = current.started_at ?? null;
    const prevFinishedAt = current.finished_at ?? null;
    const today = new Date().toISOString().slice(0, 10);
    if (localEntry) {
      localInteraction = await setLocalReadingStatus(
        bookId,
        "read",
        current.started_at || today,
        today,
      );
      pushLocalInteraction();
    } else {
      try {
        await booksApi.updateReadingStatus(bookId, {
          reading_status: "read",
          started_at: current.started_at || today,
          finished_at: today,
        });
        if (interaction) {
          interaction.reading_status = "read";
          interaction.finished_at = today;
        }
      } catch {
        return;
      }
    }
    // No toast — the book-end overlay surfaces this with an undo.
    autoReadUndo = {
      status: prevStatus,
      startedAt: prevStartedAt,
      finishedAt: prevFinishedAt,
    };
    autoReadReverted = false;
  }

  function undoAutoRead() {
    if (!autoReadUndo) return;
    autoReadSuppressed = true;
    void revertStatus(
      autoReadUndo.status,
      autoReadUndo.startedAt,
      autoReadUndo.finishedAt,
    );
    autoReadReverted = true;
  }

  // Auto-mark as read when the estimated progress hits 99% (covers books
  // that end with a colophon/back matter the reader never turns to) OR the
  // actual last page is reached (covers books whose estimate stalls below
  // 99%). False positives are recoverable via the undo in the overlay.
  $effect(() => {
    if (
      ((percentage != null && percentage >= 99) || reachedEnd) &&
      !autoReadTriggered &&
      !autoReadSuppressed &&
      (localEntry ? localInteraction : interaction)
    ) {
      autoReadTriggered = true;
      if (readingTimer) {
        clearTimeout(readingTimer);
        readingTimer = null;
      }
      void autoMarkAsRead();
    }
  });

  // ------------------------------------------------------------ book end

  function prefetchSeriesNeighbors() {
    if (!isBeepub) return; // series live on the server
    if (seriesNeighbors || seriesFetchPromise) return;
    seriesFetchPromise = booksApi
      .getSeriesNeighbors(bookId)
      .then((data) => {
        seriesNeighbors = data;
      })
      .catch(() => {
        // Silently fail — no series panel if the prefetch fails
      });
  }

  function formatSeriesIndex(idx: number | null | undefined): string {
    return idx == null ? "" : String(idx);
  }

  function seriesDisplayTotal(): string {
    return formatSeriesIndex(
      seriesNeighbors?.progress?.max_series_index ??
        seriesNeighbors?.progress?.total_in_library,
    );
  }

  async function handleBookEnd() {
    if (seriesFetchPromise) await seriesFetchPromise;
    showEndOverlay = true;
  }

  /** The same reader route for another book (this page, whatever path
   *  it is mounted at). A full load: the reader's state is per book. */
  function openBookHere(id: string) {
    window.location.href = page.url.pathname.replace(bookId, id);
  }

  // ------------------------------------------------------- illustrations

  async function handleIllustrate(detail: { cfiRange: string; text: string }) {
    illustrationModalCfi = detail.cfiRange;
    illustrationModalText = detail.text;
    if (stylePrompts.length === 0) {
      try {
        stylePrompts = await booksApi.getStylePrompts(aiBookId ?? bookId);
      } catch {
        /* ignore */
      }
    }
    showIllustrationModal = true;
  }

  async function handleCreateIllustration(detail: {
    style_prompt?: string;
    custom_prompt?: string;
    reference_images?: Array<{ source: "epub" | "illustration"; path: string }>;
  }) {
    showIllustrationModal = false;
    try {
      const ill = await booksApi.createIllustration(aiBookId ?? bookId, {
        cfi_range: illustrationModalCfi,
        text: illustrationModalText,
        ...detail,
      });
      reader?.addIllustrationAnnotation(ill);
      toastStore.success(m.illustration_generating());
      void pollIllustration(ill.id);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function pollIllustration(illustrationId: string) {
    for (let i = 0; i < 40; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      if (destroyed) return;
      try {
        const ill = await booksApi.getIllustration(
          aiBookId ?? bookId,
          illustrationId,
        );
        if (ill.status === "completed") {
          reader?.addIllustrationAnnotation(ill);
          toastStore.success(m.illustration_ready());
          return;
        }
        if (ill.status === "failed") {
          reader?.addIllustrationAnnotation(ill);
          const msg = ill.error_message ?? "";
          const friendly =
            msg.includes("IMAGE_SAFETY") || msg.includes("SAFETY")
              ? "Content was blocked by safety filters. Try a different text selection."
              : msg.includes("ReadTimeout")
                ? "API request timed out. Please try again later."
                : msg.includes("500")
                  ? "API server error. Please try again later."
                  : msg || "Unknown error";
          toastStore.error(`Generation failed: ${friendly}`);
          return;
        }
      } catch {
        return;
      }
    }
    toastStore.error(m.illustration_timeout());
  }

  async function handleDeleteIllustration(ill: IllustrationOut) {
    try {
      await booksApi.deleteIllustration(aiBookId ?? bookId, ill.id);
      reader?.removeIllustrationAnnotation(ill.cfi_range);
      toastStore.success(m.illustration_deleted());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function handleSelectIllustration(ill: IllustrationOut) {
    void reader?.displayCfi(ill.cfi_range);
    activeSidebar = null;
    viewingIllustration = ill;
  }

  async function deleteHighlight(hl: HighlightOut) {
    if (
      !(await confirmDialog({
        title: m.highlights_delete_confirm(),
        destructive: true,
      }))
    )
      return;
    try {
      await reader?.removeHighlight(hl);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  // ------------------------------------------------------------ lifecycle

  let prevHtmlOverflow = "";
  let prevBodyOverflow = "";

  onMount(async () => {
    // The reader is the whole viewport: nothing behind it may scroll
    // (rubber-banding on iOS drags the page with the finger otherwise).
    prevHtmlOverflow = document.documentElement.style.overflow;
    prevBodyOverflow = document.body.style.overflow;
    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
    try {
      const resolved = await resolveReading(bookId);
      source = resolved.source;
      sync = resolved.sync;
      localEntry = resolved.localEntry;
      if (localEntry) {
        // Local imports carry their own display metadata; there is no
        // server record to fetch it from.
        title = localEntry.title;
        hasDbTitle = true;
        authors = localEntry.authors ?? [];
        isImageBook = localEntry.isImageBook === true;
        sectionWeights = localEntry.sectionWeights ?? null;
        // Pull the linked server state first so the reader restores the
        // newest position — but bounded: past 2.5s the sync continues in
        // the background and this session opens with local state.
        if (!isLocalMode() && hasServerUrl() && getIsOnline()) {
          const { syncLocalBook } = await import("$lib/services/readingSync");
          await Promise.race([
            syncLocalBook(bookId).catch(() => {}),
            new Promise((resolve) => setTimeout(resolve, 2500)),
          ]);
          const { getLocalBookLinks } =
            await import("$lib/services/localLibrary");
          serverBookId = (await getLocalBookLinks())[bookId] ?? null;
          // Live-session adoption of the server ruler for entries the
          // sync backfill hasn't upgraded yet (persistence is doSync's
          // job); this only makes THIS session measure with real weights.
          if (
            serverBookId &&
            (localEntry.sectionWeights === undefined ||
              localEntry.isImageBook === undefined)
          ) {
            booksApi
              .get(serverBookId)
              .then((b) => {
                if (typeof b.is_image_book === "boolean")
                  isImageBook = b.is_image_book;
                if (b.section_weights && b.section_weights.length > 0)
                  sectionWeights = b.section_weights;
              })
              .catch(() => {});
          }
        }
      } else {
        booksApi
          .get(bookId)
          .then((b) => {
            authors = b.display_authors ?? b.authors ?? b.epub_authors ?? [];
            isImageBook = b.is_image_book === true;
            sectionWeights = b.section_weights ?? null;
            if (b.display_title) {
              title = b.display_title;
              hasDbTitle = true;
            }
          })
          .catch(() => {});
      }
      ready = true;
      // AI status is account-level, not book-level — fetch it whenever AI
      // could be shown (beepub books, or a linked local book).
      if (resolved.sync.kind === "beepub" || serverBookId) {
        aiApi
          .getStatus()
          .then((s) => (aiStatus = s))
          .catch(() => {});
      }
      // Reading status lives with the book's identity: the server
      // interaction for beepub books, the device record for local ones
      // (a beepub API write there would be a second writer fighting the
      // LWW merge).
      if (resolved.sync.kind === "beepub") {
        void fetchInteractionAndStartTimer();
      } else if (localEntry) {
        // Read after the opening sync above, so a fresher web-set status
        // is already folded into the record.
        localInteraction =
          (await readLocalInteraction(bookId)) ?? emptyLocalInteraction();
        startLocalReadingTimer();
      }
    } catch (e) {
      console.error(e);
      loadError = true;
    }
  });

  onDestroy(() => {
    if (!browser) return;
    destroyed = true;
    document.documentElement.style.overflow = prevHtmlOverflow;
    document.body.style.overflow = prevBodyOverflow;
    if (readingTimer) clearTimeout(readingTimer);
    if (!localEntry) return;
    // Push this session's reading state. The delay sequences the sync
    // after the reader's final save (parent/child onDestroy ordering
    // isn't contractual).
    const id = bookId;
    const kind = sync?.kind;
    setTimeout(() => {
      void import("$lib/services/readingSync").then(({ syncLocalBook }) =>
        syncLocalBook(id).catch(() => {}),
      );
      // The session's reading time is final — ship the ledger window.
      void import("$lib/services/readingLedger").then(({ pushLedger }) =>
        pushLedger(),
      );
      // Closing the book shouldn't wait out the push throttle.
      if (kind === "kosync") {
        void import("$lib/reading/kosync").then(({ flushKosyncPushes }) =>
          flushKosyncPushes(),
        );
      }
    }, 600);
  });
</script>

<svelte:head>
  <title>{m.reader_page_title({ title: title || "Reading" })}</title>
</svelte:head>

<svelte:window onkeydown={handleGlobalKeydown} />

<div
  class="flex h-[100dvh] min-h-0 flex-col {darkMode
    ? 'reader-dark bg-ink-900'
    : 'reader-light bg-background'}"
>
  <!-- The chrome above the page: the desktop toolbar, or the phone's
       always-visible top bar (its actions live in the tap-toggled bottom
       bar). One wrapper so probes can toggle the whole thing. -->
  <div class="shrink-0" data-testid="ng-chrome">
    <div class="hidden md:block">
      <Toolbar
        {bookId}
        {title}
        {percentage}
        {chapterLabel}
        {darkMode}
        {isRtl}
        {isImageBook}
        highlightCount={highlights.length}
        illustrationCount={illustrations.length}
        offline={!$isOnline}
        backHref={localEntry ? "/local" : null}
        showAi={aiEnabled}
        onprev={() => activeReader()?.prev()}
        onnext={() => activeReader()?.next()}
        onthemeToggle={handleThemeToggle}
        onhighlights={() => toggleSidebar("highlights")}
        oncompanion={() => openCompanion()}
        onsearch={() => toggleSidebar("search")}
        ontoc_toggle={() => toggleSidebar("toc")}
        onsettings={() => (showSettings = true)}
        onhelp={() => (showGestureHint = true)}
      />
    </div>
    <ReaderTopBar
      {bookId}
      {title}
      {percentage}
      {chapterLabel}
      {darkMode}
      backHref={localEntry ? "/local" : null}
    />
  </div>

  <!-- md:pb reserves a sliver for the collapsed progress line so book text
       can never sit on it, even with the gutters at their minimum. -->
  <div class="relative min-h-0 flex-1 md:pb-2.5">
    {#if ready && source && sync && !loadError}
      {#key readerKey}
        {#if claimed}
          <ImagePager
            bind:this={pager}
            {bookId}
            {sync}
            book={claimed.book}
            loader={claimed.loader}
            pages={claimed.pages}
            {initialCfi}
            {darkMode}
            mode={pagerMode}
            direction={pagerDirection}
            shift={pagerShift}
            padding={pagerPadding}
            onready={() => (rendered = true)}
            onerror={() => (loadError = true)}
            ontap={handleReaderTap}
            ontoc={(t) => (toc = t)}
            onchapter={(c) => {
              currentHref = c.href ?? "";
              chapterLabel = c.label;
            }}
            onprogress={(p) => (percentage = p.percentage)}
            onactivity={() => {
              if (!isBeepub)
                void import("$lib/services/readingLedger").then(
                  ({ tickReading }) => tickReading(),
                );
            }}
            onticks={(t) => (sectionTicks = t)}
            ondirection={(rtl, vertical) => {
              isRtl = rtl;
              isVertical = vertical;
            }}
            onrestorefallback={(pct) =>
              toastStore.info(
                m.reader_restore_fallback({ percentage: Math.round(pct) }),
              )}
            onatend={() => {
              reachedEnd = true;
              prefetchSeriesNeighbors();
            }}
            onbookend={handleBookEnd}
          />
        {:else}
          <BookReader
            bind:this={reader}
            claim={claimImageBook}
            {bookId}
            {source}
            {sync}
            {initialCfi}
            {fontFamily}
            {fontSize}
            {lineHeight}
            {letterSpacing}
            {marginX}
            {marginY}
            {darkMode}
            {pageTurn}
            {sectionWeights}
            showAi={aiEnabled}
            aiBookId={aiEnabled ? aiBookId : null}
            offline={!$isOnline}
            onbook={(b) => {
              // The file's own title unless the record supplied one.
              if (!hasDbTitle && typeof b.metadata?.title === "string")
                title = b.metadata.title;
            }}
            onready={() => (rendered = true)}
            onerror={() => (loadError = true)}
            ontap={handleReaderTap}
            ontoc={(t) => (toc = t)}
            onchapter={(c) => {
              currentHref = c.href ?? "";
              chapterLabel = c.label;
            }}
            onhighlightschange={(list) => (highlights = list)}
            onbrokenhighlights={(ids) => (brokenHighlightIds = new Set(ids))}
            onshare={(hl) => (shareHighlight = hl)}
            oncompanion={openCompanion}
            onillustrate={handleIllustrate}
            onillustrationschange={(list) => (illustrations = list)}
            onillustrationclick={(ill) => (viewingIllustration = ill)}
            onprogress={(p) => (percentage = p.percentage)}
            onactivity={() => {
              // beepub-kind saves carry track_activity — the server credits
              // the 'web' device row itself. Local/kosync books tick the
              // device ledger instead.
              if (!isBeepub)
                void import("$lib/services/readingLedger").then(
                  ({ tickReading }) => tickReading(),
                );
            }}
            onticks={(t) => (sectionTicks = t)}
            ondirection={(rtl, vertical) => {
              isRtl = rtl;
              isVertical = vertical;
            }}
            onkosyncposition={handleKosyncPosition}
            onrestorefallback={(pct) =>
              toastStore.info(
                m.reader_restore_fallback({ percentage: Math.round(pct) }),
              )}
            onpeekchange={(peek) => (peekReturn = peek)}
            onatend={() => {
              reachedEnd = true;
              prefetchSeriesNeighbors();
            }}
            onbookend={handleBookEnd}
          />
        {/if}
      {/key}
    {/if}

    <!-- Bottom progress (desktop; the top bar carries the number on
         phones). Collapsed: a hair-thin line at the bottom edge. Hovering
         the bottom strip (or an active peek, whose return link must be
         discoverable) expands the scrubber + info row as an overlay — no
         layout change, so the text never reflows. -->
    {#if rendered && percentage != null}
      <div
        class="hidden md:block absolute bottom-0 left-0 right-0 z-20 h-4 group"
        data-testid="ng-progress"
      >
        <div
          class="absolute bottom-0 left-0 right-0 h-[3px] overflow-hidden transition-opacity {peekLabel
            ? 'opacity-0'
            : 'group-hover:opacity-0'} {darkMode
            ? 'bg-ink-800'
            : 'bg-secondary'}"
        >
          <div
            class="h-full transition-[width] duration-300 {darkMode
              ? 'bg-ink-500'
              : 'bg-primary'} {isRtl ? 'ml-auto' : ''}"
            style="width: {percentage}%;"
          ></div>
        </div>
        <div
          class="absolute bottom-0 left-0 right-0 flex-col items-center gap-0 px-8 pb-3 pt-8 bg-gradient-to-t to-transparent {darkMode
            ? 'from-ink-900 via-ink-900/85'
            : 'from-white via-white/85'} {peekLabel
            ? 'flex'
            : 'hidden group-hover:flex'}"
        >
          <div class="w-full max-w-xl">
            <ProgressScrubber
              {percentage}
              {darkMode}
              {isRtl}
              ticks={sectionTicks}
              ariaLabel={m.reader_progress()}
              getlabel={(p) => activeReader()?.chapterAtPercentage(p) ?? null}
              onseek={(p) => activeReader()?.seekPercentage(p)}
            />
          </div>
          <div
            class="flex items-center gap-2.5 text-sm min-w-0 max-w-xl {darkMode
              ? 'text-ink-400'
              : 'text-muted-foreground'}"
          >
            <span class="shrink-0">{percentage}%</span>
            {#if chapterLabel}
              <span class="opacity-50 shrink-0">·</span>
              <span class="truncate">{chapterLabel}</span>
            {/if}
            {#if peekLabel}
              <span class="opacity-50">·</span>
              <button
                type="button"
                class="flex items-center gap-1.5 underline underline-offset-4 text-primary transition-opacity hover:opacity-80"
                data-testid="ng-peek-return"
                onclick={() => reader?.returnFromPeek()}
              >
                <Undo2 size={14} />
                {peekLabel}
              </button>
            {/if}
          </div>
        </div>
      </div>
    {/if}

    {#if loadError}
      <div
        class="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 px-8 text-center {darkMode
          ? 'bg-ink-900'
          : 'bg-background'}"
      >
        <BookX
          size={48}
          class={darkMode ? "text-ink-500" : "text-muted-foreground/50"}
        />
        <div class="space-y-1">
          <p
            class="text-base font-medium {darkMode
              ? 'text-ink-200'
              : 'text-foreground'}"
          >
            {m.reader_load_error_title()}
          </p>
          <p
            class="text-sm {darkMode
              ? 'text-ink-400'
              : 'text-muted-foreground'}"
          >
            {m.reader_load_error_desc()}
          </p>
        </div>
        <div class="flex items-center gap-3">
          <button
            class="rounded-lg px-4 py-2 text-sm font-medium transition-colors {darkMode
              ? 'bg-ink-100 text-ink-900 hover:bg-white'
              : 'bg-primary text-primary-foreground hover:bg-primary/90'}"
            onclick={retryLoad}
          >
            {m.common_retry()}
          </button>
          <a
            href={localEntry ? "/local" : `/books/${bookId}`}
            class="rounded-lg px-4 py-2 text-sm font-medium transition-colors {darkMode
              ? 'text-ink-300 hover:bg-ink-800'
              : 'text-muted-foreground hover:bg-secondary'}"
          >
            {m.reader_back_to_detail()}
          </a>
        </div>
      </div>
    {:else if !rendered}
      <!-- Covers the first paint until the position is restored: the
           reader lands on the saved page under this, not in front of
           the user. -->
      <div
        class="absolute inset-0 z-10 flex items-center justify-center {darkMode
          ? 'bg-ink-900'
          : 'bg-white'}"
      >
        <Spinner size="lg" class={darkMode ? "border-ink-400" : ""} />
      </div>
    {/if}

    {#if showGestureHint}
      <GestureHintOverlay {darkMode} {isRtl} onclose={dismissGestureHint} />
    {/if}

    {#if activeSidebar === "toc"}
      <TocSidebar
        {toc}
        {darkMode}
        {currentHref}
        loadRecap={aiBookId && !isImageBook
          ? () => booksApi.getRecap(aiBookId!, reader?.getCurrentCfi() ?? "")
          : null}
        onchapter={(href) => {
          void activeReader()?.displayChapter(href);
          activeSidebar = null;
        }}
        onspine={(spineIndex) => {
          void activeReader()?.displayChapter(spineIndex);
          activeSidebar = null;
        }}
        onclose={() => (activeSidebar = null)}
      />
    {/if}

    {#if activeSidebar === "search" && !isImageBook}
      <SearchSidebar
        {darkMode}
        onselect={(cfi) => {
          void reader?.displaySearchResult(cfi);
          activeSidebar = null;
        }}
        onclose={() => (activeSidebar = null)}
        onsearch={(query, onResults, signal) =>
          reader?.searchBook(query, onResults, signal) ?? Promise.resolve()}
      />
    {/if}

    {#if activeSidebar === "highlights" && !isImageBook}
      <HighlightSidebar
        {highlights}
        {illustrations}
        bookId={aiBookId ?? bookId}
        {darkMode}
        brokenIds={brokenHighlightIds}
        onselect={(hl) => {
          activeSidebar = null;
          void reader?.displayHighlight(hl);
        }}
        ondelete={deleteHighlight}
        onshare={(hl) => (shareHighlight = hl)}
        onillustrationselect={handleSelectIllustration}
        onillustrationdelete={handleDeleteIllustration}
        onclose={() => (activeSidebar = null)}
      />
    {/if}

    {#if activeSidebar === "companion" && !isImageBook}
      <CompanionSidebar
        bookId={aiBookId ?? bookId}
        {darkMode}
        {aiStatus}
        isAdmin={$authStore.user?.role === UserRole.Admin}
        selectedText={companionSelectedText}
        selectedCfi={companionSelectedCfi}
        getCurrentCfi={() => reader?.getCurrentCfi() ?? ""}
        onclose={() => (activeSidebar = null)}
      />
    {/if}
  </div>

  <!-- Phone bottom bar (tap to toggle; a fixed overlay, never in flow) -->
  {#if showMobileBottomBar}
    <ReaderBottomBar
      {percentage}
      {peekLabel}
      onpeekreturn={() => reader?.returnFromPeek()}
      canSeek={true}
      ticks={sectionTicks}
      getSeekLabel={(p) => activeReader()?.chapterAtPercentage(p) ?? null}
      onseek={(p) => activeReader()?.seekPercentage(p)}
      {darkMode}
      {isRtl}
      {isImageBook}
      highlightCount={highlights.length}
      offline={!$isOnline}
      showAi={aiEnabled}
      onprev={() => activeReader()?.prev()}
      onnext={() => activeReader()?.next()}
      ontoc={() => toggleSidebar("toc")}
      onsearch={() => toggleSidebar("search")}
      onhighlights={() => toggleSidebar("highlights")}
      oncompanion={() => openCompanion()}
      onsettings={() => {
        showSettings = true;
        showMobileBottomBar = false;
      }}
    />
  {/if}

  <ShareHighlightModal
    open={shareHighlight !== null}
    highlight={shareHighlight}
    bookTitle={title}
    bookAuthors={authors}
    onclose={() => (shareHighlight = null)}
  />

  <ReaderSettingsSheet
    bind:open={showSettings}
    {fontFamily}
    {fontSize}
    {lineHeight}
    {letterSpacing}
    {marginX}
    {marginY}
    {pageTurn}
    pageTurnNote={isVertical ? m.reader_page_turn_vertical_note() : null}
    {darkMode}
    {isImageBook}
    showSync={isKosync}
    syncBusy={kosyncBusy}
    onfontToggle={handleFontToggle}
    onfontIncrease={handleFontIncrease}
    onfontDecrease={handleFontDecrease}
    onthemeToggle={handleThemeToggle}
    onlineHeightChange={handleLineHeightChange}
    onletterSpacingChange={handleLetterSpacingChange}
    onmarginXChange={handleMarginXChange}
    onmarginYChange={handleMarginYChange}
    onpageTurnChange={claimed ? undefined : handlePageTurnChange}
    {pagerMode}
    {pagerDirection}
    {pagerShift}
    {pagerPadding}
    onpagerModeChange={claimed ? handlePagerModeChange : undefined}
    onpagerDirectionChange={claimed ? handlePagerDirectionChange : undefined}
    onpagerShiftChange={claimed ? handlePagerShiftChange : undefined}
    onpagerPaddingChange={claimed ? handlePagerPaddingChange : undefined}
    onhelp={() => (showGestureHint = true)}
    onsyncpull={handleKosyncPull}
    onsyncpush={handleKosyncPush}
  />

  {#if showIllustrationModal}
    <IllustrationPromptModal
      text={illustrationModalText}
      styles={stylePrompts}
      {darkMode}
      bookId={aiBookId ?? bookId}
      {aiStatus}
      isAdmin={$authStore.user?.role === UserRole.Admin}
      completedIllustrations={illustrations.filter(
        (x) => x.status === "completed",
      )}
      oncreate={handleCreateIllustration}
      onclose={() => (showIllustrationModal = false)}
    />
  {/if}

  {#if viewingIllustration}
    <IllustrationViewer
      illustration={viewingIllustration}
      bookId={aiBookId ?? bookId}
      {darkMode}
      onclose={() => (viewingIllustration = null)}
    />
  {/if}

  {#if showEndOverlay}
    {@const seriesNext = seriesNeighbors?.next}
    {@const seriesProgress = seriesNeighbors?.progress}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      data-testid="book-end"
      onkeydown={(e) => {
        if (e.key === "Escape") showEndOverlay = false;
      }}
      onclick={(e) => {
        if (e.target === e.currentTarget) showEndOverlay = false;
      }}
    >
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div
        class="mx-3 sm:mx-4 w-full max-w-[85vw] sm:max-w-sm md:max-w-md overflow-hidden rounded-2xl shadow-2xl {darkMode
          ? 'bg-ink-800 text-ink-100'
          : 'bg-white text-ink-900'}"
        onclick={(e) => e.stopPropagation()}
      >
        {#if seriesNext}
          <!-- Cover as hero banner -->
          <div
            class="relative flex items-center justify-center py-10 {darkMode
              ? 'bg-ink-900/60'
              : 'bg-ink-50'}"
          >
            {#if seriesNext.cover_path}
              <img
                use:authedSrc={coverUrl(seriesNext.id)}
                alt={seriesNext.title ?? "Next book"}
                class="h-52 sm:h-64 md:h-96 w-auto rounded-md shadow-xl object-cover"
              />
            {:else}
              <div
                class="h-52 sm:h-64 md:h-96 w-48 rounded-md shadow-xl flex items-center justify-center {darkMode
                  ? 'bg-ink-700 text-ink-400'
                  : 'bg-ink-200 text-muted-foreground'}"
              >
                {m.reader_no_cover()}
              </div>
            {/if}
          </div>

          <!-- Info + actions -->
          <div class="px-6 py-6">
            <p
              class="text-center text-xs font-medium uppercase tracking-widest {darkMode
                ? 'text-ink-500'
                : 'text-muted-foreground'}"
            >
              {m.reader_series_up_next({
                series: seriesNeighbors?.series_name ?? "",
              })}
            </p>
            <p class="mt-3 text-center text-xl font-semibold">
              {seriesNext.title ?? "Untitled"}
            </p>
            {#if seriesNext.series_index != null}
              <p
                class="mt-1 text-center text-sm {darkMode
                  ? 'text-ink-400'
                  : 'text-muted-foreground'}"
              >
                {m.reader_series_book_of({
                  index: formatSeriesIndex(seriesNext.series_index),
                  total: seriesDisplayTotal() || "?",
                })}
              </p>
            {/if}
            <div class="mt-6 flex gap-3">
              <button
                class="flex-1 rounded-lg px-4 py-3 font-medium transition-colors {darkMode
                  ? 'bg-ink-700 hover:bg-ink-600 text-ink-300'
                  : 'bg-ink-100 hover:bg-ink-200 text-ink-700'}"
                onclick={() => (showEndOverlay = false)}
              >
                {m.common_close()}
              </button>
              <button
                class="flex-1 rounded-lg bg-primary px-4 py-3 font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                onclick={() => openBookHere(seriesNext.id)}
              >
                {m.reader_start_reading()}
              </button>
            </div>
          </div>
        {:else if seriesProgress}
          <div class="flex flex-col items-center gap-6 px-10 py-14">
            <span class="text-6xl">🎉</span>
            <div class="text-center">
              <p class="text-2xl font-semibold">{m.reader_series_complete()}</p>
              <p
                class="mt-2 {darkMode
                  ? 'text-ink-400'
                  : 'text-muted-foreground'}"
              >
                {m.reader_series_complete_msg({
                  count: String(seriesProgress.total_in_library),
                  series: seriesNeighbors?.series_name ?? "",
                })}
              </p>
            </div>
            <button
              class="rounded-lg px-8 py-3 font-medium transition-colors {darkMode
                ? 'bg-ink-700 hover:bg-ink-600 text-ink-300'
                : 'bg-ink-100 hover:bg-ink-200 text-ink-700'}"
              onclick={() => (showEndOverlay = false)}
            >
              {m.common_close()}
            </button>
          </div>
        {:else}
          <div class="flex flex-col items-center gap-6 px-10 py-14">
            <span class="text-6xl">🎉</span>
            <div class="text-center">
              <p class="text-2xl font-semibold">{m.reader_finished_title()}</p>
              {#if title}
                <p
                  class="mt-2 {darkMode
                    ? 'text-ink-400'
                    : 'text-muted-foreground'}"
                >
                  {title}
                </p>
              {/if}
            </div>
            <button
              class="rounded-lg px-8 py-3 font-medium transition-colors {darkMode
                ? 'bg-ink-700 hover:bg-ink-600 text-ink-300'
                : 'bg-ink-100 hover:bg-ink-200 text-ink-700'}"
              onclick={() => (showEndOverlay = false)}
            >
              {m.common_close()}
            </button>
          </div>
        {/if}

        {#if autoReadUndo}
          <div
            class="flex items-center justify-center gap-2 border-t px-6 py-3.5 text-sm {darkMode
              ? 'border-ink-700 text-ink-400'
              : 'border-ink-100 text-muted-foreground'}"
          >
            {#if autoReadReverted}
              <span>{m.reader_marked_read_undone()}</span>
            {:else}
              <Check size={14} class="text-primary" />
              <span>{m.reader_auto_marked_read()}</span>
              <button
                type="button"
                class="text-primary underline underline-offset-4"
                onclick={undoAutoRead}
              >
                {m.common_undo()}
              </button>
            {/if}
          </div>
        {/if}
      </div>
    </div>
  {/if}
</div>
