<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { browser } from "$app/environment";
  import { page } from "$app/state";
  import { authStore } from "$lib/stores/auth";
  import EpubReader from "$lib/components/reader/EpubReader.svelte";
  import Toolbar from "$lib/components/reader/Toolbar.svelte";
  import ReaderTopBar from "$lib/components/reader/ReaderTopBar.svelte";
  import ReaderBottomBar from "$lib/components/reader/ReaderBottomBar.svelte";
  import ReaderSettingsSheet from "$lib/components/reader/ReaderSettingsSheet.svelte";
  import HighlightSidebar from "$lib/components/reader/HighlightSidebar.svelte";
  import TocSidebar from "$lib/components/reader/TocSidebar.svelte";
  import { booksApi } from "$lib/api/books";
  import { coverUrl } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import { aiApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import { confirmDialog } from "$lib/stores/confirm";
  import { isOnline } from "$lib/services/network";
  import IllustrationPromptModal from "$lib/components/reader/IllustrationPromptModal.svelte";
  import CompanionSidebar from "$lib/components/reader/CompanionSidebar.svelte";
  import SearchSidebar from "$lib/components/reader/SearchSidebar.svelte";
  import IllustrationViewer from "$lib/components/reader/IllustrationViewer.svelte";
  import ShareHighlightModal from "$lib/components/ShareHighlightModal.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import GestureHintOverlay from "$lib/components/reader/GestureHintOverlay.svelte";
  import ProgressScrubber from "$lib/components/reader/ProgressScrubber.svelte";
  import { BookX } from "@lucide/svelte";
  import { UserRole } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";
  import type {
    AiStatus,
    HighlightOut,
    IllustrationOut,
    InteractionOut,
    SeriesNeighborsOut,
    StylePromptOut,
  } from "$lib/types";

  let bookId = $derived(page.params.id as string);
  // Jump target passed from the book detail page (highlight click)
  let initialCfi = $derived(page.url.searchParams.get("cfi"));

  // Auto reading status
  let interaction: InteractionOut | null = $state(null);
  let readingTimer: ReturnType<typeof setTimeout> | null = null;
  let destroyed = false;
  const READING_DEBOUNCE_MS = 2 * 60 * 1000; // 2 minutes
  let autoReadTriggered = false;
  // Set when the user undoes an auto-"read" mark: they've said no, so don't
  // auto-mark again for the rest of this reading session.
  let autoReadSuppressed = false;

  let title = $state("");
  let hasDbTitle = false;
  let fontFamily = $state("serif");
  let fontSize = $state(16);
  let lineHeight = $state(1.8);
  let pageMargin = $state(32);
  // Initialize synchronously (fall back to the app theme) so dark-mode
  // readers don't get a white flash before onMount runs.
  function getInitialDark(): boolean {
    if (!browser) return false;
    try {
      const saved = localStorage.getItem("reader-dark");
      if (saved !== null) return saved === "1";
    } catch {
      // Private browsing — fall through
    }
    return document.documentElement.classList.contains("dark");
  }
  let darkMode = $state(getInitialDark());
  let percentage = $state<number | null>(null);
  let toc = $state<{ label: string; href: string; subitems?: any[] }[]>([]);
  let currentHref = $state("");
  let reader: EpubReader = $state(null as any);
  let ready = $state(false);
  let loadError = $state(false);
  let readerKey = $state(0);
  // Watchdog: if the EPUB hasn't rendered within this window, treat it as a
  // failed load so the user isn't stuck on an infinite spinner.
  const EPUB_LOAD_TIMEOUT_MS = 30_000;
  $effect(() => {
    void readerKey;
    if (!ready || epubLoaded || loadError) return;
    const timer = setTimeout(() => {
      loadError = true;
    }, EPUB_LOAD_TIMEOUT_MS);
    return () => clearTimeout(timer);
  });
  function retryLoad() {
    loadError = false;
    epubLoaded = false;
    readerKey += 1;
  }
  let isRtl = $state(false);
  let highlights = $state<HighlightOut[]>([]);
  let illustrations = $state<IllustrationOut[]>([]);
  let stylePrompts = $state<StylePromptOut[]>([]);
  type Sidebar = "highlights" | "toc" | "search" | "companion";
  let activeSidebar = $state<Sidebar | null>(null);

  let showMobileBottomBar = $state(false);
  let showSettings = $state(false);

  // One-time gesture coach mark on first book open
  let showGestureHint = $state(false);
  $effect(() => {
    if (!epubLoaded) return;
    try {
      if (!localStorage.getItem("reader-gestures-seen")) {
        showGestureHint = true;
      }
    } catch {
      // Private browsing — skip the hint
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

  function toggleSidebar(name: Sidebar) {
    activeSidebar = activeSidebar === name ? null : name;
    if (activeSidebar) showMobileBottomBar = false;
  }

  function handleReaderTap() {
    if (activeSidebar) return;
    showMobileBottomBar = !showMobileBottomBar;
  }
  let companionSelectedText = $state<string | null>(null);
  let companionSelectedCfi = $state<string | null>(null);
  let showIllustrationModal = $state(false);
  let illustrationModalCfi = $state("");
  let illustrationModalText = $state("");

  // Series navigation overlay
  let seriesNeighbors: SeriesNeighborsOut | null = $state(null);
  let seriesFetchPromise: Promise<void> | null = null;
  let showSeriesOverlay = $state(false);
  let viewingIllustration = $state<IllustrationOut | null>(null);
  let shareHighlight = $state<HighlightOut | null>(null);
  let shareModalOpen = $state(false);
  let bookAuthors = $state<string[]>([]);
  let isImageBook = $state(false);
  let aiStatus = $state<AiStatus>({
    companion: false,
    tag: false,
    image: false,
    embedding: false,
  });
  let epubLoaded = $state(false);
  let canScrub = $state(false);
  let prevHtmlOverflow = "";
  let prevBodyOverflow = "";

  onMount(() => {
    prevHtmlOverflow = document.documentElement.style.overflow;
    prevBodyOverflow = document.body.style.overflow;
    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";

    const savedFont = localStorage.getItem("reader-font");
    const savedSize = localStorage.getItem("reader-size");
    const savedLineHeight = localStorage.getItem("reader-lineheight");
    const savedMargin = localStorage.getItem("reader-margin");
    if (savedFont) fontFamily = savedFont;
    if (savedSize) fontSize = parseInt(savedSize);
    if (savedLineHeight) lineHeight = parseFloat(savedLineHeight);
    if (savedMargin) pageMargin = parseInt(savedMargin);
    ready = true;

    // Fetch AI feature status
    aiApi
      .getStatus()
      .then((s) => (aiStatus = s))
      .catch(() => {});

    // Fetch current interaction and start reading timer
    fetchInteractionAndStartTimer();

    // Fetch book metadata for share card + display title
    booksApi
      .get(bookId)
      .then((book) => {
        bookAuthors = book.display_authors ?? book.epub_authors ?? [];
        isImageBook = book.is_image_book === true;
        if (book.display_title) {
          title = book.display_title;
          hasDbTitle = true;
        }
      })
      .catch(() => {});
  });

  onDestroy(() => {
    if (!browser) return;
    destroyed = true;
    document.documentElement.style.overflow = prevHtmlOverflow;
    document.body.style.overflow = prevBodyOverflow;
    if (readingTimer) clearTimeout(readingTimer);
  });

  async function fetchInteractionAndStartTimer() {
    try {
      interaction = await booksApi.getInteraction(bookId);
    } catch {
      /* ignore */
    }

    // Only start timer if status is null or want_to_read
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

  async function revertStatus(
    status: InteractionOut["reading_status"],
    startedAt: string | null,
    finishedAt: string | null,
  ) {
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
    if (!interaction) return;
    if (
      interaction.reading_status === "read" ||
      interaction.reading_status === "did_not_finish"
    )
      return;
    const prevStatus = interaction.reading_status;
    const prevStartedAt = interaction.started_at ?? null;
    const prevFinishedAt = interaction.finished_at ?? null;
    const today = new Date().toISOString().slice(0, 10);
    try {
      await booksApi.updateReadingStatus(bookId, {
        reading_status: "read",
        started_at: interaction.started_at || today,
        finished_at: today,
      });
      interaction.reading_status = "read";
      interaction.finished_at = today;
      toastStore.info(m.reader_auto_marked_read(), {
        duration: 6000,
        action: {
          label: m.common_undo(),
          onclick: () => {
            autoReadSuppressed = true;
            revertStatus(prevStatus, prevStartedAt, prevFinishedAt);
          },
        },
      });
    } catch {
      /* ignore */
    }
  }

  // Progress bridged from an e-reader (KOReader/Readest via kosync). The
  // reader auto-jumps when the book was never read on the web; otherwise
  // the jump is a real decision tied to opening the book, so it gets a
  // dialog (the KOReader/Readest convention), not a dismissable toast.
  async function handleKosyncPosition(detail: {
    percentage: number;
    device: string | null;
    autoJumped: boolean;
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
        local: Math.round(percentage ?? 0),
      }),
      confirmLabel: m.reader_kosync_jump(),
      cancelLabel: m.reader_kosync_dialog_stay(),
    });
    if (jump) reader?.displayPercentage(detail.percentage);
  }

  let reachedEnd = $state(false);

  // Auto-mark as read when the estimated progress hits 99% (covers books
  // that end with a colophon/back matter the reader never turns to) OR the
  // actual last page is reached (covers books whose estimate stalls below
  // 99%). False positives are recoverable via the undo toast.
  $effect(() => {
    if (
      ((percentage != null && percentage >= 99) || reachedEnd) &&
      !autoReadTriggered &&
      !autoReadSuppressed &&
      interaction
    ) {
      autoReadTriggered = true;
      if (readingTimer) {
        clearTimeout(readingTimer);
        readingTimer = null;
      }
      autoMarkAsRead();
    }
  });

  function prefetchSeriesNeighbors() {
    if (seriesNeighbors || seriesFetchPromise) return;
    seriesFetchPromise = booksApi
      .getSeriesNeighbors(bookId)
      .then((data) => {
        seriesNeighbors = data;
      })
      .catch(() => {
        // Silently fail — no overlay if prefetch fails
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
    if (seriesFetchPromise) {
      await seriesFetchPromise;
    }
    if (seriesNeighbors?.next || seriesNeighbors?.progress) {
      showSeriesOverlay = true;
    }
  }

  function handleFontToggle() {
    fontFamily = fontFamily === "serif" ? "sans-serif" : "serif";
    localStorage.setItem("reader-font", fontFamily);
  }

  function handleFontIncrease() {
    if (fontSize < 32) {
      fontSize += 2;
      localStorage.setItem("reader-size", String(fontSize));
    }
  }

  function handleFontDecrease() {
    if (fontSize > 10) {
      fontSize -= 2;
      localStorage.setItem("reader-size", String(fontSize));
    }
  }

  function handleLineHeightChange(value: number) {
    lineHeight = value;
    localStorage.setItem("reader-lineheight", String(value));
  }

  function handleMarginChange(value: number) {
    pageMargin = value;
    localStorage.setItem("reader-margin", String(value));
  }

  function handleThemeToggle() {
    darkMode = !darkMode;
    localStorage.setItem("reader-dark", darkMode ? "1" : "0");
  }

  async function handleIllustrate(detail: { cfiRange: string; text: string }) {
    illustrationModalCfi = detail.cfiRange;
    illustrationModalText = detail.text;
    // Load style prompts if not cached
    if (stylePrompts.length === 0) {
      try {
        stylePrompts = await booksApi.getStylePrompts(bookId);
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
      const ill = await booksApi.createIllustration(bookId, {
        cfi_range: illustrationModalCfi,
        text: illustrationModalText,
        ...detail,
      });
      illustrations = [...illustrations, ill];
      reader?.addIllustrationAnnotation(ill);
      toastStore.success(m.illustration_generating());
      pollIllustration(ill.id);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function pollIllustration(illustrationId: string) {
    for (let i = 0; i < 40; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      if (destroyed) return;

      try {
        const ill = await booksApi.getIllustration(bookId, illustrationId);
        if (ill.status === "completed") {
          illustrations = illustrations.map((x) => (x.id === ill.id ? ill : x));
          reader?.addIllustrationAnnotation(ill);
          toastStore.success(m.illustration_ready());
          return;
        }
        if (ill.status === "failed") {
          illustrations = illustrations.map((x) => (x.id === ill.id ? ill : x));
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
      await booksApi.deleteIllustration(bookId, ill.id);
      illustrations = illustrations.filter((x) => x.id !== ill.id);
      reader?.removeIllustrationAnnotation(ill.cfi_range);
      toastStore.success(m.illustration_deleted());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function handleShareHighlight(hl: HighlightOut) {
    shareHighlight = hl;
    shareModalOpen = true;
  }

  function handleCompanion(detail: { cfiRange: string; text: string }) {
    companionSelectedText = detail.text;
    companionSelectedCfi = detail.cfiRange;
    activeSidebar = "companion";
  }

  function handleSelectIllustration(ill: IllustrationOut) {
    reader?.displayCfi(ill.cfi_range);
    activeSidebar = null;
    viewingIllustration = ill;
  }
</script>

<svelte:head>
  <title>{m.reader_page_title({ title: title || "Reading" })}</title>
</svelte:head>

<div
  class="flex flex-col h-[100dvh] min-h-0 {darkMode
    ? 'bg-ink-900'
    : 'bg-background'}"
>
  <!-- Desktop toolbar -->
  <div class="hidden md:block">
    <Toolbar
      {bookId}
      {title}
      {percentage}
      {darkMode}
      {toc}
      {isRtl}
      {isImageBook}
      highlightCount={highlights.length}
      illustrationCount={illustrations.length}
      offline={!$isOnline}
      onprev={() => reader?.prev()}
      onnext={() => reader?.next()}
      onthemeToggle={handleThemeToggle}
      onchapter={(href) => reader?.displayChapter(href)}
      onhighlights={() => toggleSidebar("highlights")}
      oncompanion={() => {
        toggleSidebar("companion");
        companionSelectedText = null;
        companionSelectedCfi = null;
      }}
      onsearch={() => toggleSidebar("search")}
      ontoc_toggle={() => toggleSidebar("toc")}
      onsettings={() => (showSettings = true)}
      onhelp={() => (showGestureHint = true)}
    />
  </div>

  <!-- Mobile top bar (always visible) -->
  <ReaderTopBar {bookId} {title} {percentage} {darkMode} />

  <div class="flex-1 min-h-0 overflow-hidden relative">
    {#if ready && !loadError}
      {#key readerKey}
        <EpubReader
          bind:this={reader}
          {bookId}
          {initialCfi}
          {fontFamily}
          {fontSize}
          {lineHeight}
          {pageMargin}
          {darkMode}
          {isImageBook}
          offline={!$isOnline}
          ontitle={(t) => {
            if (!hasDbTitle) title = t;
          }}
          onprogress={(p) => {
            percentage = p.percentage;
          }}
          ontoc={(t) => (toc = t)}
          onhrefchange={(href) => (currentHref = href)}
          ondirection={(rtl) => (isRtl = rtl)}
          onhighlightschange={(h) => (highlights = h)}
          onillustrate={handleIllustrate}
          onillustrationschange={(ills) => (illustrations = ills)}
          onillustrationclick={(ill) => (viewingIllustration = ill)}
          onshare={handleShareHighlight}
          oncompanion={handleCompanion}
          ontap={handleReaderTap}
          onready={() => (epubLoaded = true)}
          onerror={() => (loadError = true)}
          onlocationsready={() => (canScrub = true)}
          onkosyncposition={handleKosyncPosition}
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
      {/key}
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
            href="/books/{bookId}"
            class="rounded-lg px-4 py-2 text-sm font-medium transition-colors {darkMode
              ? 'text-ink-300 hover:bg-ink-800'
              : 'text-muted-foreground hover:bg-secondary'}"
          >
            {m.reader_back_to_detail()}
          </a>
        </div>
      </div>
    {:else if !epubLoaded}
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

    <!-- Bottom progress (desktop only, mobile has it in the bottom bar) -->
    {#if epubLoaded && percentage != null}
      <div
        class="hidden md:flex absolute bottom-0 left-0 right-0 z-20 flex-col items-center gap-1 px-8 pb-1.5 pointer-events-none"
      >
        <span
          class="text-xs px-3 py-1 rounded-full {darkMode
            ? 'bg-ink-800/80 text-ink-400'
            : 'bg-black/5 text-muted-foreground'}"
        >
          {percentage}%
        </span>
        {#if canScrub}
          <div class="w-full max-w-xl pointer-events-auto">
            <ProgressScrubber
              {percentage}
              {darkMode}
              {isRtl}
              ariaLabel={m.reader_progress()}
              onseek={(p) => reader?.displayPercentage(p)}
            />
          </div>
        {/if}
      </div>
    {/if}

    {#if activeSidebar === "toc"}
      <TocSidebar
        {toc}
        {darkMode}
        {currentHref}
        onchapter={(href) => {
          reader?.displayChapter(href);
          activeSidebar = null;
        }}
        onclose={() => (activeSidebar = null)}
      />
    {/if}

    {#if activeSidebar === "search" && !isImageBook}
      <SearchSidebar
        {darkMode}
        onselect={(cfi) => {
          reader?.displaySearchResult(cfi);
          activeSidebar = null;
        }}
        onclose={() => (activeSidebar = null)}
        onsearch={(query, onResults, signal) =>
          reader?.searchBook(query, onResults, signal)}
      />
    {/if}

    {#if activeSidebar === "highlights" && !isImageBook}
      <HighlightSidebar
        {highlights}
        {illustrations}
        {bookId}
        {darkMode}
        onselect={(hl) => {
          reader?.displayCfi(hl.cfi_range);
          activeSidebar = null;
        }}
        ondelete={async (hl) => {
          if (
            !(await confirmDialog({
              title: m.highlights_delete_confirm(),
              destructive: true,
            }))
          )
            return;
          const prev = highlights;
          // Optimistically remove, then delete immediately (no delayed undo).
          highlights = highlights.filter((h) => h.id !== hl.id);
          reader?.removeHighlightAnnotation(hl.cfi_range);
          try {
            await booksApi.deleteHighlight(bookId, hl.id);
          } catch (e) {
            toastStore.error((e as Error).message);
            highlights = prev;
            reader?.addHighlightAnnotation(hl.cfi_range, hl.color);
          }
        }}
        onshare={handleShareHighlight}
        onillustrationselect={handleSelectIllustration}
        onillustrationdelete={handleDeleteIllustration}
        onclose={() => (activeSidebar = null)}
      />
    {/if}

    {#if activeSidebar === "companion" && !isImageBook}
      <CompanionSidebar
        {bookId}
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

  <!-- Mobile bottom bar (tap to toggle) -->
  {#if showMobileBottomBar}
    <ReaderBottomBar
      {percentage}
      canSeek={canScrub}
      onseek={(p) => reader?.displayPercentage(p)}
      {darkMode}
      {isRtl}
      {isImageBook}
      highlightCount={highlights.length}
      offline={!$isOnline}
      onprev={() => reader?.prev()}
      onnext={() => reader?.next()}
      ontoc={() => toggleSidebar("toc")}
      onsearch={() => toggleSidebar("search")}
      onhighlights={() => toggleSidebar("highlights")}
      oncompanion={() => {
        toggleSidebar("companion");
        companionSelectedText = null;
        companionSelectedCfi = null;
      }}
      onsettings={() => {
        showSettings = true;
        showMobileBottomBar = false;
      }}
    />
  {/if}

  <!-- Mobile settings sheet -->
  <ReaderSettingsSheet
    bind:open={showSettings}
    {fontFamily}
    {fontSize}
    {lineHeight}
    {pageMargin}
    {darkMode}
    {isImageBook}
    onfontToggle={handleFontToggle}
    onfontIncrease={handleFontIncrease}
    onfontDecrease={handleFontDecrease}
    onthemeToggle={handleThemeToggle}
    onlineHeightChange={handleLineHeightChange}
    onmarginChange={handleMarginChange}
    onhelp={() => (showGestureHint = true)}
  />

  {#if showIllustrationModal}
    <IllustrationPromptModal
      text={illustrationModalText}
      styles={stylePrompts}
      {darkMode}
      {bookId}
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
      {bookId}
      {darkMode}
      onclose={() => (viewingIllustration = null)}
    />
  {/if}

  <ShareHighlightModal
    open={shareModalOpen}
    highlight={shareHighlight}
    bookTitle={title}
    {bookAuthors}
    onclose={() => {
      shareModalOpen = false;
      shareHighlight = null;
    }}
  />

  {#if showSeriesOverlay && seriesNeighbors}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onkeydown={(e) => {
        if (e.key === "Escape") showSeriesOverlay = false;
      }}
      onclick={(e) => {
        if (e.target === e.currentTarget) showSeriesOverlay = false;
      }}
    >
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div
        class="mx-3 sm:mx-4 w-full max-w-[85vw] sm:max-w-sm md:max-w-md overflow-hidden rounded-2xl shadow-2xl {darkMode
          ? 'bg-ink-800 text-ink-100'
          : 'bg-white text-ink-900'}"
        onclick={(e) => e.stopPropagation()}
      >
        {#if seriesNeighbors.next}
          <!-- Cover as hero banner -->
          <div
            class="relative flex items-center justify-center py-10 {darkMode
              ? 'bg-ink-900/60'
              : 'bg-ink-50'}"
          >
            {#if seriesNeighbors.next.cover_path}
              <img
                use:authedSrc={coverUrl(seriesNeighbors.next.id)}
                alt={seriesNeighbors.next.title ?? "Next book"}
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
                series: seriesNeighbors.series_name ?? "",
              })}
            </p>
            <p class="mt-3 text-center text-xl font-semibold">
              {seriesNeighbors.next.title ?? "Untitled"}
            </p>
            {#if seriesNeighbors.next.series_index != null}
              <p
                class="mt-1 text-center text-sm {darkMode
                  ? 'text-ink-400'
                  : 'text-muted-foreground'}"
              >
                {m.reader_series_book_of({
                  index: formatSeriesIndex(seriesNeighbors.next.series_index),
                  total: seriesDisplayTotal() || "?",
                })}
              </p>
            {/if}
            <div class="mt-6 flex gap-3">
              <button
                class="flex-1 rounded-lg px-4 py-3 font-medium transition-colors {darkMode
                  ? 'bg-ink-700 hover:bg-ink-600 text-ink-300'
                  : 'bg-ink-100 hover:bg-ink-200 text-ink-700'}"
                onclick={() => (showSeriesOverlay = false)}
              >
                {m.common_close()}
              </button>
              <button
                class="flex-1 rounded-lg bg-primary px-4 py-3 font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                onclick={() => {
                  window.location.href = `/books/${seriesNeighbors!.next!.id}/read`;
                }}
              >
                {m.reader_start_reading()}
              </button>
            </div>
          </div>
        {:else if seriesNeighbors.progress}
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
                  count: String(seriesNeighbors.progress.total_in_library),
                  series: seriesNeighbors.series_name ?? "",
                })}
              </p>
            </div>
            <button
              class="rounded-lg px-8 py-3 font-medium transition-colors {darkMode
                ? 'bg-ink-700 hover:bg-ink-600 text-ink-300'
                : 'bg-ink-100 hover:bg-ink-200 text-ink-700'}"
              onclick={() => (showSeriesOverlay = false)}
            >
              {m.common_close()}
            </button>
          </div>
        {/if}
      </div>
    </div>
  {/if}
</div>
