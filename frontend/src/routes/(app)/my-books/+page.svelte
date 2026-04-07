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
  import * as m from "$lib/paraglide/messages.js";

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
    {
      key: "currently_reading",
      label: m.mybooks_tab_reading(),
      icon: BookOpenCheck,
    },
    {
      key: "want_to_read",
      label: m.mybooks_tab_want_to_read(),
      icon: Bookmark,
    },
    { key: "read", label: m.mybooks_tab_read(), icon: CircleCheck },
    {
      key: "did_not_finish",
      label: m.mybooks_tab_did_not_finish(),
      icon: CircleX,
    },
    { key: "favorites", label: m.mybooks_tab_favorites(), icon: Heart },
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
  <title>{m.mybooks_page_title()}</title>
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
      <p class="text-foreground text-lg font-medium mb-2">
        {m.mybooks_no_books()}
      </p>
      <p class="text-muted-foreground text-sm max-w-xs">
        {#if activeTab === "favorites"}
          {m.mybooks_empty_favorites()}
        {:else}
          {m.mybooks_empty_default()}
        {/if}
      </p>
    </div>
  {:else}
    <p class="text-sm text-muted-foreground mb-4">
      {m.mybooks_book_count({ count: String(total) })}
    </p>
    <BookGrid {books} />
  {/if}
</div>
