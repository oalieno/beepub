<script lang="ts">
  import { page } from "$app/state";
  import { goto, afterNavigate } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { booksApi } from "$lib/api/books";
  import { worksApi } from "$lib/api/works";
  import { coverUrl } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import { bookshelvesApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import StarRating from "$lib/components/StarRating.svelte";
  import Modal from "$lib/components/Modal.svelte";
  import type {
    BookOut,
    ExternalMetadataOut,
    BookshelfOut,
    InteractionOut,
    HighlightOut,
    ReadingStatus,
    SeriesNeighborsOut,
  } from "$lib/types";
  import HighlightList from "$lib/components/HighlightList.svelte";
  import BottomSheet from "$lib/components/BottomSheet.svelte";
  import { BookDetailSkeleton } from "$lib/components/skeletons";
  import { UserRole } from "$lib/types";
  import {
    Heart,
    BookOpen,
    Trash2,
    Pencil,
    RefreshCw,
    ShelvingUnit,
    EllipsisVertical,
    NotebookPen,
    Bookmark,
    Flag,
    TriangleAlert,
    Download,
    Check,
    Layers,
    Link,
    Unlink,
    Scissors,
    Plus,
    X,
    Search,
  } from "@lucide/svelte";
  import BackButton from "$lib/components/BackButton.svelte";
  import * as Dialog from "$lib/components/ui/dialog";
  import { Button } from "$lib/components/ui/button";
  import { isNative } from "$lib/platform";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import { marked } from "marked";
  import ExternalRatings from "$lib/components/ExternalRatings.svelte";
  import ReadingStatusSelect from "$lib/components/ReadingStatusSelect.svelte";
  import BookMetadataSidebar from "$lib/components/BookMetadataSidebar.svelte";
  import BookMetadataEditModal from "$lib/components/BookMetadataEditModal.svelte";
  import BookNotesModal from "$lib/components/BookNotesModal.svelte";
  import ReportIssueModal from "$lib/components/ReportIssueModal.svelte";
  import * as m from "$lib/paraglide/messages.js";

  function newInteraction(
    overrides: Partial<InteractionOut> = {},
  ): InteractionOut {
    return {
      rating: null,
      is_favorite: false,
      reading_progress: null,
      reading_status: null,
      started_at: null,
      finished_at: null,
      notes: null,
      updated_at: "",
      ...overrides,
    };
  }

  function filterInLibrary(param: string, value: string) {
    const v = value.trim();
    if (!v || !book?.library_id) return;
    goto(
      `/libraries/${book.library_id}?${new URLSearchParams({ [param]: v })}`,
    );
  }

  let bookId = $derived(page.params.id as string);

  let book = $state<BookOut | null>(null);
  let interaction = $state<InteractionOut | null>(null);
  let externalMeta = $state<ExternalMetadataOut[]>([]);
  let bookshelves = $state<BookshelfOut[]>([]);
  let bookHighlights = $state<HighlightOut[]>([]);
  let similarBooks = $state<BookOut[]>([]);
  let editions = $state<
    Array<{
      id: string;
      display_title: string | null;
      display_authors: string[] | null;
      cover_path: string | null;
      metadata_count: number;
    }>
  >([]);
  let seriesNeighbors = $state<SeriesNeighborsOut | null>(null);
  let loading = $state(true);
  let showEditModal = $state(false);
  let showAddToShelf = $state(false);
  let showNotesModal = $state(false);
  let showReportModal = $state(false);
  let showMobileActions = $state(false);
  let showRemoveDownloadDialog = $state(false);

  // Work management state
  let showWorkRemoveConfirm = $state(false);
  let showWorkSplitConfirm = $state(false);
  let showWorkSearchModal = $state(false);
  let workSearchMode = $state<"add" | "create">("add");
  let workSearchQuery = $state("");
  let workSearchResults = $state<BookOut[]>([]);
  let workSearching = $state(false);
  let workSearchTimeout: ReturnType<typeof setTimeout> | null = null;
  let savingStatus = $state(false);

  // Offline download state (native only)
  let offlineAvailable = $state(false);
  let downloading = $state(false);
  let downloadProgress = $state(0);

  // Long-press handler for removing offline copy
  let longPressTimer: ReturnType<typeof setTimeout> | null = null;
  function startLongPress() {
    longPressTimer = setTimeout(() => {
      showRemoveDownloadDialog = true;
    }, 500);
  }
  function cancelLongPress() {
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      longPressTimer = null;
    }
  }

  // Undo delete state
  let pendingHighlightDeleteTimer: ReturnType<typeof setTimeout> | null = null;

  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);

  // Track if user arrived via internal navigation (vs direct link / external)
  // Persisted in sessionStorage to survive reader round-trip (component gets destroyed)
  let hasInternalHistory = $state(false);
  afterNavigate((nav) => {
    if (nav.from) {
      // nav.from is null on initial page load (direct link), non-null for internal navigation
      if (!nav.from.url.pathname.endsWith("/read")) {
        hasInternalHistory = true;
        sessionStorage.setItem(`book-back-${bookId}`, "1");
      } else {
        // Returning from reader — restore flag
        hasInternalHistory =
          sessionStorage.getItem(`book-back-${bookId}`) === "1";
      }
    }
  });

  $effect(() => {
    // Re-load data when bookId changes (e.g. navigating from similar books)
    bookId;
    loadData();
    window.scrollTo(0, 0);
  });

  async function loadData() {
    loading = true;
    try {
      const [b, ext, shelves] = await Promise.all([
        booksApi.get(bookId),
        booksApi.getExternal(bookId).catch(() => [] as ExternalMetadataOut[]),
        bookshelvesApi.list(),
      ]);
      book = b;
      externalMeta = ext;
      bookshelves = shelves;
      const secondaryFetches: Promise<void>[] = [
        booksApi
          .getInteraction(bookId)
          .then((v) => {
            interaction = v;
          })
          .catch(() => {}),
        booksApi
          .getHighlights(bookId)
          .then((v) => {
            bookHighlights = v;
          })
          .catch(() => {}),
        booksApi
          .getSimilar(bookId, 10)
          .then((v) => {
            similarBooks = v;
          })
          .catch(() => {
            similarBooks = [];
          }),
        booksApi
          .getSeriesNeighbors(bookId)
          .then((v) => {
            seriesNeighbors = v;
          })
          .catch(() => {
            seriesNeighbors = null;
          }),
        booksApi
          .getEditions(bookId)
          .then((v) => {
            editions = v;
          })
          .catch(() => {
            editions = [];
          }),
      ];
      if (isNative()) {
        secondaryFetches.push(
          import("$lib/services/offline")
            .then(({ isBookDownloaded }) => isBookDownloaded(bookId))
            .then((v) => {
              offlineAvailable = v;
            })
            .catch(() => {
              offlineAvailable = false;
            }),
        );
      }
      await Promise.all(secondaryFetches);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleDownload() {
    if (!book || downloading) return;
    downloading = true;
    downloadProgress = 0;
    try {
      const { downloadBook } = await import("$lib/services/offline");
      await downloadBook(
        bookId,
        book.display_title ?? book.title ?? "Untitled",
        book.display_authors ?? book.authors ?? [],
        (loaded, total) => {
          downloadProgress = total > 0 ? Math.round((loaded / total) * 100) : 0;
        },
      );
      offlineAvailable = true;
      toastStore.success(m.book_downloaded());
    } catch (e) {
      toastStore.error(
        m.book_download_failed({ error: String((e as Error).message) }),
      );
    } finally {
      downloading = false;
    }
  }

  async function handleDeleteDownload() {
    if (!book) return;
    try {
      const { deleteLocalBook } = await import("$lib/services/offline");
      await deleteLocalBook(bookId);
      offlineAvailable = false;
      toastStore.success(m.book_offline_removed());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleRating(rating: number) {
    if (!book) return;
    try {
      await booksApi.updateRating(bookId, rating);
      interaction = interaction
        ? { ...interaction, rating }
        : newInteraction({ rating });
      toastStore.success(m.book_rating_updated());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function toggleFavorite() {
    if (!book) return;
    const newVal = !interaction?.is_favorite;
    try {
      await booksApi.updateFavorite(bookId, newVal);
      interaction = interaction
        ? { ...interaction, is_favorite: newVal }
        : newInteraction({ is_favorite: newVal });
      toastStore.success(
        newVal ? m.book_favorite_added() : m.book_favorite_removed(),
      );
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleDelete() {
    if (!confirm(m.book_delete_confirm())) return;
    try {
      await booksApi.delete(bookId);
      toastStore.success(m.book_deleted());
      goto("/");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  // --- Work management handlers ---

  async function handleWorkRemove() {
    if (!book?.work_id) return;
    try {
      await worksApi.removeBook(book.work_id, bookId);
      book.work_id = null;
      editions = [];
      showWorkRemoveConfirm = false;
      toastStore.success(m.work_book_removed());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleWorkSplit() {
    if (!book?.work_id) return;
    try {
      await worksApi.deleteWork(book.work_id);
      book.work_id = null;
      editions = [];
      showWorkSplitConfirm = false;
      toastStore.success(m.work_split_success());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleWorkAddBook(targetBookId: string) {
    if (!book) return;
    try {
      if (workSearchMode === "add" && book.work_id) {
        await worksApi.addBook(book.work_id, targetBookId);
        toastStore.success(m.work_book_added());
      } else {
        const work = await worksApi.create([bookId, targetBookId]);
        book.work_id = work.id;
        toastStore.success(m.work_created());
      }
      editions = await booksApi.getEditions(bookId);
      showWorkSearchModal = false;
      workSearchQuery = "";
      workSearchResults = [];
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function handleWorkSearch(query: string) {
    if (workSearchTimeout) clearTimeout(workSearchTimeout);
    if (query.length < 2) {
      workSearchResults = [];
      workSearching = false;
      return;
    }
    workSearching = true;
    workSearchTimeout = setTimeout(async () => {
      try {
        const res = await booksApi.search(query, 10);
        const editionIds = new Set(editions.map((e) => e.id));
        workSearchResults = res.items.filter(
          (b) => b.id !== bookId && !editionIds.has(b.id),
        );
      } catch {
        workSearchResults = [];
      } finally {
        workSearching = false;
      }
    }, 300);
  }

  function openWorkSearch(mode: "add" | "create") {
    workSearchMode = mode;
    workSearchQuery = "";
    workSearchResults = [];
    showWorkSearchModal = true;
  }

  async function handleRemoveEdition(editionId: string) {
    if (!book?.work_id) return;
    try {
      await worksApi.removeBook(book.work_id, editionId);
      editions = editions.filter((e) => e.id !== editionId);
      if (editions.length === 0) {
        book.work_id = null;
      }
      toastStore.success(m.work_book_removed());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleRefreshMeta() {
    try {
      await booksApi.refreshMetadata(bookId);
      toastStore.success(m.book_refresh_queued());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleStatusChange(newStatus: ReadingStatus | null) {
    if (!book) return;
    savingStatus = true;
    try {
      const shouldClearDates = newStatus === null;
      const data: {
        reading_status: ReadingStatus | null;
        started_at?: string | null;
        finished_at?: string | null;
      } = {
        reading_status: newStatus || null,
        started_at: shouldClearDates ? null : (interaction?.started_at ?? null),
        finished_at: shouldClearDates
          ? null
          : (interaction?.finished_at ?? null),
      };
      await booksApi.updateReadingStatus(bookId, data);
      if (interaction) {
        interaction = {
          ...interaction,
          reading_status: newStatus || null,
          started_at: shouldClearDates ? null : interaction.started_at,
          finished_at: shouldClearDates ? null : interaction.finished_at,
        };
      } else
        interaction = newInteraction({ reading_status: newStatus || null });
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      savingStatus = false;
    }
  }

  async function handleDateChange(
    field: "started_at" | "finished_at",
    value: string,
  ) {
    if (!book) return;
    const dateVal = value || null;
    try {
      const data = {
        reading_status: interaction?.reading_status ?? null,
        started_at:
          field === "started_at" ? dateVal : (interaction?.started_at ?? null),
        finished_at:
          field === "finished_at"
            ? dateVal
            : (interaction?.finished_at ?? null),
      };
      await booksApi.updateReadingStatus(bookId, data);
      if (interaction) interaction = { ...interaction, [field]: dateVal };
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function handleNotesSaved(notes: string | null) {
    interaction = interaction
      ? { ...interaction, notes }
      : newInteraction({ notes });
  }

  function handleReported() {
    if (book) book = { ...book, has_unresolved_reports: true };
  }

  async function addToShelf(shelfId: string) {
    try {
      await bookshelvesApi.addBook(shelfId, bookId);
      toastStore.success("Added to bookshelf");
      showAddToShelf = false;
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>{book?.display_title ?? "Book"} - BeePub</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6 pb-24 md:pb-6">
  {#if loading}
    <BookDetailSkeleton />
  {:else if book}
    <!-- Back Button -->
    <div class="mb-6 -ml-1">
      <BackButton
        href={book.library_id ? `/libraries/${book.library_id}` : "/"}
        label="Back"
        onclick={hasInternalHistory ? () => history.back() : undefined}
      />
    </div>

    <!-- Hero Section -->
    <div class="flex flex-col md:flex-row gap-12">
      <!-- Cover -->
      <div
        class="flex-shrink-0 w-64 mx-auto md:mx-0 flex justify-center md:self-start"
      >
        {#if book.cover_path}
          <img
            use:authedSrc={coverUrl(book.id)}
            alt="{book.display_title} cover"
            class="max-w-full h-auto rounded-sm book-shadow"
          />
        {:else}
          <div
            class="w-full aspect-[2/3] rounded-sm bg-secondary flex items-center justify-center book-shadow"
          >
            <BookOpen class="text-muted-foreground/30" size={48} />
          </div>
        {/if}
      </div>

      <!-- Info -->
      <div class="flex-1 min-w-0 flex flex-col pt-6">
        <div>
          <h1 class="text-4xl font-bold leading-tight text-foreground">
            {book.display_title ?? "Untitled"}
          </h1>
          {#if editions.length > 0}
            <a
              href="#editions"
              class="inline-flex items-center gap-1.5 mt-2 px-3 py-1 bg-secondary rounded-full text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              <Layers size={14} />
              {m.book_editions_count({ count: editions.length + 1 })}
            </a>
          {/if}
          {#if (book.display_authors ?? []).length > 0}
            <p class="text-muted-foreground text-lg mt-2">
              {#each book.display_authors ?? [] as author, idx}
                <button
                  type="button"
                  class="hover:text-foreground hover:underline transition-colors"
                  onclick={() => filterInLibrary("author", author)}
                >
                  {author}
                </button>{idx < (book.display_authors ?? []).length - 1
                  ? ", "
                  : ""}
              {/each}
            </p>
          {/if}
        </div>

        <!-- Rating -->
        <div class="mt-5 flex items-center gap-3">
          <StarRating
            value={interaction?.rating ?? null}
            onchange={handleRating}
          />
          <span class="text-sm text-muted-foreground">Your rating</span>
        </div>

        <ExternalRatings {bookId} bind:externalMeta {isAdmin} />

        <ReadingStatusSelect
          {interaction}
          saving={savingStatus}
          onstatuschange={handleStatusChange}
          ondatechange={handleDateChange}
        />

        <!-- Action Buttons (desktop) -->
        <div class="mt-auto pt-6 hidden md:flex items-center gap-2.5">
          <button
            onclick={() =>
              goto(`/books/${book!.id}/read`, { replaceState: true })}
            class="h-10 flex items-center justify-center gap-2 bg-foreground hover:bg-foreground/90 text-background font-semibold px-5 rounded-full transition-colors whitespace-nowrap text-sm"
          >
            <BookOpen size={16} />
            {m.book_start_reading()}
          </button>
          <button
            class="h-10 w-10 flex items-center justify-center bg-card card-soft rounded-full hover:shadow-md transition-all {interaction?.reading_status ===
            'want_to_read'
              ? 'text-primary'
              : 'text-foreground'}"
            onclick={() =>
              handleStatusChange(
                interaction?.reading_status === "want_to_read"
                  ? null
                  : "want_to_read",
              )}
            title={interaction?.reading_status === "want_to_read"
              ? m.book_remove_want_to_read()
              : m.book_want_to_read()}
          >
            <Bookmark
              size={16}
              class={interaction?.reading_status === "want_to_read"
                ? "fill-primary"
                : ""}
            />
          </button>
          {#if isNative()}
            {#if offlineAvailable}
              <button
                class="h-10 w-10 flex items-center justify-center bg-card card-soft rounded-full text-primary hover:shadow-md transition-all"
                onpointerdown={startLongPress}
                onpointerup={cancelLongPress}
                onpointerleave={cancelLongPress}
                title={m.book_downloaded_long_press()}
              >
                <Check size={16} />
              </button>
            {:else if downloading}
              <button
                class="h-10 w-10 flex items-center justify-center rounded-full relative"
                disabled
                title="Downloading {downloadProgress}%"
              >
                <svg class="w-10 h-10 -rotate-90" viewBox="0 0 40 40">
                  <circle
                    cx="20"
                    cy="20"
                    r="17"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2.5"
                    class="text-secondary"
                  />
                  <circle
                    cx="20"
                    cy="20"
                    r="17"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2.5"
                    class="text-primary"
                    stroke-dasharray={2 * Math.PI * 17}
                    stroke-dashoffset={2 *
                      Math.PI *
                      17 *
                      (1 - downloadProgress / 100)}
                    stroke-linecap="round"
                  />
                </svg>
                <span
                  class="absolute inset-0 flex items-center justify-center text-[10px] font-semibold text-primary"
                  >{downloadProgress}%</span
                >
              </button>
            {:else}
              <button
                class="h-10 w-10 flex items-center justify-center bg-card card-soft rounded-full text-foreground hover:shadow-md transition-all"
                onclick={handleDownload}
                title={m.book_download_offline()}
              >
                <Download size={16} />
              </button>
            {/if}
          {:else if $authStore.user?.can_download}
            <a
              href="/api/books/{bookId}/file"
              download
              class="h-10 w-10 flex items-center justify-center bg-card card-soft rounded-full text-foreground hover:shadow-md transition-all"
              title={m.book_download_epub()}
            >
              <Download size={16} />
            </a>
          {/if}
          <DropdownMenu.Root>
            <DropdownMenu.Trigger>
              <button
                class="h-10 w-10 flex items-center justify-center bg-card card-soft rounded-full text-muted-foreground hover:text-foreground hover:shadow-md transition-all"
                title={m.book_more_actions()}
              >
                <EllipsisVertical size={16} />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Content align="start" side="top">
              <DropdownMenu.Item onclick={toggleFavorite}>
                <Heart
                  size={14}
                  class={interaction?.is_favorite
                    ? "fill-red-500 text-red-500"
                    : ""}
                />
                {interaction?.is_favorite
                  ? m.book_remove_favorite()
                  : m.book_add_favorite()}
              </DropdownMenu.Item>
              <DropdownMenu.Item onclick={() => (showAddToShelf = true)}>
                <ShelvingUnit size={14} />
                {m.book_add_to_shelf()}
              </DropdownMenu.Item>
              <DropdownMenu.Item onclick={() => (showNotesModal = true)}>
                <NotebookPen
                  size={14}
                  class={interaction?.notes ? "text-primary" : ""}
                />
                {m.book_notes()}
              </DropdownMenu.Item>
              <DropdownMenu.Item onclick={() => (showReportModal = true)}>
                <Flag
                  size={14}
                  class={book.has_unresolved_reports ? "text-destructive" : ""}
                />
                {m.book_report_issue()}
              </DropdownMenu.Item>
              {#if isAdmin}
                <DropdownMenu.Separator />
                <DropdownMenu.Item onclick={() => (showEditModal = true)}>
                  <Pencil size={14} />
                  {m.book_edit_metadata()}
                </DropdownMenu.Item>
                <DropdownMenu.Item onclick={handleRefreshMeta}>
                  <RefreshCw size={14} />
                  {m.book_refresh_metadata()}
                </DropdownMenu.Item>
                <DropdownMenu.Separator />
                {#if book.work_id}
                  <DropdownMenu.Item onclick={() => openWorkSearch("add")}>
                    <Plus size={14} />
                    {m.work_add_to_work()}
                  </DropdownMenu.Item>
                  <DropdownMenu.Item
                    onclick={() => (showWorkRemoveConfirm = true)}
                  >
                    <Unlink size={14} />
                    {m.work_remove_from_work()}
                  </DropdownMenu.Item>
                  <DropdownMenu.Item
                    onclick={() => (showWorkSplitConfirm = true)}
                  >
                    <Scissors size={14} />
                    {m.work_split_work()}
                  </DropdownMenu.Item>
                {:else}
                  <DropdownMenu.Item onclick={() => openWorkSearch("create")}>
                    <Link size={14} />
                    {m.work_link_book()}
                  </DropdownMenu.Item>
                {/if}
                <DropdownMenu.Item variant="destructive" onclick={handleDelete}>
                  <Trash2 size={14} />
                  {m.book_delete()}
                </DropdownMenu.Item>
              {/if}
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        </div>
      </div>
    </div>

    {#if book.has_unresolved_reports}
      <div
        class="flex items-center gap-3 px-4 py-3 bg-destructive/10 border border-destructive/20 rounded-xl mt-6"
      >
        <TriangleAlert size={18} class="text-destructive shrink-0" />
        <p class="text-sm text-destructive">
          {m.book_corrupted_warning()}
        </p>
      </div>
    {/if}

    <!-- Separator -->
    <div class="border-t border-border my-8"></div>

    <!-- Description + Metadata -->
    <div class="flex flex-col md:flex-row gap-10">
      {#if book.description ?? book.epub_description}
        <div class="flex-1 min-w-0 order-last md:order-none">
          <h2 class="text-xl font-bold mb-3 text-foreground">
            {m.book_description()}
          </h2>
          <div class="text-muted-foreground leading-relaxed prose-description">
            {@html book.description ?? book.epub_description}
          </div>
        </div>
      {/if}

      <BookMetadataSidebar
        {book}
        {seriesNeighbors}
        onfilter={filterInLibrary}
      />
    </div>

    <!-- Notes -->
    {#if interaction?.notes}
      <div class="border-t border-border my-8"></div>
      <div>
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-xl font-bold text-foreground">{m.book_notes()}</h2>
          <button
            class="text-sm text-muted-foreground hover:text-foreground transition-colors"
            onclick={() => {
              showNotesModal = true;
            }}
          >
            {m.common_edit()}
          </button>
        </div>
        <div
          class="bg-card card-soft rounded-2xl p-4 prose-description text-muted-foreground leading-relaxed"
        >
          {@html marked.parse(interaction.notes)}
        </div>
      </div>
    {/if}

    <!-- Highlights -->
    {#if bookHighlights.length > 0}
      <div class="border-t border-border my-8"></div>
      <div>
        <h2 class="text-xl font-bold mb-3 text-foreground">
          {m.book_highlights()}
        </h2>
        <div class="bg-card card-soft rounded-2xl p-4 max-h-80 overflow-y-auto">
          <HighlightList
            highlights={bookHighlights}
            onselect={(hl) => goto(`/books/${bookId}/read`)}
            ondelete={(hl) => {
              bookHighlights = bookHighlights.filter((h) => h.id !== hl.id);

              if (pendingHighlightDeleteTimer)
                clearTimeout(pendingHighlightDeleteTimer);

              toastStore.info(m.book_highlight_removed(), {
                action: {
                  label: m.common_undo(),
                  onclick: () => {
                    if (pendingHighlightDeleteTimer)
                      clearTimeout(pendingHighlightDeleteTimer);
                    pendingHighlightDeleteTimer = null;
                    bookHighlights = [...bookHighlights, hl];
                  },
                },
                duration: 5000,
              });

              pendingHighlightDeleteTimer = setTimeout(async () => {
                try {
                  await booksApi.deleteHighlight(bookId, hl.id);
                } catch (e) {
                  toastStore.error((e as Error).message);
                  bookHighlights = [...bookHighlights, hl];
                }
                pendingHighlightDeleteTimer = null;
              }, 5000);
            }}
          />
        </div>
      </div>
    {/if}

    <!-- Other Editions -->
    {#if editions.length > 0}
      <div class="border-t border-border my-8"></div>
      <div id="editions">
        <h2 class="text-xl font-bold mb-3 text-foreground">
          {m.book_other_editions()}
        </h2>
        <div class="flex gap-4 overflow-x-auto pb-2 -mx-2 px-2 snap-x">
          {#each editions as edition}
            <div class="flex-shrink-0 w-28 relative group/edition">
              <a href="/books/{edition.id}" class="group">
                <div
                  class="aspect-[2/3] rounded-lg overflow-hidden bg-secondary mb-2 book-shadow group-hover:book-shadow-hover transition-shadow"
                >
                  {#if edition.cover_path}
                    <img
                      use:authedSrc={coverUrl(edition.id)}
                      alt={edition.display_title ?? ""}
                      class="w-full h-full object-cover"
                      loading="lazy"
                    />
                  {:else}
                    <div
                      class="w-full h-full flex items-center justify-center text-muted-foreground text-xs p-2 text-center"
                    >
                      {edition.display_title ?? "Untitled"}
                    </div>
                  {/if}
                </div>
                <p
                  class="text-xs text-foreground font-medium line-clamp-2 group-hover:text-primary transition-colors"
                >
                  {edition.display_title ?? "Untitled"}
                </p>
                {#if edition.display_authors?.length}
                  <p class="text-xs text-muted-foreground line-clamp-1">
                    {edition.display_authors.join(", ")}
                  </p>
                {/if}
              </a>
              {#if isAdmin}
                <button
                  class="absolute top-1 right-1 p-1 bg-black/50 backdrop-blur-sm rounded-full text-white opacity-0 group-hover/edition:opacity-100 transition-opacity"
                  title={m.work_remove_from_work()}
                  onclick={() => handleRemoveEdition(edition.id)}
                >
                  <X size={12} />
                </button>
              {/if}
            </div>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Similar Books -->
    {#if similarBooks.length > 0}
      <div class="border-t border-border my-8"></div>
      <div>
        <h2 class="text-xl font-bold mb-3 text-foreground">Similar Books</h2>
        <div class="flex gap-4 overflow-x-auto pb-2 -mx-2 px-2 snap-x">
          {#each similarBooks as simBook}
            <a href="/books/{simBook.id}" class="flex-shrink-0 w-28 group">
              <div
                class="aspect-[2/3] rounded-lg overflow-hidden bg-secondary mb-2 book-shadow group-hover:book-shadow-hover transition-shadow"
              >
                {#if simBook.cover_path}
                  <img
                    use:authedSrc={coverUrl(simBook.id)}
                    alt={simBook.display_title ?? ""}
                    class="w-full h-full object-cover"
                    loading="lazy"
                  />
                {:else}
                  <div
                    class="w-full h-full flex items-center justify-center text-muted-foreground text-xs p-2 text-center"
                  >
                    {simBook.display_title ?? "Untitled"}
                  </div>
                {/if}
              </div>
              <p
                class="text-xs text-foreground font-medium line-clamp-2 group-hover:text-primary transition-colors"
              >
                {simBook.display_title ?? "Untitled"}
              </p>
              {#if simBook.display_authors?.length}
                <p class="text-xs text-muted-foreground line-clamp-1">
                  {simBook.display_authors.join(", ")}
                </p>
              {/if}
            </a>
          {/each}
        </div>
      </div>
    {/if}
  {/if}
</div>

<!-- Mobile Sticky Bottom Bar -->
{#if book && !loading}
  <div
    class="fixed bottom-0 left-0 right-0 z-40 md:hidden bg-background/95 backdrop-blur-sm border-t border-border px-4 pt-3"
    style="padding-bottom: max(0.75rem, env(safe-area-inset-bottom));"
  >
    <div class="flex items-center gap-2.5" style="max-width: 900px;">
      <button
        onclick={() => goto(`/books/${book!.id}/read`, { replaceState: true })}
        class="h-12 flex-1 flex items-center justify-center gap-2 bg-foreground hover:bg-foreground/90 text-background font-semibold rounded-full transition-colors text-base"
      >
        <BookOpen size={16} />
        {m.book_start_reading()}
      </button>
      <button
        class="h-12 w-12 flex items-center justify-center bg-card card-soft rounded-full transition-all {interaction?.reading_status ===
        'want_to_read'
          ? 'text-primary'
          : 'text-foreground'}"
        onclick={() =>
          handleStatusChange(
            interaction?.reading_status === "want_to_read"
              ? null
              : "want_to_read",
          )}
        title={interaction?.reading_status === "want_to_read"
          ? m.book_remove_want_to_read()
          : m.book_want_to_read()}
      >
        <Bookmark
          size={18}
          class={interaction?.reading_status === "want_to_read"
            ? "fill-primary"
            : ""}
        />
      </button>
      {#if isNative()}
        {#if offlineAvailable}
          <button
            class="h-12 w-12 flex items-center justify-center bg-card card-soft rounded-full text-primary transition-all"
            onpointerdown={startLongPress}
            onpointerup={cancelLongPress}
            onpointerleave={cancelLongPress}
            title={m.book_downloaded_long_press()}
          >
            <Check size={18} />
          </button>
        {:else if downloading}
          <button
            class="h-12 w-12 flex items-center justify-center rounded-full relative"
            disabled
          >
            <svg class="w-12 h-12 -rotate-90" viewBox="0 0 48 48">
              <circle
                cx="24"
                cy="24"
                r="21"
                fill="none"
                stroke="currentColor"
                stroke-width="2.5"
                class="text-secondary"
              />
              <circle
                cx="24"
                cy="24"
                r="21"
                fill="none"
                stroke="currentColor"
                stroke-width="2.5"
                class="text-primary"
                stroke-dasharray={2 * Math.PI * 21}
                stroke-dashoffset={2 *
                  Math.PI *
                  21 *
                  (1 - downloadProgress / 100)}
                stroke-linecap="round"
              />
            </svg>
            <span
              class="absolute inset-0 flex items-center justify-center text-xs font-semibold text-primary"
              >{downloadProgress}%</span
            >
          </button>
        {:else}
          <button
            class="h-12 w-12 flex items-center justify-center bg-card card-soft rounded-full text-foreground transition-all"
            onclick={handleDownload}
          >
            <Download size={18} />
          </button>
        {/if}
      {:else if $authStore.user?.can_download}
        <a
          href="/api/books/{bookId}/file"
          download
          class="h-12 w-12 flex items-center justify-center bg-card card-soft rounded-full text-foreground transition-all"
          title={m.book_download_epub()}
        >
          <Download size={18} />
        </a>
      {/if}
      <button
        class="h-12 w-12 flex items-center justify-center bg-card card-soft rounded-full text-muted-foreground transition-all"
        onclick={() => (showMobileActions = true)}
      >
        <EllipsisVertical size={18} />
      </button>
    </div>
  </div>

  <BottomSheet bind:open={showMobileActions}>
    <button
      class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
      onclick={() => {
        toggleFavorite();
        showMobileActions = false;
      }}
    >
      <Heart
        size={20}
        class={interaction?.is_favorite
          ? "fill-red-500 text-red-500 shrink-0"
          : "text-muted-foreground shrink-0"}
      />
      {interaction?.is_favorite
        ? m.book_remove_favorite()
        : m.book_add_favorite()}
    </button>
    <button
      class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
      onclick={() => {
        showAddToShelf = true;
        showMobileActions = false;
      }}
    >
      <ShelvingUnit size={20} class="text-muted-foreground shrink-0" />
      {m.book_add_to_shelf()}
    </button>
    <button
      class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
      onclick={() => {
        showNotesModal = true;
        showMobileActions = false;
      }}
    >
      <NotebookPen
        size={20}
        class={interaction?.notes
          ? "text-primary shrink-0"
          : "text-muted-foreground shrink-0"}
      />
      {m.book_notes()}
    </button>
    <button
      class="flex items-center gap-4 w-full px-2 py-3.5 text-[15px] rounded-lg active:bg-secondary transition-colors {book.has_unresolved_reports
        ? 'text-destructive'
        : 'text-foreground'}"
      onclick={() => {
        showReportModal = true;
        showMobileActions = false;
      }}
    >
      <Flag
        size={20}
        class={book.has_unresolved_reports
          ? "text-destructive shrink-0"
          : "text-muted-foreground shrink-0"}
      />
      {m.book_report_issue()}
    </button>
    {#if isAdmin}
      <div class="border-t border-border my-1"></div>
      <button
        class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
        onclick={() => {
          showEditModal = true;
          showMobileActions = false;
        }}
      >
        <Pencil size={20} class="text-muted-foreground shrink-0" />
        {m.book_edit_metadata()}
      </button>
      <button
        class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
        onclick={() => {
          handleRefreshMeta();
          showMobileActions = false;
        }}
      >
        <RefreshCw size={20} class="text-muted-foreground shrink-0" />
        {m.book_refresh_metadata()}
      </button>
      <div class="border-t border-border my-1"></div>
      {#if book.work_id}
        <button
          class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
          onclick={() => {
            openWorkSearch("add");
            showMobileActions = false;
          }}
        >
          <Plus size={20} class="text-muted-foreground shrink-0" />
          {m.work_add_to_work()}
        </button>
        <button
          class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
          onclick={() => {
            showWorkRemoveConfirm = true;
            showMobileActions = false;
          }}
        >
          <Unlink size={20} class="text-muted-foreground shrink-0" />
          {m.work_remove_from_work()}
        </button>
        <button
          class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
          onclick={() => {
            showWorkSplitConfirm = true;
            showMobileActions = false;
          }}
        >
          <Scissors size={20} class="text-muted-foreground shrink-0" />
          {m.work_split_work()}
        </button>
      {:else}
        <button
          class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
          onclick={() => {
            openWorkSearch("create");
            showMobileActions = false;
          }}
        >
          <Link size={20} class="text-muted-foreground shrink-0" />
          {m.work_link_book()}
        </button>
      {/if}
      <button
        class="flex items-center gap-4 w-full px-2 py-3.5 text-destructive text-[15px] rounded-lg active:bg-secondary transition-colors"
        onclick={() => {
          handleDelete();
          showMobileActions = false;
        }}
      >
        <Trash2 size={20} class="text-destructive shrink-0" />
        {m.book_delete()}
      </button>
    {/if}
  </BottomSheet>
{/if}

{#if book}
  <BookMetadataEditModal
    {book}
    bind:open={showEditModal}
    onupdate={(updated) => (book = updated)}
  />

  <BookNotesModal
    {bookId}
    initialNotes={interaction?.notes ?? ""}
    bind:open={showNotesModal}
    onsaved={handleNotesSaved}
  />

  <Modal
    title={m.book_add_to_bookshelf()}
    open={showAddToShelf}
    onclose={() => (showAddToShelf = false)}
  >
    <div class="space-y-2">
      {#if bookshelves.length === 0}
        <p class="text-muted-foreground text-sm">
          {m.book_no_bookshelves()}<a href="/bookshelves" class="text-primary"
            >{m.book_create_bookshelf()}</a
          >.
        </p>
      {:else}
        {#each bookshelves as shelf}
          <button
            class="w-full text-left px-4 py-3 rounded-xl bg-secondary/50 hover:bg-secondary hover:shadow-sm transition-all"
            onclick={() => addToShelf(shelf.id)}
          >
            <p class="font-medium text-foreground">{shelf.name}</p>
            {#if shelf.description}
              <p class="text-muted-foreground text-xs mt-0.5">
                {shelf.description}
              </p>
            {/if}
          </button>
        {/each}
      {/if}
    </div>
  </Modal>
{/if}

<ReportIssueModal
  {bookId}
  bind:open={showReportModal}
  onreported={handleReported}
/>

<!-- Remove from Work Confirmation -->
<Dialog.Root bind:open={showWorkRemoveConfirm}>
  <Dialog.Content class="sm:max-w-sm bg-white dark:bg-neutral-900">
    <Dialog.Header>
      <Dialog.Title>{m.work_remove_from_work()}</Dialog.Title>
      <Dialog.Description
        >{m.work_remove_from_work_confirm()}</Dialog.Description
      >
    </Dialog.Header>
    <Dialog.Footer>
      <Button
        variant="outline"
        class="rounded-xl"
        onclick={() => (showWorkRemoveConfirm = false)}
      >
        {m.common_cancel()}
      </Button>
      <Button
        class="rounded-xl bg-destructive text-white hover:bg-destructive/90"
        onclick={handleWorkRemove}
      >
        {m.work_remove_from_work()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<!-- Split Work Confirmation -->
<Dialog.Root bind:open={showWorkSplitConfirm}>
  <Dialog.Content class="sm:max-w-sm bg-white dark:bg-neutral-900">
    <Dialog.Header>
      <Dialog.Title>{m.work_split_work()}</Dialog.Title>
      <Dialog.Description
        >{m.work_split_work_confirm({
          count: editions.length + 1,
        })}</Dialog.Description
      >
    </Dialog.Header>
    <Dialog.Footer>
      <Button
        variant="outline"
        class="rounded-xl"
        onclick={() => (showWorkSplitConfirm = false)}
      >
        {m.common_cancel()}
      </Button>
      <Button
        class="rounded-xl bg-destructive text-white hover:bg-destructive/90"
        onclick={handleWorkSplit}
      >
        {m.work_split_work()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<!-- Work Search Modal (Add to Work / Link to Another Book) -->
{#if showWorkSearchModal}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 z-[100] bg-black/50 backdrop-blur-sm"
    onclick={() => {
      showWorkSearchModal = false;
      workSearchQuery = "";
      workSearchResults = [];
    }}
    onkeydown={(e) => e.key === "Escape" && (showWorkSearchModal = false)}
  >
    <div
      role="presentation"
      class="max-w-xl mt-[12vh] mx-4 sm:mx-auto bg-card rounded-2xl shadow-2xl border border-border/50 overflow-hidden"
      onclick={(e) => e.stopPropagation()}
    >
      <!-- Header -->
      <div class="px-4 py-3 border-b border-border/50">
        <p class="text-sm font-medium text-foreground">
          {workSearchMode === "add" ? m.work_add_to_work() : m.work_link_book()}
        </p>
      </div>

      <!-- Search input -->
      <div class="flex items-center gap-3 px-4 py-3 border-b border-border/50">
        <Search size={20} class="text-muted-foreground shrink-0" />
        <!-- svelte-ignore a11y_autofocus -->
        <input
          bind:value={workSearchQuery}
          oninput={() => handleWorkSearch(workSearchQuery)}
          placeholder={m.work_search_placeholder()}
          class="flex-1 bg-transparent text-foreground placeholder:text-muted-foreground outline-none text-base"
          autofocus
        />
        {#if workSearchQuery}
          <button
            class="text-muted-foreground hover:text-foreground"
            onclick={() => {
              workSearchQuery = "";
              workSearchResults = [];
            }}
          >
            <X size={16} />
          </button>
        {/if}
        <kbd
          class="hidden sm:inline text-xs text-muted-foreground bg-secondary px-1.5 py-0.5 rounded"
          >esc</kbd
        >
      </div>

      <!-- Results -->
      <div class="max-h-[60vh] overflow-y-auto">
        {#if workSearching}
          <div class="px-4 py-8 text-center text-muted-foreground text-sm">
            {m.work_searching()}
          </div>
        {:else if workSearchQuery.length >= 2 && workSearchResults.length === 0}
          <div class="px-4 py-8 text-center text-muted-foreground text-sm">
            {m.work_no_results()}
          </div>
        {:else}
          {#each workSearchResults as result (result.id)}
            <button
              class="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-secondary/50 transition-colors"
              onclick={() => handleWorkAddBook(result.id)}
            >
              <div
                class="w-10 h-14 shrink-0 rounded-sm overflow-hidden bg-secondary flex items-center justify-center"
              >
                {#if result.cover_path}
                  <img
                    use:authedSrc={coverUrl(result.id)}
                    alt=""
                    class="w-full h-full object-cover"
                    loading="lazy"
                  />
                {:else}
                  <BookOpen size={16} class="text-muted-foreground/30" />
                {/if}
              </div>
              <div class="flex-1 min-w-0">
                <p class="text-sm font-medium text-foreground truncate">
                  {result.display_title ?? m.common_untitled()}
                </p>
                <p class="text-xs text-muted-foreground truncate">
                  {(result.display_authors ?? []).join(", ") || "\u00A0"}
                </p>
              </div>
            </button>
          {/each}
        {/if}
      </div>
    </div>
  </div>
{/if}

<!-- Remove Offline Copy Confirmation -->
<Dialog.Root bind:open={showRemoveDownloadDialog}>
  <Dialog.Content class="sm:max-w-sm bg-white dark:bg-neutral-900">
    <Dialog.Header>
      <Dialog.Title>{m.book_remove_offline_title()}</Dialog.Title>
      <Dialog.Description>
        {m.book_remove_offline_desc()}
      </Dialog.Description>
    </Dialog.Header>
    <Dialog.Footer>
      <Button
        variant="outline"
        class="rounded-xl"
        onclick={() => (showRemoveDownloadDialog = false)}
      >
        {m.common_cancel()}
      </Button>
      <Button
        class="rounded-xl bg-destructive text-white hover:bg-destructive/90"
        onclick={() => {
          handleDeleteDownload();
          showRemoveDownloadDialog = false;
        }}
      >
        {m.common_remove()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
