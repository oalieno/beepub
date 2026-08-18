<script lang="ts">
  import { onMount } from "svelte";
  import { librariesApi } from "$lib/api/libraries";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import ReadingActivityHeatmap from "$lib/components/ReadingActivityHeatmap.svelte";
  import ReadingStreakCard from "$lib/components/ReadingStreakCard.svelte";
  import { booksApi } from "$lib/api/books";
  import { coverUrl } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import { isOnline } from "$lib/services/network";
  import { readingSyncStamp } from "$lib/services/readingSync";
  import type {
    BookWithInteractionOut,
    LibraryOut,
    ReadingStats,
  } from "$lib/types";
  import { BookOpen } from "@lucide/svelte";
  import { HomeSkeleton } from "$lib/components/skeletons";
  import * as m from "$lib/paraglide/messages.js";

  let libraries = $state<LibraryOut[]>([]);
  let recentBooks = $state<BookWithInteractionOut[]>([]);
  let continueReadingBooks = $state<BookWithInteractionOut[]>([]);
  let readingActivity = $state<{ date: string; seconds: number }[]>([]);
  let readingStats = $state<ReadingStats | null>(null);
  let currentYear = new Date().getFullYear();
  let loading = $state(true);
  let hasLoadedOnline = $state(false);
  let loadFailed = $state(false);

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
      const allBooks: BookWithInteractionOut[] = [];
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
      loadFailed = false;
    } catch {
      // Distinguish "couldn't load" from "library is empty" so the user
      // sees a retry instead of a misleading empty state.
      loadFailed = true;
    }
  }

  onMount(async () => {
    await loadOnlineData();
    loading = false;
  });

  // A mount-time failure (server blip shorter than the offline-shell
  // damping window) heals itself once the server answers again.
  $effect(() => {
    if ($isOnline && !hasLoadedOnline && !loading) {
      void loadOnlineData();
    }
  });

  // A background sync just pushed offline reading to the server: the
  // continue-reading percentages this page fetched at mount are stale now.
  let prevSyncStamp = $readingSyncStamp;
  $effect(() => {
    const stamp = $readingSyncStamp;
    if (stamp !== prevSyncStamp) {
      prevSyncStamp = stamp;
      if (hasLoadedOnline) void loadOnlineData();
    }
  });
</script>

<svelte:head>
  <title>{m.home_page_title()}</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-6 sm:px-8 py-6">
  {#if loading}
    <HomeSkeleton />
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
              class="shrink-0 snap-start w-[140px] sm:w-[160px] group"
            >
              <div
                class="aspect-[2/3] rounded-xl overflow-hidden bg-muted mb-2 relative"
              >
                {#if book.cover_path}
                  <img
                    use:authedSrc={coverUrl(book.id, book.updated_at)}
                    alt={book.display_title ?? m.common_untitled()}
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
                {book.display_title ?? m.common_untitled()}
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
            href="/libraries/all"
            class="text-primary hover:text-primary/80 text-sm font-medium"
            >{m.home_browse_all()}</a
          >
        {/if}
      </div>
      {#if loadFailed}
        <div class="bg-card card-soft rounded-2xl p-12 text-center">
          <BookOpen class="mx-auto text-muted-foreground/30 mb-4" size={48} />
          <p class="text-muted-foreground text-lg">{m.home_load_failed()}</p>
          <button
            class="mt-3 inline-flex items-center rounded-xl px-4 py-2 text-sm font-medium bg-secondary text-secondary-foreground hover:bg-secondary/80 transition-colors"
            onclick={loadOnlineData}
          >
            {m.common_retry()}
          </button>
        </div>
      {:else if recentBooks.length === 0}
        <div class="bg-card card-soft rounded-2xl p-12 text-center">
          <BookOpen class="mx-auto text-muted-foreground/30 mb-4" size={48} />
          <p class="text-muted-foreground text-lg">{m.home_no_books()}</p>
          <p class="text-muted-foreground/70 text-sm mt-1">
            {m.home_no_books_subtitle()}
          </p>
        </div>
      {:else}
        <BookGrid books={recentBooks} />
      {/if}
    </section>
  {/if}
</div>
