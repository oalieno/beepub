<script lang="ts">
  import { page } from "$app/state";
  import { goto, afterNavigate } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { booksApi } from "$lib/api/books";
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
    CircleCheck,
  } from "@lucide/svelte";
  import BackButton from "$lib/components/BackButton.svelte";
  import { isNative } from "$lib/platform";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import { marked } from "marked";
  import ExternalRatings from "$lib/components/ExternalRatings.svelte";
  import ReadingStatusSelect from "$lib/components/ReadingStatusSelect.svelte";
  import BookMetadataSidebar from "$lib/components/BookMetadataSidebar.svelte";
  import BookMetadataEditModal from "$lib/components/BookMetadataEditModal.svelte";
  import BookNotesModal from "$lib/components/BookNotesModal.svelte";
  import ReportIssueModal from "$lib/components/ReportIssueModal.svelte";

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
  let seriesNeighbors = $state<SeriesNeighborsOut | null>(null);
  let loading = $state(true);
  let showEditModal = $state(false);
  let showAddToShelf = $state(false);
  let showNotesModal = $state(false);
  let showReportModal = $state(false);
  let showMobileActions = $state(false);
  let savingStatus = $state(false);

  // Offline download state (native only)
  let offlineAvailable = $state(false);
  let downloading = $state(false);
  let downloadProgress = $state(0);

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
      toastStore.success("Book downloaded for offline reading");
    } catch (e) {
      toastStore.error(`Download failed: ${(e as Error).message}`);
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
      toastStore.success("Offline copy removed");
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
      toastStore.success("Rating updated");
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
        newVal ? "Added to favorites" : "Removed from favorites",
      );
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleDelete() {
    if (!confirm("Delete this book permanently?")) return;
    try {
      await booksApi.delete(bookId);
      toastStore.success("Book deleted");
      goto("/");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleRefreshMeta() {
    try {
      await booksApi.refreshMetadata(bookId);
      toastStore.success("Metadata refresh queued");
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
            Start Reading
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
              ? "Remove from Want to Read"
              : "Want to Read"}
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
                class="h-10 w-10 flex items-center justify-center bg-card card-soft rounded-full text-green-600 hover:shadow-md transition-all"
                onclick={handleDeleteDownload}
                title="Downloaded — tap to remove"
              >
                <CircleCheck size={16} />
              </button>
            {:else}
              <button
                class="h-10 w-10 flex items-center justify-center bg-card card-soft rounded-full text-foreground hover:shadow-md transition-all"
                onclick={handleDownload}
                disabled={downloading}
                title={downloading
                  ? `Downloading ${downloadProgress}%`
                  : "Download for offline"}
              >
                {#if downloading}
                  <span class="text-xs font-semibold">{downloadProgress}%</span>
                {:else}
                  <Download size={16} />
                {/if}
              </button>
            {/if}
          {:else if $authStore.user?.can_download}
            <a
              href="/api/books/{bookId}/file"
              download
              class="h-10 w-10 flex items-center justify-center bg-card card-soft rounded-full text-foreground hover:shadow-md transition-all"
              title="Download EPUB"
            >
              <Download size={16} />
            </a>
          {/if}
          <button
            class="h-10 w-10 flex items-center justify-center bg-card card-soft rounded-full text-foreground hover:shadow-md transition-all"
            onclick={toggleFavorite}
            title={interaction?.is_favorite
              ? "Remove from favorites"
              : "Add to favorites"}
          >
            <Heart
              size={16}
              class={interaction?.is_favorite
                ? "fill-red-500 text-red-500"
                : ""}
            />
          </button>
          <button
            class="h-10 w-10 flex items-center justify-center bg-card card-soft rounded-full text-foreground hover:shadow-md transition-all"
            onclick={() => (showAddToShelf = true)}
            title="Add to bookshelf"
          >
            <ShelvingUnit size={16} />
          </button>
          <button
            class="h-10 w-10 flex items-center justify-center bg-card card-soft rounded-full text-foreground hover:shadow-md transition-all"
            onclick={() => {
              showNotesModal = true;
            }}
            title="Notes"
          >
            <NotebookPen
              size={16}
              class={interaction?.notes ? "text-primary" : ""}
            />
          </button>
          <button
            class="h-10 w-10 flex items-center justify-center bg-card card-soft rounded-full hover:shadow-md transition-all {book.has_unresolved_reports
              ? 'text-destructive'
              : 'text-foreground'}"
            onclick={() => (showReportModal = true)}
            title="Report issue"
          >
            <Flag size={16} />
          </button>
          {#if isAdmin}
            <DropdownMenu.Root>
              <DropdownMenu.Trigger>
                <button
                  class="h-10 w-10 flex items-center justify-center bg-card card-soft rounded-full text-muted-foreground hover:text-foreground hover:shadow-md transition-all"
                  title="Admin actions"
                >
                  <EllipsisVertical size={16} />
                </button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Content align="start" side="top">
                <DropdownMenu.Item onclick={() => (showEditModal = true)}>
                  <Pencil size={14} />
                  Edit metadata
                </DropdownMenu.Item>
                <DropdownMenu.Item onclick={handleRefreshMeta}>
                  <RefreshCw size={14} />
                  Refresh metadata
                </DropdownMenu.Item>
                <DropdownMenu.Separator />
                <DropdownMenu.Item variant="destructive" onclick={handleDelete}>
                  <Trash2 size={14} />
                  Delete book
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Root>
          {/if}
        </div>
      </div>
    </div>

    {#if book.has_unresolved_reports}
      <div
        class="flex items-center gap-3 px-4 py-3 bg-destructive/10 border border-destructive/20 rounded-xl mt-6"
      >
        <TriangleAlert size={18} class="text-destructive shrink-0" />
        <p class="text-sm text-destructive">
          This book's file may be corrupted or unreadable.
        </p>
      </div>
    {/if}

    <!-- Separator -->
    <div class="border-t border-border my-8"></div>

    <!-- Description + Metadata -->
    <div class="flex flex-col md:flex-row gap-10">
      {#if book.description ?? book.epub_description}
        <div class="flex-1 min-w-0 order-last md:order-none">
          <h2 class="text-xl font-bold mb-3 text-foreground">Description</h2>
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
          <h2 class="text-xl font-bold text-foreground">Notes</h2>
          <button
            class="text-sm text-muted-foreground hover:text-foreground transition-colors"
            onclick={() => {
              showNotesModal = true;
            }}
          >
            Edit
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
        <h2 class="text-xl font-bold mb-3 text-foreground">Highlights</h2>
        <div class="bg-card card-soft rounded-2xl p-4 max-h-80 overflow-y-auto">
          <HighlightList
            highlights={bookHighlights}
            onselect={(hl) => goto(`/books/${bookId}/read`)}
            ondelete={(hl) => {
              bookHighlights = bookHighlights.filter((h) => h.id !== hl.id);

              if (pendingHighlightDeleteTimer)
                clearTimeout(pendingHighlightDeleteTimer);

              toastStore.info("Highlight removed", {
                action: {
                  label: "Undo",
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
        Start Reading
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
          ? "Remove from Want to Read"
          : "Want to Read"}
      >
        <Bookmark
          size={18}
          class={interaction?.reading_status === "want_to_read"
            ? "fill-primary"
            : ""}
        />
      </button>
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
      {interaction?.is_favorite ? "Remove from favorites" : "Add to favorites"}
    </button>
    <button
      class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
      onclick={() => {
        showAddToShelf = true;
        showMobileActions = false;
      }}
    >
      <ShelvingUnit size={20} class="text-muted-foreground shrink-0" />
      Add to shelf
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
      Notes
    </button>
    {#if isNative()}
      {#if offlineAvailable}
        <button
          class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
          onclick={() => {
            handleDeleteDownload();
            showMobileActions = false;
          }}
        >
          <CircleCheck size={20} class="text-green-600 shrink-0" />
          Downloaded (tap to remove)
        </button>
      {:else}
        <button
          class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
          onclick={() => {
            handleDownload();
            showMobileActions = false;
          }}
          disabled={downloading}
        >
          <Download size={20} class="text-muted-foreground shrink-0" />
          {downloading
            ? `Downloading ${downloadProgress}%`
            : "Download for offline"}
        </button>
      {/if}
    {:else if $authStore.user?.can_download}
      <a
        href="/api/books/{bookId}/file"
        download
        class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
        onclick={() => (showMobileActions = false)}
      >
        <Download size={20} class="text-muted-foreground shrink-0" />
        Download EPUB
      </a>
    {/if}
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
      Report issue
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
        Edit metadata
      </button>
      <button
        class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
        onclick={() => {
          handleRefreshMeta();
          showMobileActions = false;
        }}
      >
        <RefreshCw size={20} class="text-muted-foreground shrink-0" />
        Refresh metadata
      </button>
      <button
        class="flex items-center gap-4 w-full px-2 py-3.5 text-destructive text-[15px] rounded-lg active:bg-secondary transition-colors"
        onclick={() => {
          handleDelete();
          showMobileActions = false;
        }}
      >
        <Trash2 size={20} class="text-destructive shrink-0" />
        Delete book
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
    title="Add to Bookshelf"
    open={showAddToShelf}
    onclose={() => (showAddToShelf = false)}
  >
    <div class="space-y-2">
      {#if bookshelves.length === 0}
        <p class="text-muted-foreground text-sm">
          No bookshelves yet. <a href="/bookshelves" class="text-primary"
            >Create one</a
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
