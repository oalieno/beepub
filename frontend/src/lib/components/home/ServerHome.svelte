<script lang="ts">
  /**
   * Home in server mode: continue reading (server books, plus books that
   * so far live only on this device), reading activity, recently added.
   */
  import { onMount } from "svelte";
  import { librariesApi } from "$lib/api/libraries";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import ContinueReadingRow, {
    type ContinueReadingItem,
  } from "$lib/components/ContinueReadingRow.svelte";
  import { isNative } from "$lib/platform";
  import ReadingActivityHeatmap from "$lib/components/ReadingActivityHeatmap.svelte";
  import ReadingStreakCard from "$lib/components/ReadingStreakCard.svelte";
  import { booksApi } from "$lib/api/books";
  import { coverUrl } from "$lib/api/client";
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
  let continueReading = $state<ContinueReadingItem[]>([]);
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
      continueReading = await mergeContinueReading(currentlyReading.items);

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

  /** Server books being read, merged with device books that have no
   *  server copy yet (linked ones already appear as their server copy),
   *  most recently read first. */
  async function mergeContinueReading(
    books: BookWithInteractionOut[],
  ): Promise<ContinueReadingItem[]> {
    const merged: (ContinueReadingItem & { lastReadAt: string })[] = books.map(
      (book) => ({
        id: book.id,
        title: book.display_title ?? m.common_untitled(),
        authors: book.display_authors ?? [],
        percentage: book.reading_percentage ?? null,
        authedCover: book.cover_path
          ? coverUrl(book.id, book.updated_at)
          : null,
        lastReadAt: book.last_read_at ?? "",
      }),
    );
    if (isNative()) {
      try {
        const { loadShelfEntries, continueItems } =
          await import("$lib/services/localShelf");
        const entries = await loadShelfEntries();
        merged.push(
          ...continueItems(entries.filter((e) => !e.linked)).map((item) => ({
            ...item,
            authedCover: null,
          })),
        );
      } catch {
        // The device shelf is a bonus here; the server list stands alone.
      }
    }
    return merged
      .sort((a, b) => b.lastReadAt.localeCompare(a.lastReadAt))
      .slice(0, 12);
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

<div class="max-w-6xl mx-auto px-6 sm:px-8 py-6">
  {#if loading}
    <HomeSkeleton />
  {:else}
    <!-- Continue Reading -->
    {#if continueReading.length > 0}
      <ContinueReadingRow
        items={continueReading}
        seeAllHref="/my-books?tab=currently_reading"
      />
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
