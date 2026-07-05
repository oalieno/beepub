<script lang="ts">
  import { page } from "$app/state";
  import { booksApi } from "$lib/api/books";
  import { seriesApi } from "$lib/api/series";
  import { bookshelvesApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import { coverUrl } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import StarRating from "$lib/components/StarRating.svelte";
  import BookNotesEditor from "$lib/components/BookNotesEditor.svelte";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import BackButton from "$lib/components/BackButton.svelte";
  import Modal from "$lib/components/Modal.svelte";
  import { BookDetailSkeleton } from "$lib/components/skeletons";
  import { BookOpen, ListPlus } from "@lucide/svelte";
  import type {
    BookshelfOut,
    BookWithInteractionOut,
    SeriesOut,
  } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";

  let name = $derived(page.url.searchParams.get("name") ?? "");
  let library = $derived(page.url.searchParams.get("library") ?? "");
  let series = $state<SeriesOut | null>(null);
  let volumes = $state<BookWithInteractionOut[]>([]);
  let loading = $state(true);
  let loadSeq = 0;

  let bookshelves = $state<BookshelfOut[]>([]);
  let showAddToShelf = $state(false);

  async function load(seriesName: string, libraryId: string) {
    const seq = ++loadSeq;
    loading = true;
    try {
      // Resolve the series first. With a library in the URL this is the normal
      // path; without one (an old/shared ?name= link) the backend returns the
      // first matching series and we scope the volumes to its library.
      const detail = await seriesApi.get(seriesName, libraryId || undefined);
      const lib = detail.library_id;
      const [vols, shelves] = await Promise.all([
        booksApi.getAll({ series: seriesName, library: lib, limit: 200 }),
        bookshelvesApi.list().catch(() => [] as BookshelfOut[]),
      ]);
      if (seq !== loadSeq) return;
      series = detail;
      volumes = vols.items;
      bookshelves = shelves;
      // Canonicalise a library-less link so bookmarks/shares carry the library.
      if (!libraryId && typeof history !== "undefined") {
        history.replaceState(
          history.state,
          "",
          `/series?name=${encodeURIComponent(seriesName)}&library=${lib}`,
        );
      }
    } catch (e) {
      if (seq === loadSeq) {
        series = null;
        toastStore.error((e as Error).message);
      }
    } finally {
      if (seq === loadSeq) loading = false;
    }
  }

  async function addToShelf(shelfId: string) {
    if (!series) return;
    try {
      await bookshelvesApi.addSeries(
        shelfId,
        series.series_name,
        series.library_id,
      );
      toastStore.success(m.bookshelf_added());
      showAddToShelf = false;
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  $effect(() => {
    if (name) load(name, library);
    else loading = false;
  });

  async function handleRating(rating: number | null) {
    if (!series) return;
    try {
      await seriesApi.updateRating(
        series.series_name,
        series.library_id,
        rating,
      );
      series = { ...series, rating };
      toastStore.success(m.book_rating_updated());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function saveNotes(notes: string | null) {
    if (series)
      await seriesApi.updateNotes(series.series_name, series.library_id, notes);
  }

  function handleNotesSaved(notes: string | null) {
    if (series) series = { ...series, notes };
  }
</script>

<svelte:head>
  <title>{(series?.series_name ?? m.nav_series()) + " - BeePub"}</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6 pb-24 md:pb-6">
  {#if loading}
    <BookDetailSkeleton />
  {:else if series}
    <!-- Back Button -->
    <div class="mb-6 -ml-1">
      <BackButton
        href="/"
        label={m.common_back()}
        onclick={() => history.back()}
      />
    </div>

    <!-- Hero Section -->
    <div class="flex flex-col md:flex-row gap-12">
      <!-- Cover -->
      <div
        class="flex-shrink-0 w-64 mx-auto md:mx-0 flex justify-center md:self-start"
      >
        {#if series.cover_book?.cover_path}
          <img
            use:authedSrc={coverUrl(
              series.cover_book.id,
              series.cover_book.updated_at,
            )}
            alt="{series.series_name} cover"
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
          <p class="text-xs text-muted-foreground uppercase tracking-wide mb-1">
            {m.nav_series()}
          </p>
          <h1 class="text-4xl font-bold leading-tight text-foreground">
            {series.series_name}
          </h1>
          <p class="text-muted-foreground text-lg mt-2">
            {m.series_book_count({ count: String(series.book_count) })}
          </p>
        </div>

        <!-- Series rating -->
        <div class="mt-5 flex items-center gap-3">
          <StarRating value={series.rating} onchange={handleRating} />
          <span class="text-sm text-muted-foreground"
            >{m.series_rating_label()}</span
          >
        </div>

        <!-- Actions -->
        <div class="mt-5">
          <button
            class="inline-flex items-center gap-2 rounded-xl bg-secondary/60 hover:bg-secondary px-4 py-2 text-sm font-medium text-foreground transition-colors"
            onclick={() => (showAddToShelf = true)}
          >
            <ListPlus size={16} />
            {m.book_add_to_shelf()}
          </button>
        </div>
      </div>
    </div>

    <!-- Notes -->
    <div class="border-t border-border my-8"></div>
    <BookNotesEditor
      bookId={series.cover_book?.id ?? ""}
      title={m.series_notes_title()}
      initialNotes={series.notes ?? ""}
      saveFn={saveNotes}
      onchange={handleNotesSaved}
    />

    <!-- Volumes -->
    {#if volumes.length > 0}
      <div class="border-t border-border my-8"></div>
      <h2 class="text-xl font-bold mb-4 text-foreground">
        {m.series_volumes()}
      </h2>
      <BookGrid books={volumes} />
    {/if}
  {/if}
</div>

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
