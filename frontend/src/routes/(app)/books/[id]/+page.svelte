<script lang="ts">
  import { tick, untrack } from "svelte";
  import { page } from "$app/state";
  import { goto, afterNavigate } from "$app/navigation";
  import { keyboardVisible } from "#lib/stores/keyboard.ts";
  import { authStore } from "#lib/stores/auth.ts";
  import { booksApi } from "#lib/api/books.ts";
  import { beepubSync } from "#lib/reading/beepub.ts";
  import { worksApi } from "#lib/api/works.ts";
  import { coverUrl } from "#lib/api/client.ts";
  import GeneratedCover from "#lib/components/GeneratedCover.svelte";
  import { authedSrc } from "#lib/actions/authedSrc.ts";
  import { toastStore } from "#lib/stores/toast.ts";
  import type { DownloadRequest } from "#lib/stores/downloads.ts";
  import { refreshLinkedBookIds } from "#lib/stores/linkedBooks.ts";
  import DownloadButton from "#lib/components/DownloadButton.svelte";
  import { confirmDialog } from "#lib/stores/confirm.ts";
  import StarRating from "#lib/components/StarRating.svelte";
  import type {
    BookOut,
    ExternalMetadataOut,
    InteractionOut,
    HighlightOut,
    ReadingStatus,
    SeriesNeighborsOut,
  } from "#lib/types.ts";
  import HighlightList from "#lib/components/HighlightList.svelte";
  import BottomSheet from "#lib/components/BottomSheet.svelte";
  import { BookDetailSkeleton } from "#lib/components/skeletons/index.ts";
  import { UserRole } from "#lib/types.ts";
  import {
    BookOpen,
    EllipsisVertical,
    Bookmark,
    TriangleAlert,
    Download,
    Layers,
    X,
    Star,
    BookCopy,
    FileText,
  } from "@lucide/svelte";
  import BackButton from "#lib/components/BackButton.svelte";
  import { isNative } from "#lib/platform.ts";
  import { readingSyncStamp } from "#lib/services/readingSync.ts";
  import * as DropdownMenu from "#lib/components/ui/dropdown-menu/index.ts";
  import { marked } from "marked";
  import { sanitizeDescription } from "#lib/sanitize.ts";
  import ExternalRatings from "#lib/components/ExternalRatings.svelte";
  import ReadingStatusSelect from "#lib/components/ReadingStatusSelect.svelte";
  import BookMetadataSidebar from "#lib/components/BookMetadataSidebar.svelte";
  import BookNotesEditor from "#lib/components/BookNotesEditor.svelte";
  import BackToTop from "#lib/components/BackToTop.svelte";
  import BookActions, {
    downloadRequestFor,
    type Edition,
  } from "#lib/components/book-actions/BookActions.svelte";
  import BookActionMenuItems from "#lib/components/book-actions/BookActionMenuItems.svelte";
  import * as m from "#lib/paraglide/messages.js";

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
  // Physical books have no file: no reader, no download — tracking is
  // status/rating/notes only (a percentage is meaningless for paper).
  let isPhysical = $derived(book?.format === "physical");
  // Uploaded as TXT/MOBI/AZW3 and converted at ingest: the file behind the
  // book is the EPUB, and the source is offered separately (its ⋯ menu).
  let isConverted = $derived(
    ["txt", "mobi", "azw3", "cbz"].includes(book?.format ?? ""),
  );
  let sourceFormat = $derived((book?.format ?? "").toUpperCase());
  let externalMeta = $state<ExternalMetadataOut[]>([]);
  let bookHighlights = $state<HighlightOut[]>([]);
  let similarBooks = $state<BookOut[]>([]);
  let editions = $state<Edition[]>([]);
  let primaryBookId = $state<string | null>(null);
  let seriesNeighbors = $state<SeriesNeighborsOut | null>(null);
  let loading = $state(true);
  let notesStartEditing = $state(false);
  let notesSectionEl = $state<HTMLDivElement | null>(null);

  function scrollToNotes(startEditing = false) {
    notesSectionEl?.scrollIntoView({ behavior: "smooth", block: "start" });
    if (startEditing) notesStartEditing = true;
  }
  let showMobileActions = $state(false);
  // The ⋯ menu's actions and their dialogs (shared with the library table).
  let bookActions = $state<BookActions>();
  let savingStatus = $state(false);

  // Download-to-library (native only): the state lives in the app-wide
  // queue, keyed by book — this page is reused across volumes.
  let downloadRequest = $derived<DownloadRequest | null>(
    book ? downloadRequestFor(book) : null,
  );

  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);

  // Track if user arrived via internal navigation (vs direct link / external)
  // Persisted in sessionStorage to survive reader round-trip (component gets destroyed)
  let hasInternalHistory = $state(false);
  afterNavigate((nav) => {
    if (nav.shallow && nav.type === "goto") return;

    if (nav.from) {
      // nav.from is null on initial page load (direct link), non-null for internal navigation
      if (!/\/read$/.test(nav.from.url.pathname)) {
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

  // A background sync just merged offline reading into the server row —
  // the reading state this page shows is stale until refetched. Quietly:
  // the page is on screen and stays as it is (only the first load and
  // another book put the skeleton up), and a refresh that fails leaves
  // what was there.
  let prevSyncStamp = $readingSyncStamp;
  $effect(() => {
    const stamp = $readingSyncStamp;
    if (stamp !== prevSyncStamp) {
      prevSyncStamp = stamp;
      void untrack(refreshReadingState);
    }
  });

  async function refreshReadingState() {
    const id = bookId;
    // (Still loading: that load reads the merged rows itself.)
    if (loading || !book) return;
    const [fresh, marks] = await Promise.all([
      booksApi.getInteraction(id).catch(() => null),
      beepubSync.listHighlights(id).catch(() => null),
    ]);
    if (id !== bookId || loading) return;
    if (fresh) interaction = fresh;
    if (marks) bookHighlights = marks;
  }

  let notFound = $state(false);

  async function loadData() {
    // The page is reused from one book to the next (similar books, series
    // neighbours): an answer that comes back after the reader has moved on
    // is for a book no longer shown, and is dropped.
    const id = bookId;
    const current = () => id === bookId;

    const keep =
      <T,>(set: (v: T) => void) =>
      (v: T) => {
        if (current()) set(v);
      };
    loading = true;
    notFound = false;
    try {
      const [b, ext] = await Promise.all([
        booksApi.get(id),
        booksApi.getExternal(id).catch(() => [] as ExternalMetadataOut[]),
      ]);
      if (!current()) return;
      book = b;
      externalMeta = ext;
      const secondaryFetches: Promise<void>[] = [
        booksApi
          .getInteraction(id)
          .then(keep((v) => (interaction = v)))
          .catch(() => {}),
        beepubSync
          .listHighlights(id)
          .then(keep((v) => (bookHighlights = v)))
          .catch(() => {}),
        booksApi
          .getSimilar(id, 10)
          .catch(() => [] as BookOut[])
          .then(keep((v) => (similarBooks = v))),
        booksApi
          .getSeriesNeighbors(id)
          .catch(() => null)
          .then(keep((v) => (seriesNeighbors = v))),
        booksApi
          .getEditions(id)
          .catch(() => ({ editions: [] as Edition[], primary_book_id: null }))
          .then(
            keep((v) => {
              editions = v.editions;
              primaryBookId = v.primary_book_id;
            }),
          ),
      ];
      if (isNative()) secondaryFetches.push(refreshLinkedBookIds());
      await Promise.all(secondaryFetches);
    } catch (e) {
      if (!current()) return;
      // Gone (deleted) or out of reach is a page state, not a toast;
      // anything else — a network hiccup, a 5xx — keeps the toast.
      const status = (e as { status?: number }).status;
      if (status === 404 || status === 403) notFound = true;
      else toastStore.error((e as Error).message);
    } finally {
      // (The newer load owns the skeleton now.)
      if (current()) loading = false;
    }
    if (!current()) return;
    // Come from the library table's ⋯ menu: the notes, open to write in.
    if (book && page.url.hash === "#notes") {
      await tick();
      scrollToNotes(true);
    }
  }

  async function handleRating(rating: number | null) {
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

  // --- The editions row (the ⋯ menu's work items are BookActions') ---

  async function handleRemoveEdition(editionId: string) {
    if (!book?.work_id) return;
    try {
      await worksApi.removeBook(book.work_id, editionId);
      editions = editions.filter((e) => e.id !== editionId);
      if (editions.length === 0) {
        book.work_id = null;
        primaryBookId = null;
      } else if (primaryBookId === editionId) {
        // Backend auto-promotes newest remaining as primary; refetch.
        const data = await booksApi.getEditions(bookId);
        primaryBookId = data.primary_book_id;
      }
      toastStore.success(m.work_book_removed());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleSetPrimary(targetBookId: string) {
    if (!book?.work_id) return;
    try {
      await worksApi.update(book.work_id, { primary_book_id: targetBookId });
      primaryBookId = targetBookId;
      toastStore.success(m.work_primary_set());
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

  function favorited(value: boolean) {
    interaction = interaction
      ? { ...interaction, is_favorite: value }
      : newInteraction({ is_favorite: value });
  }

  function reported() {
    if (book) book = { ...book, has_unresolved_reports: true };
  }

  function deleted() {
    // The book page no longer exists — replace it in history so back
    // doesn't land on a 404.
    goto(book?.library_id ? `/libraries/${book.library_id}` : "/", {
      replace: true,
    });
  }
</script>

<svelte:head>
  <title>{book?.display_title ?? "Book"} - BeePub</title>
</svelte:head>

<!-- Bottom padding clears the fixed action bar, whose own height grows
     by env(safe-area-inset-bottom) on iOS — mirror it here or the last
     section sits flush against the bar. -->
<div
  class="max-w-5xl mx-auto px-6 sm:px-8 py-6 pb-[calc(6rem+env(safe-area-inset-bottom,0px))] md:pb-6"
>
  <!-- Back Button: live before the book arrives, so a slow load (or a
       failed one) never traps whoever tapped in by mistake. -->
  <div class="mb-6 -ml-1">
    <BackButton
      href={book?.library_id ? `/libraries/${book.library_id}` : "/"}
      onclick={hasInternalHistory ? () => history.back() : undefined}
    />
  </div>

  {#if loading}
    <BookDetailSkeleton />
  {:else if notFound}
    <div class="flex flex-col items-center text-center py-8">
      <img
        src="/error-404.webp"
        alt=""
        style="width: min(26rem, 80vw); max-height: 36dvh; height: auto; object-fit: contain;"
        class="mb-4"
      />
      <h1 class="text-xl font-semibold text-foreground mb-2">
        {m.book_not_found_title()}
      </h1>
      <p class="text-muted-foreground mb-6 max-w-sm">
        {m.book_not_found_desc()}
      </p>
      <a
        href="/libraries"
        class="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium hover:opacity-90 transition-opacity"
      >
        {m.book_not_found_back()}
      </a>
    </div>
  {:else if book}
    <!-- Hero Section -->
    <div class="flex flex-col md:flex-row gap-12">
      <!-- Cover -->
      <div
        class="flex-shrink-0 w-64 mx-auto md:mx-0 flex justify-center md:self-start"
      >
        {#if book.cover_path}
          <img
            use:authedSrc={coverUrl(book.id, book.updated_at)}
            alt="{book.display_title} cover"
            class="max-w-full h-auto rounded-sm book-shadow"
          />
        {:else}
          <GeneratedCover
            title={book.display_title ?? "Untitled"}
            authors={book.display_authors ?? []}
            class="w-full aspect-[2/3]"
          />
        {/if}
      </div>

      <!-- Info -->
      <div class="flex-1 min-w-0 flex flex-col pt-6">
        <div>
          <h1
            class="text-4xl font-bold leading-tight text-foreground [overflow-wrap:anywhere]"
          >
            {book.display_title ?? "Untitled"}
          </h1>
          {#if isPhysical}
            <!-- Doubles as the entry to the library filtered to physical
                 books (same navigation pattern as the author chips). -->
            <button
              type="button"
              class="inline-flex items-center gap-1.5 mt-2 mr-2 px-3 py-1 bg-secondary rounded-full text-sm text-muted-foreground hover:text-foreground transition-colors"
              onclick={() => filterInLibrary("format", "physical")}
            >
              <BookCopy size={14} />
              {m.physical_badge()}
            </button>
          {/if}
          {#if isConverted}
            <button
              type="button"
              class="inline-flex items-center gap-1.5 mt-2 mr-2 px-3 py-1 bg-secondary rounded-full text-sm text-muted-foreground hover:text-foreground transition-colors"
              onclick={() => filterInLibrary("format", book?.format ?? "")}
            >
              <FileText size={14} />
              {m.converted_badge({ format: sourceFormat })}
            </button>
          {/if}
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
          <span class="text-sm text-muted-foreground"
            >{m.series_rating_your()}</span
          >
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
          {#if !isPhysical}
            <button
              onclick={() => goto(`/books/${book!.id}/read`, { replace: true })}
              class="h-10 flex items-center justify-center gap-2 bg-foreground hover:bg-foreground/90 text-background font-semibold px-5 rounded-full transition-colors whitespace-nowrap text-sm"
            >
              <BookOpen size={16} />
              {interaction?.reading_status === "currently_reading"
                ? m.book_continue_reading()
                : m.book_start_reading()}
            </button>
          {/if}
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
          {#if isPhysical}
            <!-- nothing to download -->
          {:else if isNative()}
            {#if downloadRequest}
              <DownloadButton request={downloadRequest} />
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
              <BookActionMenuItems groups={bookActions?.groups() ?? []} />
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
            {@html sanitizeDescription(
              book.description ?? book.epub_description,
            )}
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
    <div class="border-t border-border my-8"></div>
    <div bind:this={notesSectionEl}>
      {#key bookId}
        <BookNotesEditor
          {bookId}
          initialNotes={interaction?.notes ?? ""}
          bind:startEditing={notesStartEditing}
          onchange={handleNotesSaved}
        />
      {/key}
    </div>

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
            onselect={(hl) =>
              goto(
                `/books/${bookId}/read?cfi=${encodeURIComponent(hl.cfi_range)}`,
              )}
            ondelete={async (hl) => {
              if (
                !(await confirmDialog({
                  title: m.highlights_delete_confirm(),
                  destructive: true,
                }))
              )
                return;

              const prev = bookHighlights;
              // Optimistic remove, then delete immediately (no delayed undo).
              bookHighlights = bookHighlights.filter((h) => h.id !== hl.id);
              try {
                await beepubSync.deleteHighlight(bookId, hl.id);
                toastStore.success(m.book_highlight_removed());
              } catch (e) {
                toastStore.error((e as Error).message);
                bookHighlights = prev;
              }
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
              <a
                href="/books/{edition.id}"
                class="group"
                data-sveltekit-replacestate
              >
                <div
                  class="aspect-[2/3] rounded-lg overflow-hidden bg-secondary mb-2 book-shadow group-hover:book-shadow-hover transition-shadow"
                >
                  {#if edition.cover_path}
                    <img
                      use:authedSrc={coverUrl(edition.id, null, "thumb")}
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
              {#if edition.id === primaryBookId}
                <div
                  class="absolute top-1 left-1 p-1 bg-amber-500 rounded-full text-white shadow-md"
                  title={m.work_primary_badge()}
                >
                  <Star size={12} class="fill-white" />
                </div>
              {/if}
              {#if isAdmin}
                <div
                  class="absolute top-1 right-1 flex gap-1 opacity-70 can-hover:opacity-0 can-hover:group-hover/edition:opacity-100 transition-opacity"
                >
                  {#if edition.id !== primaryBookId}
                    <button
                      class="p-1 bg-black/50 backdrop-blur-sm rounded-full text-white"
                      title={m.work_set_as_primary()}
                      onclick={() => handleSetPrimary(edition.id)}
                    >
                      <Star size={12} />
                    </button>
                  {/if}
                  <button
                    class="p-1 bg-black/50 backdrop-blur-sm rounded-full text-white"
                    title={m.work_remove_from_work()}
                    onclick={() => handleRemoveEdition(edition.id)}
                  >
                    <X size={12} />
                  </button>
                </div>
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
        <h2 class="text-xl font-bold mb-3 text-foreground">
          {m.book_similar()}
        </h2>
        <div class="flex gap-4 overflow-x-auto pb-2 -mx-2 px-2 snap-x">
          {#each similarBooks as simBook}
            <a
              href="/books/{simBook.id}"
              class="flex-shrink-0 w-28 group"
              data-sveltekit-replacestate
            >
              <div
                class="aspect-[2/3] rounded-lg overflow-hidden bg-secondary mb-2 book-shadow group-hover:book-shadow-hover transition-shadow"
              >
                {#if simBook.cover_path}
                  <img
                    use:authedSrc={coverUrl(
                      simBook.id,
                      simBook.updated_at,
                      "thumb",
                    )}
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

<!-- Mobile back-to-top (above sticky bottom bar) -->
{#if book && !loading}
  <BackToTop />
{/if}

<!-- Mobile Sticky Bottom Bar -->
{#if book && !loading && !$keyboardVisible}
  <div
    class="fixed bottom-0 left-0 right-0 z-40 md:hidden bg-background/95 backdrop-blur-sm border-t border-border px-4 pt-3"
    style="padding-bottom: max(0.75rem, env(safe-area-inset-bottom));"
  >
    <div class="flex items-center gap-2.5" style="max-width: 900px;">
      {#if !isPhysical}
        <button
          onclick={() => goto(`/books/${book!.id}/read`, { replace: true })}
          class="h-12 flex-1 flex items-center justify-center gap-2 bg-foreground hover:bg-foreground/90 text-background font-semibold rounded-full transition-colors text-base"
        >
          <BookOpen size={16} />
          {interaction?.reading_status === "currently_reading"
            ? m.book_continue_reading()
            : m.book_start_reading()}
        </button>
      {:else}
        <span
          class="h-12 flex-1 flex items-center justify-center gap-2 bg-card card-soft rounded-full text-muted-foreground text-sm"
        >
          <BookCopy size={16} />
          {m.physical_badge()}
        </span>
      {/if}
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
      {#if isPhysical}
        <!-- nothing to download -->
      {:else if isNative()}
        {#if downloadRequest}
          <DownloadButton request={downloadRequest} size="lg" />
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
        aria-label={m.book_more_actions()}
        class="h-12 w-12 flex items-center justify-center bg-card card-soft rounded-full text-muted-foreground transition-all"
        onclick={() => (showMobileActions = true)}
        ><EllipsisVertical size={18} /></button
      >
    </div>
  </div>

  <BottomSheet bind:open={showMobileActions}>
    {#each bookActions?.groups() ?? [] as group, i}
      {#if i > 0}
        <div class="border-t border-border my-1"></div>
      {/if}
      {#each group as action (action.key)}
        <button
          class="flex items-center gap-4 w-full px-2 py-3.5 text-[15px] rounded-lg active:bg-secondary transition-colors disabled:opacity-50 {action.destructive
            ? 'text-destructive'
            : 'text-foreground'}"
          disabled={action.disabled}
          onclick={() => {
            showMobileActions = false;
            action.run();
          }}
        >
          <action.icon
            size={20}
            class="shrink-0 {action.tone ??
              (action.destructive
                ? 'text-destructive'
                : 'text-muted-foreground')}"
          />
          {action.label}
        </button>
      {/each}
    {/each}
  </BottomSheet>
{/if}

<BookActions
  bind:this={bookActions}
  {book}
  favorite={interaction?.is_favorite ?? false}
  hasNotes={!!interaction?.notes}
  bind:editions
  bind:primaryBookId
  onfavorite={(_, value) => favorited(value)}
  onnotes={() => scrollToNotes(true)}
  onreported={reported}
  onconverted={loadData}
  onwork={(_, workId) => book && (book.work_id = workId)}
  ondeleted={deleted}
/>
