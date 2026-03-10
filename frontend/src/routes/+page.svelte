<script lang="ts">
  import { onMount } from "svelte";
  import { authStore } from "$lib/stores/auth";
  import { librariesApi } from "$lib/api/libraries";
  import { bookshelvesApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import ReadingActivityHeatmap from "$lib/components/ReadingActivityHeatmap.svelte";
  import CollectionCard from "$lib/components/CollectionCard.svelte";
  import { booksApi } from "$lib/api/books";
  import type {
    BookOut,
    BookshelfOut,
    BookWithInteractionOut,
    LibraryOut,
  } from "$lib/types";
  import { goto } from "$app/navigation";
  import { BookOpen, BookMarked } from "@lucide/svelte";

  let libraries = $state<LibraryOut[]>([]);
  let bookshelves = $state<BookshelfOut[]>([]);
  let recentBooks = $state<BookOut[]>([]);
  let continueReadingBooks = $state<BookWithInteractionOut[]>([]);
  let readingActivity = $state<{ date: string; seconds: number }[]>([]);
  let currentYear = new Date().getFullYear();
  let loading = $state(true);

  onMount(async () => {
    try {
      const [libs, shelves, activity, currentlyReading] = await Promise.all([
        librariesApi.list($authStore.token!),
        bookshelvesApi.list($authStore.token!),
        booksApi
          .getReadingActivity(currentYear, $authStore.token!)
          .catch(() => []),
        booksApi
          .getMyBooks($authStore.token!, {
            status: "currently_reading",
            sort: "last_read_at",
            limit: 12,
          })
          .catch(() => ({ items: [], total: 0 })),
      ]);
      libraries = libs;
      bookshelves = shelves;
      readingActivity = activity;
      continueReadingBooks = currentlyReading.items;

      // Gather recent books from all libraries (only fetch top 12 each)
      const allBooks: BookOut[] = [];
      await Promise.all(
        libraries.map(async (lib) => {
          try {
            const result = await librariesApi.getBooks(
              lib.id,
              $authStore.token!,
              { sort: "added_at", limit: 12 },
            );
            allBooks.push(...result.items);
          } catch {
            // skip
          }
        }),
      );
      allBooks.sort((a, b) => {
        const aDate = a.calibre_added_at ?? a.created_at;
        const bDate = b.calibre_added_at ?? b.created_at;
        return new Date(bDate).getTime() - new Date(aDate).getTime();
      });
      recentBooks = allBooks.slice(0, 12);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  });
</script>

<svelte:head>
  <title>BeePub - Home</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
  {#if loading}
    <div class="flex items-center justify-center h-64">
      <div
        class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-primary"
      ></div>
    </div>
  {:else}
    <!-- Hero greeting -->
    <section class="mb-12">
      <div
        class="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-2"
      >
        <div>
          <h1
            class="text-4xl md:text-5xl font-bold leading-tight text-foreground"
          >
            Happy reading{$authStore.user
              ? `,\n${$authStore.user.username}`
              : ""}
          </h1>
          <p class="text-muted-foreground text-lg mt-3 max-w-md">
            Explore your personal library. Discover new stories and revisit old
            favorites.
          </p>
        </div>
        <div class="flex items-center gap-6 text-center">
          <div>
            <p class="text-3xl font-bold text-primary">{libraries.length}</p>
            <p class="text-muted-foreground text-xs mt-0.5">Libraries</p>
          </div>
          <div class="w-px h-8 bg-border"></div>
          <div>
            <p class="text-3xl font-bold text-primary">
              {libraries.reduce((sum, lib) => sum + (lib.book_count ?? 0), 0).toLocaleString()}
            </p>
            <p class="text-muted-foreground text-xs mt-0.5">Books</p>
          </div>
          <div class="w-px h-8 bg-border"></div>
          <div>
            <p class="text-3xl font-bold text-primary">{bookshelves.length}</p>
            <p class="text-muted-foreground text-xs mt-0.5">Shelves</p>
          </div>
        </div>
      </div>
    </section>

    <!-- Continue Reading -->
    {#if continueReadingBooks.length > 0}
      <section class="mb-12">
        <div class="flex items-end justify-between mb-6">
          <div>
            <h2 class="text-2xl font-bold text-foreground">Continue Reading</h2>
            <p class="text-muted-foreground text-sm mt-1">
              Pick up where you left off
            </p>
          </div>
          <a
            href="/my-books?tab=currently_reading"
            class="text-primary hover:text-primary/80 text-sm font-medium"
            >See all →</a
          >
        </div>
        <div class="flex gap-4 overflow-x-auto pb-2 snap-x snap-mandatory scrollbar-hide">
          {#each continueReadingBooks as book}
            <a
              href="/books/{book.id}/read"
              class="shrink-0 snap-start w-[140px] group"
            >
              <div
                class="aspect-[2/3] rounded-xl overflow-hidden bg-muted mb-2 relative"
              >
                {#if book.cover_path}
                  <img
                    src="/covers/{book.id}.jpg"
                    alt={book.display_title ?? "Book cover"}
                    class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                  />
                {:else}
                  <div
                    class="w-full h-full flex items-center justify-center text-muted-foreground/30"
                  >
                    <BookOpen size={32} />
                  </div>
                {/if}
                {#if book.reading_percentage != null}
                  <div class="absolute bottom-0 left-0 right-0 h-1 bg-muted-foreground/20">
                    <div
                      class="h-full bg-primary transition-all"
                      style="width: {Math.round(book.reading_percentage)}%"
                    ></div>
                  </div>
                {/if}
              </div>
              <p
                class="text-sm font-medium text-foreground line-clamp-2 leading-tight group-hover:text-primary transition-colors"
              >
                {book.display_title ?? "Untitled"}
              </p>
              {#if book.reading_percentage != null}
                <p class="text-xs text-muted-foreground mt-0.5">
                  {Math.round(book.reading_percentage)}%
                </p>
              {/if}
            </a>
          {/each}
        </div>
      </section>
    {/if}

    <!-- Reading Activity Heatmap -->
    <section class="mb-12">
      <div
        class="w-full max-w-full overflow-hidden bg-card card-soft rounded-2xl p-4 sm:p-6"
      >
        <ReadingActivityHeatmap data={readingActivity} year={currentYear} />
      </div>
    </section>

    <!-- Recent Books -->
    <section class="mb-12">
      <div class="flex items-end justify-between mb-6">
        <div>
          <h2 class="text-2xl font-bold text-foreground">Recently Added</h2>
          <p class="text-muted-foreground text-sm mt-1">
            Fresh additions to your library
          </p>
        </div>
        {#if libraries.length > 0}
          <a
            href="/libraries"
            class="text-primary hover:text-primary/80 text-sm font-medium"
            >Browse all →</a
          >
        {/if}
      </div>
      {#if recentBooks.length === 0}
        <div class="bg-card card-soft rounded-2xl p-12 text-center">
          <BookOpen class="mx-auto text-muted-foreground/30 mb-4" size={48} />
          <p class="text-muted-foreground text-lg">No books yet</p>
          <p class="text-muted-foreground/70 text-sm mt-1">
            Upload some EPUBs to get started.
          </p>
        </div>
      {:else}
        <BookGrid books={recentBooks} />
      {/if}
    </section>

    <!-- Bookshelves -->
    <section>
      <div class="flex items-end justify-between mb-6">
        <div>
          <h2 class="text-2xl font-bold text-foreground">My Shelves</h2>
          <p class="text-muted-foreground text-sm mt-1">
            Your curated collections
          </p>
        </div>
        <a
          href="/bookshelves"
          class="text-primary hover:text-primary/80 text-sm font-medium"
          >View all →</a
        >
      </div>
      {#if bookshelves.length === 0}
        <div class="bg-card card-soft rounded-2xl p-12 text-center">
          <BookMarked class="mx-auto text-muted-foreground/30 mb-4" size={48} />
          <p class="text-muted-foreground text-lg">No shelves yet</p>
          <p class="text-muted-foreground/70 text-sm mt-1">
            Create a bookshelf to organize your reading.
          </p>
        </div>
      {:else}
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-2 gap-4">
          {#each bookshelves.slice(0, 6) as shelf}
            <CollectionCard
              href="/bookshelves/{shelf.id}"
              name={shelf.name}
              previewBookIds={shelf.preview_book_ids}
              bookCount={shelf.book_count}
              badgeLabel={shelf.is_public ? "Public" : "Private"}
              badgeClass={shelf.is_public
                ? "bg-primary/15 text-primary"
                : "bg-secondary text-muted-foreground"}
            >
              {#snippet icon()}
                <BookMarked
                  class="text-muted-foreground/50 shrink-0"
                  size={16}
                />
              {/snippet}
            </CollectionCard>
          {/each}
        </div>
      {/if}
    </section>
  {/if}
</div>
