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
  import * as m from "$lib/paraglide/messages.js";

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
  <title>{m.discover_page_title()}</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6 space-y-10">
  <!-- Recommendations -->
  <section>
    <div class="mb-8">
      <div class="flex items-center gap-2">
        <Sparkles size={24} class="text-primary" />
        <h1 class="text-2xl sm:text-3xl font-bold text-foreground">
          {m.discover_recommendations()}
        </h1>
      </div>
      <p class="text-muted-foreground mt-1">
        {m.discover_recommendations_subtitle()}
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
          {m.discover_no_recommendations()}
        </p>
        <p class="text-muted-foreground text-sm max-w-xs">
          {m.discover_no_recommendations_subtitle()}
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
        <h1 class="text-3xl font-bold text-foreground">
          {m.discover_browse()}
        </h1>
      </div>
      <p class="text-muted-foreground mt-1">{m.discover_browse_subtitle()}</p>
    </div>

    <!-- Category Tabs -->
    <div class="relative mb-6 max-w-full">
      <div
        class="inline-flex items-center bg-card card-soft rounded-full px-1.5 py-1.5 gap-1 overflow-x-auto scrollbar-none max-w-full"
      >
        {#each [{ key: "genre", label: m.discover_category_genre() }, { key: "subgenre", label: m.discover_category_subgenre() }, { key: "mood", label: m.discover_category_mood() }, { key: "theme", label: m.discover_category_theme() }, { key: "trope", label: m.discover_category_trope() }] as cat}
          <button
            class="shrink-0 px-5 py-2 rounded-full text-sm font-medium transition-all duration-200 {activeCategory ===
            cat.key
              ? 'bg-primary text-primary-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground hover:bg-secondary'}"
            onclick={() =>
              switchCategory(
                cat.key as "genre" | "subgenre" | "mood" | "theme" | "trope",
              )}
          >
            {cat.label}
          </button>
        {/each}
      </div>
      <!-- Right fade hint for scrollable overflow -->
      <div
        class="absolute right-0 top-0 bottom-0 w-8 pointer-events-none rounded-r-full bg-gradient-to-l from-background to-transparent sm:hidden"
      ></div>
    </div>

    {#if loadingBrowse}
      <BrowseSectionSkeleton sections={3} />
    {:else if browseSections.length === 0}
      <div class="flex flex-col items-center justify-center py-24 text-center">
        <div class="mb-4 p-3 bg-primary/10 rounded-xl">
          <Compass class="text-primary/50" size={28} />
        </div>
        <p class="text-foreground text-lg font-medium mb-2">
          {m.search_no_books_found()}
        </p>
        <p class="text-muted-foreground text-sm max-w-xs">
          {m.discover_no_books_tagged({ category: activeCategory })}
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
              <a
                href="/all-books?tag={encodeURIComponent(section.tag)}"
                class="text-xs text-primary hover:text-primary/80 font-medium transition-colors"
              >
                {m.discover_see_all()}
              </a>
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
