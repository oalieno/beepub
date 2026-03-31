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
  import { isOnline } from "$lib/services/network";
  import IllustrationPromptModal from "$lib/components/reader/IllustrationPromptModal.svelte";
  import CompanionSidebar from "$lib/components/reader/CompanionSidebar.svelte";
  import SearchSidebar from "$lib/components/reader/SearchSidebar.svelte";
  import IllustrationViewer from "$lib/components/reader/IllustrationViewer.svelte";
  import ShareHighlightModal from "$lib/components/ShareHighlightModal.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { UserRole } from "$lib/types";
  import type {
    AiStatus,
    HighlightOut,
    IllustrationOut,
    InteractionOut,
    SeriesNeighborsOut,
    StylePromptOut,
  } from "$lib/types";

  let bookId = $derived(page.params.id as string);

  // Auto reading status
  let interaction: InteractionOut | null = $state(null);
  let readingTimer: ReturnType<typeof setTimeout> | null = null;
  let destroyed = false;
  const READING_DEBOUNCE_MS = 2 * 60 * 1000; // 2 minutes
  let autoReadTriggered = false;

  let title = $state("");
  let fontFamily = $state("serif");
  let fontSize = $state(16);
  let darkMode = $state(false);
  let percentage = $state(0);
  let toc = $state<{ label: string; href: string; subitems?: any[] }[]>([]);
  let currentHref = $state("");
  let reader: EpubReader = $state(null as any);
  let ready = $state(false);
  let isRtl = $state(false);
  let highlights = $state<HighlightOut[]>([]);
  let illustrations = $state<IllustrationOut[]>([]);
  let stylePrompts = $state<StylePromptOut[]>([]);
  type Sidebar = "highlights" | "toc" | "search" | "companion";
  let activeSidebar = $state<Sidebar | null>(null);

  let showMobileBottomBar = $state(false);
  let showSettings = $state(false);

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
  let pendingHighlightDeleteTimer: ReturnType<typeof setTimeout> | null = null;
  let aiStatus = $state<AiStatus>({
    companion: false,
    tag: false,
    image: false,
    embedding: false,
  });
  let epubLoaded = $state(false);
  let prevHtmlOverflow = "";
  let prevBodyOverflow = "";

  onMount(() => {
    prevHtmlOverflow = document.documentElement.style.overflow;
    prevBodyOverflow = document.body.style.overflow;
    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";

    const savedFont = localStorage.getItem("reader-font");
    const savedSize = localStorage.getItem("reader-size");
    const savedTheme = localStorage.getItem("reader-dark");
    if (savedFont) fontFamily = savedFont;
    if (savedSize) fontSize = parseInt(savedSize);
    if (savedTheme) darkMode = savedTheme === "1";
    ready = true;

    // Fetch AI feature status
    aiApi
      .getStatus()
      .then((s) => (aiStatus = s))
      .catch(() => {});

    // Fetch current interaction and start reading timer
    fetchInteractionAndStartTimer();

    // Fetch book authors for share card
    booksApi
      .get(bookId)
      .then((book) => {
        bookAuthors = book.display_authors ?? book.epub_authors ?? [];
        isImageBook = book.is_image_book === true;
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
        } catch {
          /* ignore */
        }
      }, READING_DEBOUNCE_MS);
    }
  }

  async function autoMarkAsRead() {
    if (!interaction) return;
    if (
      interaction.reading_status === "read" ||
      interaction.reading_status === "did_not_finish"
    )
      return;
    const today = new Date().toISOString().slice(0, 10);
    try {
      await booksApi.updateReadingStatus(bookId, {
        reading_status: "read",
        started_at: interaction.started_at || today,
        finished_at: today,
      });
      interaction.reading_status = "read";
      interaction.finished_at = today;
    } catch {
      /* ignore */
    }
  }

  $effect(() => {
    if (percentage >= 99 && !autoReadTriggered && interaction) {
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
      toastStore.success("Generating illustration...");
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
          toastStore.success("Illustration ready!");
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
    toastStore.error("Generation timed out");
  }

  async function handleDeleteIllustration(ill: IllustrationOut) {
    try {
      await booksApi.deleteIllustration(bookId, ill.id);
      illustrations = illustrations.filter((x) => x.id !== ill.id);
      reader?.removeIllustrationAnnotation(ill.cfi_range);
      toastStore.success("Illustration deleted");
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
  <title>{title || "Reading"} - BeePub</title>
</svelte:head>

<div
  class="flex flex-col h-[100dvh] min-h-0 {darkMode
    ? 'bg-gray-900'
    : 'bg-background'}"
>
  <!-- Desktop toolbar -->
  <div class="hidden md:block">
    <Toolbar
      {bookId}
      {title}
      {fontFamily}
      {fontSize}
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
      onfontToggle={handleFontToggle}
      onfontIncrease={handleFontIncrease}
      onfontDecrease={handleFontDecrease}
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
    />
  </div>

  <!-- Mobile top bar (always visible) -->
  <ReaderTopBar {bookId} {title} {percentage} {darkMode} />

  <div class="flex-1 min-h-0 overflow-hidden relative">
    {#if ready}
      <EpubReader
        bind:this={reader}
        {bookId}
        {fontFamily}
        {fontSize}
        {darkMode}
        {isImageBook}
        offline={!$isOnline}
        ontitle={(t) => (title = t)}
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
        onatend={prefetchSeriesNeighbors}
        onbookend={handleBookEnd}
      />
    {/if}

    {#if !epubLoaded}
      <div
        class="absolute inset-0 z-10 flex items-center justify-center {darkMode
          ? 'bg-gray-900'
          : 'bg-white'}"
      >
        <Spinner size="lg" class={darkMode ? "border-gray-400" : ""} />
      </div>
    {/if}

    <!-- Bottom percentage indicator (desktop only, mobile has it in top bar) -->
    {#if epubLoaded}
      <div
        class="hidden md:flex absolute bottom-0 left-0 right-0 items-center justify-center py-2 pointer-events-none"
      >
        <span
          class="text-xs px-3 py-1 rounded-full {darkMode
            ? 'bg-gray-800/80 text-gray-400'
            : 'bg-black/5 text-muted-foreground'}"
        >
          {percentage}%
        </span>
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
          reader?.displayCfi(cfi);
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
        ondelete={(hl) => {
          highlights = highlights.filter((h) => h.id !== hl.id);
          reader?.removeHighlightAnnotation(hl.cfi_range);

          if (pendingHighlightDeleteTimer)
            clearTimeout(pendingHighlightDeleteTimer);

          toastStore.info("Highlight removed", {
            action: {
              label: "Undo",
              onclick: () => {
                if (pendingHighlightDeleteTimer)
                  clearTimeout(pendingHighlightDeleteTimer);
                pendingHighlightDeleteTimer = null;
                highlights = [...highlights, hl];
                reader?.addHighlightAnnotation(hl.cfi_range, hl.color);
              },
            },
            duration: 5000,
          });

          pendingHighlightDeleteTimer = setTimeout(async () => {
            try {
              await booksApi.deleteHighlight(bookId, hl.id);
            } catch (e) {
              toastStore.error((e as Error).message);
              highlights = [...highlights, hl];
              reader?.addHighlightAnnotation(hl.cfi_range, hl.color);
            }
            pendingHighlightDeleteTimer = null;
          }, 5000);
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
    {darkMode}
    {isImageBook}
    onfontToggle={handleFontToggle}
    onfontIncrease={handleFontIncrease}
    onfontDecrease={handleFontDecrease}
    onthemeToggle={handleThemeToggle}
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
          ? 'bg-gray-800 text-gray-100'
          : 'bg-white text-gray-900'}"
        onclick={(e) => e.stopPropagation()}
      >
        {#if seriesNeighbors.next}
          <!-- Cover as hero banner -->
          <div
            class="relative flex items-center justify-center py-10 {darkMode
              ? 'bg-gray-900/60'
              : 'bg-gray-50'}"
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
                  ? 'bg-gray-700 text-gray-400'
                  : 'bg-gray-200 text-muted-foreground'}"
              >
                No cover
              </div>
            {/if}
          </div>

          <!-- Info + actions -->
          <div class="px-6 py-6">
            <p
              class="text-center text-xs font-medium uppercase tracking-widest {darkMode
                ? 'text-gray-500'
                : 'text-muted-foreground'}"
            >
              Up next in {seriesNeighbors.series_name}
            </p>
            <p class="mt-3 text-center text-xl font-semibold">
              {seriesNeighbors.next.title ?? "Untitled"}
            </p>
            {#if seriesNeighbors.next.series_index != null}
              <p
                class="mt-1 text-center text-sm {darkMode
                  ? 'text-gray-400'
                  : 'text-muted-foreground'}"
              >
                Book {seriesNeighbors.next.series_index} of {seriesNeighbors
                  .progress?.total_in_library ?? "?"}
              </p>
            {/if}
            <div class="mt-6 flex gap-3">
              <button
                class="flex-1 rounded-lg px-4 py-3 font-medium transition-colors {darkMode
                  ? 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                  : 'bg-gray-100 hover:bg-gray-200 text-gray-700'}"
                onclick={() => (showSeriesOverlay = false)}
              >
                Close
              </button>
              <button
                class="flex-1 rounded-lg bg-primary px-4 py-3 font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                onclick={() => {
                  window.location.href = `/books/${seriesNeighbors!.next!.id}/read`;
                }}
              >
                Start reading
              </button>
            </div>
          </div>
        {:else if seriesNeighbors.progress && seriesNeighbors.progress.read_count >= seriesNeighbors.progress.total_in_library}
          <div class="flex flex-col items-center gap-6 px-10 py-14">
            <span class="text-6xl">🎉</span>
            <div class="text-center">
              <p class="text-2xl font-semibold">Series Complete!</p>
              <p
                class="mt-2 {darkMode
                  ? 'text-gray-400'
                  : 'text-muted-foreground'}"
              >
                You've finished all {seriesNeighbors.progress.total_in_library} books
                in {seriesNeighbors.series_name}
              </p>
            </div>
            <button
              class="rounded-lg px-8 py-3 font-medium transition-colors {darkMode
                ? 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                : 'bg-gray-100 hover:bg-gray-200 text-gray-700'}"
              onclick={() => (showSeriesOverlay = false)}
            >
              Close
            </button>
          </div>
        {/if}
      </div>
    </div>
  {/if}
</div>
