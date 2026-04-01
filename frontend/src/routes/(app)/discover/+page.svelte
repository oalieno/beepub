<script lang="ts">
  import { onMount } from "svelte";
  import { booksApi } from "$lib/api/books";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import BookCard from "$lib/components/BookCard.svelte";
  import type {
    BookWithInteractionOut,
    ReadingStatus,
    TagBrowseSection,
  } from "$lib/types";
  import { Compass, Sparkles } from "@lucide/svelte";
  import {
    BookGridSkeleton,
    BrowseSectionSkeleton,
  } from "$lib/components/skeletons";
  import { toastStore } from "$lib/stores/toast";

  let recommendations = $state<BookWithInteractionOut[]>([]);
  let browseSections = $state<TagBrowseSection[]>([]);
  let activeCategory = $state<
    "genre" | "subgenre" | "mood" | "theme" | "trope"
  >("genre");
  let loadingRecs = $state(true);
  let loadingBrowse = $state(true);

  // Track reading status for browse section books
  let browseInteractions = $state<Record<string, ReadingStatus | null>>({});

  onMount(async () => {
    loadRecommendations();
    loadBrowse();
  });

  async function loadRecommendations() {
    loadingRecs = true;
    try {
      recommendations = await booksApi.getRecommendations(20);
    } catch (e) {
      toastStore.error("Failed to load recommendations");
    } finally {
      loadingRecs = false;
    }
  }

  async function loadBrowse() {
    loadingBrowse = true;
    try {
      browseSections = await booksApi.getBrowseByCategory(activeCategory);
      // Fetch interactions for all browse books
      const allBookIds = browseSections.flatMap((s) =>
        s.books.map((b) => b.id),
      );
      if (allBookIds.length > 0) {
        try {
          const resp = await booksApi.getBatchInteractions(allBookIds);
          const newMap: Record<string, ReadingStatus | null> = {};
          for (const [id, item] of Object.entries(resp.interactions)) {
            newMap[id] = (item.reading_status as ReadingStatus) ?? null;
          }
          browseInteractions = newMap;
        } catch {
          // silently fail
        }
      }
    } catch (e) {
      toastStore.error("Failed to load browse sections");
    } finally {
      loadingBrowse = false;
    }
  }

  async function switchCategory(
    cat: "genre" | "subgenre" | "mood" | "theme" | "trope",
  ) {
    activeCategory = cat;
    await loadBrowse();
  }

  function handleBrowseStatusChange(
    bookId: string,
    status: ReadingStatus | null,
  ) {
    browseInteractions = { ...browseInteractions, [bookId]: status };
  }
</script>

<svelte:head>
  <title>Discover - BeePub</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6 space-y-10">
  <!-- Recommendations -->
  <section>
    <div class="mb-8">
      <div class="flex items-center gap-2">
        <Sparkles size={24} class="text-primary" />
        <h1 class="text-3xl font-bold text-foreground">Recommended for You</h1>
      </div>
      <p class="text-muted-foreground mt-1">
        Based on your reading activity and favorites.
      </p>
    </div>

    {#if loadingRecs}
      <BookGridSkeleton count={12} />
    {:else if recommendations.length === 0}
      <div class="flex flex-col items-center justify-center py-24 text-center">
        <div class="mb-4 p-3 bg-primary/10 rounded-xl">
          <Sparkles class="text-primary/50" size={28} />
        </div>
        <p class="text-foreground text-lg font-medium mb-2">
          No recommendations yet
        </p>
        <p class="text-muted-foreground text-sm max-w-xs">
          Start reading and rating books to get personalized recommendations.
        </p>
      </div>
    {:else}
      <BookGrid books={recommendations} enableInteractions={true} />
    {/if}
  </section>

  <!-- Browse by Category -->
  <section>
    <div class="mb-8">
      <div class="flex items-center gap-2">
        <Compass size={24} class="text-primary" />
        <h1 class="text-3xl font-bold text-foreground">Browse</h1>
      </div>
      <p class="text-muted-foreground mt-1">
        Explore books by AI-generated tags.
      </p>
    </div>

    <!-- Category Tabs -->
    <div
      class="flex items-center bg-card card-soft rounded-full px-1.5 py-1.5 gap-1 w-fit mb-6"
    >
      {#each ["genre", "subgenre", "mood", "theme", "trope"] as cat}
        <button
          class="px-5 py-2 rounded-full text-sm font-medium transition-all duration-200 capitalize {activeCategory ===
          cat
            ? 'bg-primary text-primary-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground hover:bg-secondary'}"
          onclick={() =>
            switchCategory(
              cat as "genre" | "subgenre" | "mood" | "theme" | "trope",
            )}
        >
          {cat}
        </button>
      {/each}
    </div>

    {#if loadingBrowse}
      <BrowseSectionSkeleton sections={3} />
    {:else if browseSections.length === 0}
      <div class="flex flex-col items-center justify-center py-24 text-center">
        <div class="mb-4 p-3 bg-primary/10 rounded-xl">
          <Compass class="text-primary/50" size={28} />
        </div>
        <p class="text-foreground text-lg font-medium mb-2">No books found</p>
        <p class="text-muted-foreground text-sm max-w-xs">
          No books tagged with {activeCategory} tags yet.
        </p>
      </div>
    {:else}
      <div class="space-y-10">
        {#each browseSections as section}
          <div>
            <div class="flex items-center justify-between mb-3">
              <h3 class="text-lg font-semibold text-foreground">
                {section.label}
              </h3>
              <span class="text-xs text-muted-foreground">
                {section.book_count}
                {section.book_count === 1 ? "book" : "books"}
              </span>
            </div>
            <div
              class="flex gap-4 overflow-x-auto pb-4 -mx-2 px-2 scrollbar-thin"
            >
              {#each section.books as book (book.id)}
                <div class="flex-shrink-0 w-[140px] sm:w-[160px]">
                  <BookCard
                    {book}
                    readingStatus={browseInteractions[book.id] ?? null}
                    onStatusChange={handleBrowseStatusChange}
                  />
                </div>
              {/each}
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </section>
</div>
