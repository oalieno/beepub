<script lang="ts">
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import type { BookWithInteractionOut, ReadingStatus } from "$lib/types";
  import {
    BookOpenCheck,
    Bookmark,
    CircleCheck,
    CircleX,
    Heart,
    BookOpen,
  } from "@lucide/svelte";
  import { BookGridSkeleton } from "$lib/components/skeletons";

  type TabKey =
    | "currently_reading"
    | "want_to_read"
    | "read"
    | "did_not_finish"
    | "favorites";

  const tabs: {
    key: TabKey;
    label: string;
    icon: typeof BookOpenCheck;
  }[] = [
    { key: "currently_reading", label: "Reading", icon: BookOpenCheck },
    { key: "want_to_read", label: "Want to Read", icon: Bookmark },
    { key: "read", label: "Read", icon: CircleCheck },
    { key: "did_not_finish", label: "Did Not Finish", icon: CircleX },
    { key: "favorites", label: "Favorites", icon: Heart },
  ];

  let books = $state<BookWithInteractionOut[]>([]);
  let total = $state(0);
  let loading = $state(true);

  // Derive active tab from URL so back/forward navigation works
  let urlTab = $derived(
    (page.url.searchParams.get("tab") as TabKey | null) ?? "currently_reading",
  );
  let activeTab = $derived(
    tabs.some((t) => t.key === urlTab) ? urlTab : "currently_reading",
  );

  // Load books whenever activeTab changes (including back/forward navigation)
  $effect(() => {
    const tab = activeTab;
    loading = true;
    const isFavoriteTab = tab === "favorites";
    booksApi
      .getMyBooks({
        status: isFavoriteTab ? undefined : (tab as ReadingStatus),
        favorite: isFavoriteTab ? true : undefined,
        sort: tab === "currently_reading" ? "last_read_at" : "updated_at",
        limit: 60,
      })
      .then((result) => {
        books = result.items;
        total = result.total;
      })
      .catch((e) => {
        toastStore.error((e as Error).message);
      })
      .finally(() => {
        loading = false;
      });
  });

  function switchTab(tab: TabKey) {
    goto(`/my-books?tab=${tab}`);
  }
</script>

<svelte:head>
  <title>My Books - BeePub</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6">
  <!-- Tabs -->
  <div class="flex gap-1 overflow-x-auto pb-1 mb-8 -mx-4 px-4 sm:mx-0 sm:px-0">
    {#each tabs as tab}
      <button
        class="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors {activeTab ===
        tab.key
          ? 'bg-primary text-primary-foreground'
          : 'text-muted-foreground hover:text-foreground hover:bg-muted'}"
        onclick={() => switchTab(tab.key)}
      >
        <tab.icon size={15} />
        {tab.label}
      </button>
    {/each}
  </div>

  {#if loading}
    <BookGridSkeleton count={12} />
  {:else if books.length === 0}
    <div class="flex flex-col items-center justify-center py-24 text-center">
      <div class="mb-4 p-3 bg-primary/10 rounded-xl">
        <BookOpen class="text-primary/50" size={28} />
      </div>
      <p class="text-foreground text-lg font-medium mb-2">No books here yet</p>
      <p class="text-muted-foreground text-sm max-w-xs">
        {#if activeTab === "favorites"}
          Tap the heart icon on a book to add it to your favorites.
        {:else}
          Set a book's reading status to see it here.
        {/if}
      </p>
    </div>
  {:else}
    <p class="text-sm text-muted-foreground mb-4">
      {total}
      {total === 1 ? "book" : "books"}
    </p>
    <BookGrid {books} />
  {/if}
</div>
