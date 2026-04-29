<script lang="ts">
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
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

  const PAGE_SIZE = 60;

  let books = $state<BookWithInteractionOut[]>([]);
  let total = $state(0);
  let loading = $state(true);
  let loadingMore = $state(false);
  let requestSeq = 0;
  let hasMore = $derived(books.length < total);

  // Derive active tab from URL so back/forward navigation works
  let urlTab = $derived(
    (page.url.searchParams.get("tab") as TabKey | null) ?? "currently_reading",
  );
  let activeTab = $derived(
    tabs.some((t) => t.key === urlTab) ? urlTab : "currently_reading",
  );

  function getTabQuery(tab: TabKey) {
    const isFavoriteTab = tab === "favorites";
    return {
      status: isFavoriteTab ? undefined : (tab as ReadingStatus),
      favorite: isFavoriteTab ? true : undefined,
      sort: tab === "currently_reading" ? "last_read_at" : "updated_at",
    };
  }

  async function loadFirstPage(tab: TabKey, seq: number) {
    loading = true;
    loadingMore = false;
    try {
      const result = await booksApi.getMyBooks({
        ...getTabQuery(tab),
        limit: PAGE_SIZE,
        offset: 0,
      });
      if (seq !== requestSeq) return;
      books = result.items;
      total = result.total;
    } catch (e) {
      if (seq === requestSeq) toastStore.error((e as Error).message);
    } finally {
      if (seq === requestSeq) {
        loading = false;
      }
    }
  }

  async function loadMore() {
    if (loading || loadingMore || !hasMore) return;
    const seq = requestSeq;
    const tab = activeTab;
    loadingMore = true;
    try {
      const result = await booksApi.getMyBooks({
        ...getTabQuery(tab),
        limit: PAGE_SIZE,
        offset: books.length,
      });
      if (seq !== requestSeq || tab !== activeTab) return;
      books = [...books, ...result.items];
      total = result.total;
    } catch (e) {
      if (seq === requestSeq) toastStore.error((e as Error).message);
    } finally {
      if (seq === requestSeq) {
        loadingMore = false;
      }
    }
  }

  // Load books whenever activeTab changes (including back/forward navigation)
  $effect(() => {
    const tab = activeTab;
    requestSeq += 1;
    loadFirstPage(tab, requestSeq);
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
      {m.browser_showing({
        count: String(books.length),
        total: String(total),
      })}
    </p>
    <BookGrid {books} />
    {#if hasMore}
      <div class="flex justify-center mt-8">
        <button
          class="px-6 py-2.5 bg-secondary hover:bg-secondary/80 text-foreground font-medium rounded-xl transition-colors disabled:opacity-50"
          onclick={loadMore}
          disabled={loadingMore}
        >
          {#if loadingMore}
            <span class="flex items-center gap-2">
              <Spinner size="sm" color="foreground" />
              {m.common_loading()}
            </span>
          {:else}
            {m.browser_load_more()}
          {/if}
        </button>
      </div>
    {/if}
  {/if}
</div>
