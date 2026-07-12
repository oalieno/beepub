<script lang="ts">
  import { page } from "$app/state";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import BackButton from "$lib/components/BackButton.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import type { BookWithInteractionOut, ReadingStatus } from "$lib/types";
  import { BookOpen } from "@lucide/svelte";
  import { BookGridSkeleton } from "$lib/components/skeletons";
  import * as m from "$lib/paraglide/messages.js";

  type TabKey =
    | "currently_reading"
    | "want_to_read"
    | "read"
    | "did_not_finish"
    | "favorites";

  // System-shelf detail: the bookshelves page pins one card per reading
  // status (plus favorites) and links here with ?tab=.
  const shelfNames: Record<TabKey, () => string> = {
    currently_reading: m.mybooks_tab_reading,
    want_to_read: m.mybooks_tab_want_to_read,
    read: m.mybooks_tab_read,
    did_not_finish: m.mybooks_tab_did_not_finish,
    favorites: m.mybooks_tab_favorites,
  };

  const PAGE_SIZE = 60;

  let books = $state<BookWithInteractionOut[]>([]);
  let total = $state(0);
  let loading = $state(true);
  let loadingMore = $state(false);
  let requestSeq = 0;
  let hasMore = $derived(books.length < total);

  // Derive the active shelf from the URL so back/forward navigation works
  let urlTab = $derived(
    (page.url.searchParams.get("tab") as TabKey | null) ?? "currently_reading",
  );
  let activeTab = $derived(urlTab in shelfNames ? urlTab : "currently_reading");

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
</script>

<svelte:head>
  <title>{m.bookshelf_page_title({ name: shelfNames[activeTab]() })}</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6">
  <div class="mb-6">
    <div class="mb-1">
      <BackButton href="/bookshelves" label={m.nav_shelves()} />
    </div>
    <h1 class="text-3xl font-bold text-foreground">
      {shelfNames[activeTab]()}
    </h1>
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
      {m.browser_showing({ total: String(total) })}
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
