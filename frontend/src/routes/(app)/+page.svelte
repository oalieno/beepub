<script lang="ts">
  import { onMount } from "svelte";
  import { librariesApi } from "$lib/api/libraries";
  import { toastStore } from "$lib/stores/toast";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import ReadingActivityHeatmap from "$lib/components/ReadingActivityHeatmap.svelte";
  import ReadingStreakCard from "$lib/components/ReadingStreakCard.svelte";
  import { booksApi } from "$lib/api/books";
  import { coverUrl } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import { isNative } from "$lib/platform";
  import { isOnline } from "$lib/services/network";
  import type {
    BookOut,
    BookWithInteractionOut,
    LibraryOut,
    ReadingStats,
  } from "$lib/types";
  import type { DownloadEntry } from "$lib/services/offline";
  import { BookOpen, Download, WifiOff } from "@lucide/svelte";
  import { HomeSkeleton } from "$lib/components/skeletons";
  import * as m from "$lib/paraglide/messages.js";

  let libraries = $state<LibraryOut[]>([]);
  let recentBooks = $state<BookOut[]>([]);
  let continueReadingBooks = $state<BookWithInteractionOut[]>([]);
  let readingActivity = $state<{ date: string; seconds: number }[]>([]);
  let readingStats = $state<ReadingStats | null>(null);
  let downloadedBooks = $state<DownloadEntry[]>([]);
  let offline = $derived(!$isOnline && isNative());
  let currentYear = new Date().getFullYear();
  let loading = $state(true);
  let hasLoadedOnline = $state(false);

  async function loadDownloadedBooks() {
    if (!isNative()) return;
    try {
      const { getDownloadedBooks, getCoverSrc } =
        await import("$lib/services/offline");
      const books = await getDownloadedBooks();
      // Always re-derive cover URIs (stored paths become stale after app restart)
      for (const book of books) {
        book.coverPath = await getCoverSrc(book);
      }
      downloadedBooks = books;
    } catch {
      // ignore
    }
  }

  async function loadOnlineData() {
    try {
      const [libs, activity, stats, currentlyReading] = await Promise.all([
        librariesApi.list(),
        booksApi.getReadingActivity(currentYear).catch(() => []),
        booksApi.getReadingStats().catch(() => null),
        booksApi
          .getMyBooks({
            status: "currently_reading",
            sort: "last_read_at",
            limit: 12,
          })
          .catch(() => ({ items: [], total: 0 })),
      ]);
      libraries = libs;
      readingActivity = activity;
      readingStats = stats;
      continueReadingBooks = currentlyReading.items;

      // Gather recent books from all libraries (only fetch top 12 each)
      const allBooks: BookOut[] = [];
      await Promise.all(
        libraries.map(async (lib) => {
          try {
            const result = await librariesApi.getBooks(lib.id, {
              sort: "added_at",
              limit: 12,
            });
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
      hasLoadedOnline = true;
    } catch {
      // API calls failed — offline state handled by isOnline store
    }
  }

  onMount(async () => {
    await loadDownloadedBooks();
    if (!offline) {
      await loadOnlineData();
    }
    loading = false;
  });

  // Re-fetch data when coming back online
  $effect(() => {
    if (!offline && !hasLoadedOnline && !loading) {
      loadOnlineData();
    }
  });
</script>

<svelte:head>
  <title>{m.home_page_title()}</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-6 sm:px-8 py-6">
  {#if loading}
    <HomeSkeleton />
  {:else if offline}
    <!-- Offline mode -->
    <section class="mb-8">
      <div
        role="status"
        class="bg-amber-500/10 border border-amber-500/30 rounded-2xl px-5 py-4 flex items-center gap-3"
      >
        <WifiOff class="text-amber-500 shrink-0" size={20} />
        <p class="text-sm text-foreground">
          {m.home_offline_message()}
        </p>
      </div>
    </section>

    {#if downloadedBooks.length > 0}
      <section>
        <div class="flex items-end justify-between mb-6">
          <div>
            <h2 class="text-2xl font-bold text-foreground">
              {m.home_downloaded_books()}
            </h2>
            <p class="text-muted-foreground text-sm mt-1">
              {m.home_downloaded_subtitle()}
            </p>
          </div>
          <a
            href="/downloads"
            class="text-primary hover:text-primary/80 text-sm font-medium"
            >{m.home_manage()}</a
          >
        </div>
        <div
          class="grid gap-4"
          style="grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));"
        >
          {#each downloadedBooks as entry (entry.bookId)}
            <a href="/books/{entry.bookId}/read" class="group">
              <div
                class="aspect-[2/3] rounded-xl overflow-hidden bg-muted mb-2"
              >
                {#if entry.coverPath}
                  <img
                    src={entry.coverPath}
                    alt={entry.title}
                    class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                  />
                {:else}
                  <div
                    class="w-full h-full flex items-center justify-center text-muted-foreground/30"
                  >
                    <BookOpen size={32} />
                  </div>
                {/if}
              </div>
              <p
                class="text-sm font-medium text-foreground line-clamp-2 leading-tight group-hover:text-primary transition-colors"
              >
                {entry.title}
              </p>
            </a>
          {/each}
        </div>
      </section>
    {:else}
      <div class="bg-card card-soft rounded-2xl p-12 text-center">
        <Download class="mx-auto text-muted-foreground/30 mb-4" size={48} />
        <p class="text-muted-foreground text-lg">{m.home_no_downloaded()}</p>
        <p class="text-muted-foreground/70 text-sm mt-1">
          {m.home_no_downloaded_subtitle()}
        </p>
      </div>
    {/if}
  {:else}
    <!-- Continue Reading -->
    {#if continueReadingBooks.length > 0}
      <section class="mb-12">
        <div class="flex items-end justify-between mb-6">
          <div>
            <h2 class="text-2xl font-bold text-foreground">
              {m.home_continue_reading()}
            </h2>
            <p class="text-muted-foreground text-sm mt-1">
              {m.home_continue_reading_subtitle()}
            </p>
          </div>
          <a
            href="/my-books?tab=currently_reading"
            class="text-primary hover:text-primary/80 text-sm font-medium"
            >{m.home_see_all()}</a
          >
        </div>
        <div
          class="flex gap-4 overflow-x-auto pb-2 snap-x snap-mandatory scrollbar-hide"
        >
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
                    use:authedSrc={coverUrl(book.id)}
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
                  <div
                    class="absolute bottom-0 left-0 right-0 h-1 bg-muted-foreground/20"
                  >
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
        class="w-full overflow-hidden bg-card card-soft rounded-2xl p-4 sm:p-6"
        style="max-width: 1200px;"
      >
        {#if readingStats}
          <div class="mb-4 pb-4 border-b border-border">
            <ReadingStreakCard
              stats={readingStats}
              {readingActivity}
              onGoalUpdate={async (goalSeconds) => {
                const updated = await booksApi.updateReadingGoal(goalSeconds);
                readingStats = updated;
              }}
            />
          </div>
        {/if}
        <ReadingActivityHeatmap data={readingActivity} year={currentYear} />
      </div>
    </section>

    <!-- Recent Books -->
    <section class="mb-12">
      <div class="flex items-end justify-between mb-6">
        <div>
          <h2 class="text-2xl font-bold text-foreground">
            {m.home_recently_added()}
          </h2>
          <p class="text-muted-foreground text-sm mt-1">
            {m.home_recently_added_subtitle()}
          </p>
        </div>
        {#if libraries.length > 0}
          <a
            href="/libraries"
            class="text-primary hover:text-primary/80 text-sm font-medium"
            >{m.home_browse_all()}</a
          >
        {/if}
      </div>
      {#if recentBooks.length === 0}
        <div class="bg-card card-soft rounded-2xl p-12 text-center">
          <BookOpen class="mx-auto text-muted-foreground/30 mb-4" size={48} />
          <p class="text-muted-foreground text-lg">{m.home_no_books()}</p>
          <p class="text-muted-foreground/70 text-sm mt-1">
            {m.home_no_books_subtitle()}
          </p>
        </div>
      {:else}
        <BookGrid books={recentBooks} enableInteractions />
      {/if}
    </section>

    <!-- Downloaded Books (native only, when books exist) -->
    {#if downloadedBooks.length > 0}
      <section class="mb-12">
        <div class="flex items-end justify-between mb-6">
          <div>
            <h2 class="text-2xl font-bold text-foreground">
              {m.home_downloaded_books()}
            </h2>
            <p class="text-muted-foreground text-sm mt-1">
              {m.home_downloaded_subtitle()}
            </p>
          </div>
          <a
            href="/downloads"
            class="text-primary hover:text-primary/80 text-sm font-medium"
            >{m.home_see_all()}</a
          >
        </div>
        <div
          class="flex gap-4 overflow-x-auto pb-2 snap-x snap-mandatory scrollbar-hide"
        >
          {#each downloadedBooks as entry (entry.bookId)}
            <a
              href="/books/{entry.bookId}/read"
              class="shrink-0 snap-start w-[140px] group"
            >
              <div
                class="aspect-[2/3] rounded-xl overflow-hidden bg-muted mb-2"
              >
                {#if entry.coverPath}
                  <img
                    src={entry.coverPath}
                    alt={entry.title}
                    class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                  />
                {:else}
                  <div
                    class="w-full h-full flex items-center justify-center text-muted-foreground/30"
                  >
                    <BookOpen size={32} />
                  </div>
                {/if}
              </div>
              <p
                class="text-sm font-medium text-foreground line-clamp-2 leading-tight group-hover:text-primary transition-colors"
              >
                {entry.title}
              </p>
              {#if entry.authors?.length}
                <p class="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                  {entry.authors.join(", ")}
                </p>
              {/if}
            </a>
          {/each}
        </div>
      </section>
    {/if}
  {/if}
</div>
