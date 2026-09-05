<script lang="ts">
  /**
   * read-ng — the route for the new reader engine (reader-ng). Loads a
   * book through BookReader and wraps it in the product chrome the
   * current reader has: the desktop toolbar and the phone top bar, the
   * tap-toggled phone bottom bar, the four sidebars (TOC with recap,
   * search, highlights, AI companion), the settings sheet with the kosync
   * pull/push row, the share card, the desktop scrubber with the peek
   * pill, the kosync offer, and the local-first sync triggers around a
   * session. Every piece of chrome is the shared component the current
   * reader renders; only the engine behind it differs.
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
  import { hasServerUrl, isLocalMode } from "$lib/api/client";
  import { resolveReading } from "$lib/reading/resolve";
  import type { BookSource } from "$lib/reading/source";
  import type { SyncBackend } from "$lib/reading/sync";
  import type { LocalBookEntry } from "$lib/services/localLibrary";
  import { getIsOnline, isOnline } from "$lib/services/network";
  import { authStore } from "$lib/stores/auth";
  import { confirmDialog } from "$lib/stores/confirm";
  import { toastStore } from "$lib/stores/toast";
  import { UserRole, type AiStatus, type HighlightOut } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";
  import type { PageTurnMode, TocItem } from "$lib/reader/core";
  import BookReader from "$lib/components/reader/BookReader.svelte";
  import CompanionSidebar from "$lib/components/reader/CompanionSidebar.svelte";
  import GestureHintOverlay from "$lib/components/reader/GestureHintOverlay.svelte";
  import HighlightSidebar from "$lib/components/reader/HighlightSidebar.svelte";
  import ProgressScrubber from "$lib/components/reader/ProgressScrubber.svelte";
  import ReaderBottomBar from "$lib/components/reader/ReaderBottomBar.svelte";
  import ReaderSettingsSheet from "$lib/components/reader/ReaderSettingsSheet.svelte";
  import ReaderTopBar from "$lib/components/reader/ReaderTopBar.svelte";
  import SearchSidebar from "$lib/components/reader/SearchSidebar.svelte";
  import TocSidebar from "$lib/components/reader/TocSidebar.svelte";
  import Toolbar from "$lib/components/reader/Toolbar.svelte";
  import ShareHighlightModal from "$lib/components/ShareHighlightModal.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Undo2 } from "@lucide/svelte";

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
  let authors = $state<string[]>([]);
  let isImageBook = $state(false);
  let sectionWeights = $state<number[] | null>(null);
  let ready = $state(false);
  let rendered = $state(false);
  let loadError = $state<string | null>(null);
  let reader: BookReader | undefined = $state();

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
    if (activeSidebar) activeSidebar = null;
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
      await reader?.flushProgress();
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

  onMount(async () => {
    try {
      const resolved = await resolveReading(bookId);
      source = resolved.source;
      sync = resolved.sync;
      localEntry = resolved.localEntry;
      if (localEntry) {
        // Local imports carry their own display metadata; there is no
        // server record to fetch it from.
        title = localEntry.title;
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
          if (serverBookId && localEntry.sectionWeights === undefined) {
            booksApi
              .get(serverBookId)
              .then((b) => {
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
            title = b.display_title ?? b.title ?? b.epub_title ?? "";
            authors = b.display_authors ?? b.authors ?? b.epub_authors ?? [];
            isImageBook = b.is_image_book === true;
            sectionWeights = b.section_weights ?? null;
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
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e);
    }
  });

  onDestroy(() => {
    if (!browser || !localEntry) return;
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
  <title>{title ? `${title} · read-ng` : "read-ng"}</title>
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
        offline={!$isOnline}
        backHref={localEntry ? "/local" : null}
        showAi={aiEnabled}
        onprev={() => reader?.prev()}
        onnext={() => reader?.next()}
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
    {#if ready && source && sync}
      <BookReader
        bind:this={reader}
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
        offline={!$isOnline}
        onbook={(b) => {
          // The file's own title until (unless) the record supplies one.
          if (!title && typeof b.metadata?.title === "string")
            title = b.metadata.title;
        }}
        onready={() => (rendered = true)}
        onerror={(e) => (loadError = e.message)}
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
        onprogress={(p) => (percentage = p.percentage)}
        onactivity={() => {
          // beepub-kind saves carry track_activity — the server credits
          // the 'web' device row itself. Local/kosync books tick the
          // device ledger instead.
          if (!isBeepub)
            void import("$lib/services/readingLedger").then(({ tickReading }) =>
              tickReading(),
            );
        }}
        onticks={(t) => (sectionTicks = t)}
        ondirection={(rtl) => (isRtl = rtl)}
        onkosyncposition={handleKosyncPosition}
        onrestorefallback={(pct) =>
          toastStore.info(
            m.reader_restore_fallback({ percentage: Math.round(pct) }),
          )}
        onpeekchange={(peek) => (peekReturn = peek)}
      />
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
              getlabel={(p) => reader?.chapterAtPercentage(p) ?? null}
              onseek={(p) => reader?.seekPercentage(p)}
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

    {#if !rendered && !loadError}
      <div
        class="pointer-events-none absolute inset-0 flex items-center justify-center"
      >
        <Spinner />
      </div>
    {/if}

    {#if loadError}
      <div
        class="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-background px-8 text-center text-foreground"
      >
        <p class="text-sm">The new reader could not open this book.</p>
        <pre
          class="max-w-full overflow-x-auto rounded-md bg-muted p-3 text-left text-xs">{loadError}</pre>
        <Button variant="outline" href={`/books/${bookId}/read`}
          >Open in the current reader</Button
        >
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
          void reader?.displayChapter(href);
          activeSidebar = null;
        }}
        onspine={(spineIndex) => {
          void reader?.displayChapter(spineIndex);
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
        {bookId}
        {darkMode}
        brokenIds={brokenHighlightIds}
        onselect={(hl) => {
          activeSidebar = null;
          void reader?.displayHighlight(hl);
        }}
        ondelete={deleteHighlight}
        onshare={(hl) => (shareHighlight = hl)}
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
      getSeekLabel={(p) => reader?.chapterAtPercentage(p) ?? null}
      onseek={(p) => reader?.seekPercentage(p)}
      {darkMode}
      {isRtl}
      {isImageBook}
      highlightCount={highlights.length}
      offline={!$isOnline}
      showAi={aiEnabled}
      onprev={() => reader?.prev()}
      onnext={() => reader?.next()}
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
    onpageTurnChange={handlePageTurnChange}
    onhelp={() => (showGestureHint = true)}
    onsyncpull={handleKosyncPull}
    onsyncpush={handleKosyncPush}
  />
</div>
