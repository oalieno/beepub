<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { browser } from "$app/environment";
  import { page } from "$app/stores";
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import EpubReader from "$lib/components/reader/EpubReader.svelte";
  import Toolbar from "$lib/components/reader/Toolbar.svelte";
  import HighlightSidebar from "$lib/components/reader/HighlightSidebar.svelte";
  import TocSidebar from "$lib/components/reader/TocSidebar.svelte";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import IllustrationPromptModal from "$lib/components/reader/IllustrationPromptModal.svelte";
  import IllustrationSidebar from "$lib/components/reader/IllustrationSidebar.svelte";
  import IllustrationViewer from "$lib/components/reader/IllustrationViewer.svelte";
  import ShareHighlightModal from "$lib/components/ShareHighlightModal.svelte";
  import type {
    HighlightOut,
    IllustrationOut,
    InteractionOut,
    StylePromptOut,
  } from "$lib/types";

  let bookId = $derived($page.params.id as string);

  // Auto reading status
  let interaction: InteractionOut | null = $state(null);
  let readingTimer: ReturnType<typeof setTimeout> | null = null;
  const READING_DEBOUNCE_MS = 2 * 60 * 1000; // 2 minutes
  let autoReadTriggered = false;

  let title = $state("");
  let fontFamily = $state("serif");
  let fontSize = $state(16);
  let darkMode = $state(false);
  let percentage = $state(0);
  let toc = $state<{ label: string; href: string; subitems?: any[] }[]>([]);
  let reader: EpubReader = $state(null as any);
  let ready = $state(false);
  let isRtl = $state(false);
  let highlights = $state<HighlightOut[]>([]);
  let illustrations = $state<IllustrationOut[]>([]);
  let stylePrompts = $state<StylePromptOut[]>([]);
  let showHighlightSidebar = $state(false);
  let showTocSidebar = $state(false);
  let showIllustrationSidebar = $state(false);
  let showIllustrationModal = $state(false);
  let illustrationModalCfi = $state("");
  let illustrationModalText = $state("");
  let viewingIllustration = $state<IllustrationOut | null>(null);
  let shareHighlight = $state<HighlightOut | null>(null);
  let shareModalOpen = $state(false);
  let bookAuthors = $state<string[]>([]);
  let prevHtmlOverflow = "";
  let prevBodyOverflow = "";

  onMount(() => {
    prevHtmlOverflow = document.documentElement.style.overflow;
    prevBodyOverflow = document.body.style.overflow;
    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";

    if (!$authStore.token) {
      goto("/login");
      return;
    }
    const savedFont = localStorage.getItem("reader-font");
    const savedSize = localStorage.getItem("reader-size");
    const savedTheme = localStorage.getItem("reader-dark");
    if (savedFont) fontFamily = savedFont;
    if (savedSize) fontSize = parseInt(savedSize);
    if (savedTheme) darkMode = savedTheme === "1";
    ready = true;

    // Fetch current interaction and start reading timer
    fetchInteractionAndStartTimer();

    // Fetch book authors for share card
    if ($authStore.token) {
      booksApi.get(bookId, $authStore.token).then((book) => {
        bookAuthors = book.display_authors ?? book.epub_authors ?? [];
      }).catch(() => {});
    }
  });

  onDestroy(() => {
    if (!browser) return;
    document.documentElement.style.overflow = prevHtmlOverflow;
    document.body.style.overflow = prevBodyOverflow;
    if (readingTimer) clearTimeout(readingTimer);
  });

  async function fetchInteractionAndStartTimer() {
    if (!$authStore.token) return;
    try {
      interaction = await booksApi.getInteraction(bookId, $authStore.token);
    } catch {
      /* ignore */
    }

    // Only start timer if status is null or want_to_read
    if (
      !interaction?.reading_status ||
      interaction.reading_status === "want_to_read"
    ) {
      readingTimer = setTimeout(async () => {
        if (!$authStore.token) return;
        const today = new Date().toISOString().slice(0, 10);
        try {
          await booksApi.updateReadingStatus(
            bookId,
            {
              reading_status: "currently_reading",
              started_at: today,
            },
            $authStore.token,
          );
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
    if (!$authStore.token || !interaction) return;
    if (
      interaction.reading_status === "read" ||
      interaction.reading_status === "did_not_finish"
    )
      return;
    const today = new Date().toISOString().slice(0, 10);
    try {
      await booksApi.updateReadingStatus(
        bookId,
        {
          reading_status: "read",
          started_at: interaction.started_at || today,
          finished_at: today,
        },
        $authStore.token,
      );
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
    if (stylePrompts.length === 0 && $authStore.token) {
      try {
        stylePrompts = await booksApi.getStylePrompts(bookId, $authStore.token);
      } catch {
        /* ignore */
      }
    }
    showIllustrationModal = true;
  }

  async function handleCreateIllustration(detail: {
    style_prompt?: string;
    custom_prompt?: string;
  }) {
    showIllustrationModal = false;
    if (!$authStore.token) return;
    try {
      const ill = await booksApi.createIllustration(
        bookId,
        {
          cfi_range: illustrationModalCfi,
          text: illustrationModalText,
          ...detail,
        },
        $authStore.token,
      );
      illustrations = [...illustrations, ill];
      toastStore.success("Generating illustration...");
      pollIllustration(ill.id);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function pollIllustration(illustrationId: string) {
    if (!$authStore.token) return;
    for (let i = 0; i < 40; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      if (!$authStore.token) return;
      try {
        const ill = await booksApi.getIllustration(
          bookId,
          illustrationId,
          $authStore.token,
        );
        if (ill.status === "completed") {
          illustrations = illustrations.map((x) => (x.id === ill.id ? ill : x));
          reader?.addIllustrationAnnotation(ill);
          toastStore.success("Illustration ready!");
          return;
        }
        if (ill.status === "failed") {
          illustrations = illustrations.filter((x) => x.id !== ill.id);
          toastStore.error(
            `Generation failed: ${ill.error_message ?? "unknown error"}`,
          );
          return;
        }
      } catch {
        return;
      }
    }
    toastStore.error("Generation timed out");
  }

  async function handleDeleteIllustration(ill: IllustrationOut) {
    if (!$authStore.token) return;
    try {
      await booksApi.deleteIllustration(bookId, ill.id, $authStore.token);
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

  function handleSelectIllustration(ill: IllustrationOut) {
    reader?.displayCfi(ill.cfi_range);
    showIllustrationSidebar = false;
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
  <Toolbar
    {bookId}
    {title}
    {fontFamily}
    {fontSize}
    {percentage}
    {darkMode}
    {toc}
    {isRtl}
    highlightCount={highlights.length}
    illustrationCount={illustrations.length}
    onprev={() => reader?.prev()}
    onnext={() => reader?.next()}
    onfontToggle={handleFontToggle}
    onfontIncrease={handleFontIncrease}
    onfontDecrease={handleFontDecrease}
    onthemeToggle={handleThemeToggle}
    onchapter={(href) => reader?.displayChapter(href)}
    onhighlights={() => {
      showHighlightSidebar = !showHighlightSidebar;
      showTocSidebar = false;
      showIllustrationSidebar = false;
    }}
    onillustrations={() => {
      showIllustrationSidebar = !showIllustrationSidebar;
      showHighlightSidebar = false;
      showTocSidebar = false;
    }}
    ontoc_toggle={() => {
      showTocSidebar = !showTocSidebar;
      showHighlightSidebar = false;
      showIllustrationSidebar = false;
    }}
  />

  <div class="flex-1 min-h-0 overflow-hidden relative">
    {#if ready && $authStore.token}
      <EpubReader
        bind:this={reader}
        {bookId}
        token={$authStore.token}
        {fontFamily}
        {fontSize}
        {darkMode}
        ontitle={(t) => (title = t)}
        onprogress={(p) => {
          percentage = p.percentage;
        }}
        ontoc={(t) => (toc = t)}
        ondirection={(rtl) => (isRtl = rtl)}
        onhighlightschange={(h) => (highlights = h)}
        onillustrate={handleIllustrate}
        onillustrationschange={(ills) => (illustrations = ills)}
        onillustrationclick={(ill) => (viewingIllustration = ill)}
        onshare={handleShareHighlight}
      />
    {/if}

    <!-- Bottom percentage indicator -->
    <div
      class="absolute bottom-0 left-0 right-0 flex items-center justify-center py-2 pointer-events-none"
    >
      <span
        class="text-xs px-3 py-1 rounded-full {darkMode
          ? 'bg-gray-800/80 text-gray-400'
          : 'bg-black/5 text-muted-foreground'}"
      >
        {percentage}%
      </span>
    </div>

    {#if showTocSidebar}
      <TocSidebar
        {toc}
        {darkMode}
        onchapter={(href) => {
          reader?.displayChapter(href);
          showTocSidebar = false;
        }}
        onclose={() => (showTocSidebar = false)}
      />
    {/if}

    {#if showHighlightSidebar}
      <HighlightSidebar
        {highlights}
        {darkMode}
        onselect={(hl) => {
          reader?.displayCfi(hl.cfi_range);
          showHighlightSidebar = false;
        }}
        ondelete={async (hl) => {
          if (!$authStore.token) return;
          try {
            await booksApi.deleteHighlight(bookId, hl.id, $authStore.token);
            highlights = highlights.filter((h) => h.id !== hl.id);
            reader?.removeHighlightAnnotation(hl.cfi_range);
            toastStore.success("Highlight removed");
          } catch (e) {
            toastStore.error((e as Error).message);
          }
        }}
        onshare={handleShareHighlight}
        onclose={() => (showHighlightSidebar = false)}
      />
    {/if}

    {#if showIllustrationSidebar}
      <IllustrationSidebar
        {illustrations}
        {bookId}
        {darkMode}
        onselect={handleSelectIllustration}
        ondelete={handleDeleteIllustration}
        onclose={() => (showIllustrationSidebar = false)}
      />
    {/if}
  </div>

  {#if showIllustrationModal}
    <IllustrationPromptModal
      text={illustrationModalText}
      styles={stylePrompts}
      {darkMode}
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
</div>
