<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { booksApi } from "$lib/api/books";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import BookCard from "$lib/components/BookCard.svelte";
  import type {
    BookWithInteractionOut,
    ReadingStatus,
    TagBrowseSection,
  } from "$lib/types";
  import { Compass, Sparkles } from "@lucide/svelte";
  import Spinner from "$lib/components/Spinner.svelte";

  let recommendations = $state<BookWithInteractionOut[]>([]);
  let browseSections = $state<TagBrowseSection[]>([]);
  let activeCategory = $state<"genre" | "mood" | "topic">("genre");
  let loadingRecs = $state(true);
  let loadingBrowse = $state(true);

  // Track reading status for browse section books
  let browseInteractions = $state<Record<string, ReadingStatus | null>>({});

  onMount(async () => {
    if (!$authStore.token) {
      goto("/login");
      return;
    }
    loadRecommendations();
    loadBrowse();
  });

  async function loadRecommendations() {
    loadingRecs = true;
    try {
      recommendations = await booksApi.getRecommendations(
        $authStore.token!,
        20,
      );
    } catch (e) {
      console.error("Failed to load recommendations:", e);
    } finally {
      loadingRecs = false;
    }
  }

  async function loadBrowse() {
    loadingBrowse = true;
    try {
      browseSections = await booksApi.getBrowseByCategory(
        activeCategory,
        $authStore.token!,
      );
      // Fetch interactions for all browse books
      const allBookIds = browseSections.flatMap((s) =>
        s.books.map((b) => b.id),
      );
      if (allBookIds.length > 0 && $authStore.token) {
        try {
          const resp = await booksApi.getBatchInteractions(
            allBookIds,
            $authStore.token,
          );
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
      console.error("Failed to load browse sections:", e);
    } finally {
      loadingBrowse = false;
    }
  }

  async function switchCategory(cat: "genre" | "mood" | "topic") {
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

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-10">
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
      <div class="flex items-center justify-center py-12">
        <Spinner size="lg" />
      </div>
    {:else if recommendations.length === 0}
      <div
        class="bg-card card-soft rounded-2xl p-8 text-center text-muted-foreground"
      >
        <p class="text-lg mb-2">No recommendations yet</p>
        <p class="text-sm">
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
      {#each ["genre", "mood", "topic"] as cat}
        <button
          class="px-5 py-2 rounded-full text-sm font-medium transition-all duration-200 capitalize {activeCategory ===
          cat
            ? 'bg-primary text-primary-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground hover:bg-secondary'}"
          onclick={() => switchCategory(cat as "genre" | "mood" | "topic")}
        >
          {cat}
        </button>
      {/each}
    </div>

    {#if loadingBrowse}
      <div class="flex items-center justify-center py-12">
        <Spinner size="lg" />
      </div>
    {:else if browseSections.length === 0}
      <div
        class="bg-card card-soft rounded-2xl p-8 text-center text-muted-foreground"
      >
        <p>No books tagged with {activeCategory} tags yet.</p>
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
                <div
                  class="flex-shrink-0 w-[calc(50%-8px)] sm:w-[calc(33.33%-11px)] md:w-[calc(25%-12px)] lg:w-[calc(20%-13px)] xl:w-[calc(16.66%-14px)]"
                >
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
