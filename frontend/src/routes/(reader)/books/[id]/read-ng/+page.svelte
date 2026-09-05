<script lang="ts">
  /**
   * read-ng — the route for the new reader engine (reader-ng). Loads a
   * book through BookReader and wraps it in the product chrome that
   * exists so far: a header with the percentage and the highlights /
   * settings entries, the settings sheet, the highlight sidebar and share
   * card, the desktop scrubber with the peek pill, the kosync offer, and
   * the local-first sync triggers around a session.
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
  import { hasServerUrl, isLocalMode } from "$lib/api/client";
  import { resolveReading } from "$lib/reading/resolve";
  import type { BookSource } from "$lib/reading/source";
  import type { SyncBackend } from "$lib/reading/sync";
  import type { LocalBookEntry } from "$lib/services/localLibrary";
  import { getIsOnline } from "$lib/services/network";
  import type { HighlightOut } from "$lib/types";
  import { confirmDialog } from "$lib/stores/confirm";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";
  import type { PageTurnMode } from "$lib/reader/core";
  import BookReader from "$lib/components/reader/BookReader.svelte";
  import GestureHintOverlay from "$lib/components/reader/GestureHintOverlay.svelte";
  import HighlightSidebar from "$lib/components/reader/HighlightSidebar.svelte";
  import ProgressScrubber from "$lib/components/reader/ProgressScrubber.svelte";
  import ReaderSettingsSheet from "$lib/components/reader/ReaderSettingsSheet.svelte";
  import ShareHighlightModal from "$lib/components/ShareHighlightModal.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { Button } from "$lib/components/ui/button";
  import {
    ArrowLeft,
    ChevronLeft,
    ChevronRight,
    Highlighter,
    Settings,
    Undo2,
  } from "@lucide/svelte";

  let bookId = $derived(page.params.id as string);
  let initialCfi = $derived(page.url.searchParams.get("cfi"));

  let source = $state<BookSource | null>(null);
  let sync = $state<SyncBackend | null>(null);
  let localEntry = $state<LocalBookEntry | null>(null);
  let isBeepub = $derived(sync?.kind === "beepub");
  let title = $state("");
  let authors = $state<string[]>([]);
  let sectionWeights = $state<number[] | null>(null);
  let ready = $state(false);
  let rendered = $state(false);
  let loadError = $state<string | null>(null);
  let reader: BookReader | undefined = $state();

  // Highlights: BookReader owns the list and the marks; the page shows
  // the sidebar and the share card.
  let highlights = $state<HighlightOut[]>([]);
  let brokenHighlightIds = $state<Set<string>>(new Set());
  let showHighlights = $state(false);
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

  let showSettings = $state(false);
  let showGestureHint = $state(false);

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
          // Live-session adoption of the server ruler for entries the
          // sync backfill hasn't upgraded yet (persistence is doSync's
          // job); this only makes THIS session measure with real weights.
          if (localEntry.sectionWeights === undefined) {
            const { getLocalBookLinks } =
              await import("$lib/services/localLibrary");
            const serverBookId = (await getLocalBookLinks())[bookId] ?? null;
            if (serverBookId) {
              booksApi
                .get(serverBookId)
                .then((b) => {
                  if (b.section_weights && b.section_weights.length > 0)
                    sectionWeights = b.section_weights;
                })
                .catch(() => {});
            }
          }
        }
      } else {
        booksApi
          .get(bookId)
          .then((b) => {
            title = b.display_title ?? b.title ?? b.epub_title ?? "";
            authors = b.display_authors ?? b.authors ?? b.epub_authors ?? [];
            sectionWeights = b.section_weights ?? null;
          })
          .catch(() => {});
      }
      ready = true;
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

<div
  class="flex h-[100dvh] min-h-0 flex-col {darkMode
    ? 'reader-dark bg-ink-900'
    : 'reader-light bg-background'}"
>
  <header
    class="flex min-h-12 shrink-0 items-center gap-1 border-b border-border px-2 text-foreground"
    style="padding-top: env(safe-area-inset-top, 0px);"
    data-testid="ng-chrome"
  >
    <Button
      variant="ghost"
      size="icon"
      href={localEntry ? "/local" : `/books/${bookId}`}
      aria-label="Back"
    >
      <ArrowLeft />
    </Button>
    <div class="min-w-0 flex-1 truncate text-sm">{title}</div>
    {#if percentage != null}
      <span
        class="text-xs text-muted-foreground tabular-nums"
        data-testid="ng-percent"
      >
        {percentage}%
      </span>
    {/if}
    <Button
      variant="ghost"
      size="icon"
      class="hidden md:inline-flex"
      aria-label="Previous page"
      onclick={() => reader?.prev()}
    >
      <ChevronLeft />
    </Button>
    <Button
      variant="ghost"
      size="icon"
      class="hidden md:inline-flex"
      aria-label="Next page"
      onclick={() => reader?.next()}
    >
      <ChevronRight />
    </Button>
    <Button
      variant="ghost"
      size="icon"
      aria-label={m.reader_highlights()}
      onclick={() => (showHighlights = true)}
    >
      <Highlighter />
    </Button>
    <Button
      variant="ghost"
      size="icon"
      aria-label={m.reader_settings_title()}
      onclick={() => (showSettings = true)}
    >
      <Settings />
    </Button>
  </header>

  <div class="relative min-h-0 flex-1">
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
        onready={() => (rendered = true)}
        onerror={(e) => (loadError = e.message)}
        onhighlightschange={(list) => (highlights = list)}
        onbrokenhighlights={(ids) => (brokenHighlightIds = new Set(ids))}
        onshare={(hl) => (shareHighlight = hl)}
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

    <!-- Bottom progress (desktop; the header carries the number on
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
              onseek={(p) => reader?.seekPercentage(p)}
            />
          </div>
          <div
            class="flex items-center gap-2.5 text-sm min-w-0 max-w-xl {darkMode
              ? 'text-ink-400'
              : 'text-muted-foreground'}"
          >
            <span class="shrink-0">{percentage}%</span>
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
      <GestureHintOverlay
        {darkMode}
        {isRtl}
        onclose={() => (showGestureHint = false)}
      />
    {/if}
  </div>

  {#if showHighlights}
    <HighlightSidebar
      {highlights}
      {bookId}
      {darkMode}
      brokenIds={brokenHighlightIds}
      onselect={(hl) => {
        showHighlights = false;
        void reader?.displayHighlight(hl);
      }}
      ondelete={deleteHighlight}
      onshare={(hl) => (shareHighlight = hl)}
      onclose={() => (showHighlights = false)}
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
  />
</div>
