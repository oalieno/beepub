<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { authStore } from "$lib/stores/auth";
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

  let activeTab = $state<TabKey>("currently_reading");
  let books = $state<BookWithInteractionOut[]>([]);
  let total = $state(0);
  let loading = $state(true);

  onMount(() => {
    if (!$authStore.token) {
      goto("/login");
      return;
    }
    const urlTab = $page.url.searchParams.get("tab") as TabKey | null;
    if (urlTab && tabs.some((t) => t.key === urlTab)) {
      activeTab = urlTab;
    }
    loadBooks();
  });

  async function loadBooks() {
    loading = true;
    try {
      const isFavoriteTab = activeTab === "favorites";
      const result = await booksApi.getMyBooks($authStore.token!, {
        status: isFavoriteTab
          ? undefined
          : (activeTab as ReadingStatus),
        favorite: isFavoriteTab ? true : undefined,
        sort: activeTab === "currently_reading" ? "last_read_at" : "updated_at",
        limit: 60,
      });
      books = result.items;
      total = result.total;
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  function switchTab(tab: TabKey) {
    activeTab = tab;
    const url = new URL(window.location.href);
    url.searchParams.set("tab", tab);
    window.history.replaceState({}, "", url.toString());
    loadBooks();
  }
</script>

<svelte:head>
  <title>My Books - BeePub</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
  <div class="mb-8">
    <h1 class="text-3xl font-bold text-foreground">My Books</h1>
    <p class="text-muted-foreground mt-1">
      Your reading lists and favorites
    </p>
  </div>

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
    <div class="flex items-center justify-center h-40">
      <div
        class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-primary"
      ></div>
    </div>
  {:else if books.length === 0}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      <BookOpen class="mx-auto mb-4 text-muted-foreground/30" size={48} />
      <p class="text-muted-foreground text-lg">No books here yet</p>
      <p class="text-muted-foreground/70 text-sm mt-1">
        {#if activeTab === "favorites"}
          Tap the heart icon on a book to add it to your favorites.
        {:else}
          Set a book's reading status to see it here.
        {/if}
      </p>
    </div>
  {:else}
    <p class="text-sm text-muted-foreground mb-4">
      {total} {total === 1 ? "book" : "books"}
    </p>
    <BookGrid books={books} />
  {/if}
</div>
