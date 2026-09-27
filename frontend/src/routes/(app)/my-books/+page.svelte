<script lang="ts">
  import { page } from "$app/state";
  import { scrollSnapshot } from "$lib/scrollSnapshot";
  import { booksApi } from "$lib/api/books";
  import { removedDownloads } from "$lib/services/downloadedBooks";
  import { linkedServerBookIds } from "$lib/stores/linkedBooks";
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
    | "favorites"
    | "downloaded";

  // System-shelf detail: the bookshelves page pins one card per reading
  // status (plus favorites) and links here with ?tab=.
  const shelfNames: Record<TabKey, () => string> = {
    currently_reading: m.mybooks_tab_reading,
    want_to_read: m.mybooks_tab_want_to_read,
    read: m.mybooks_tab_read,
    did_not_finish: m.mybooks_tab_did_not_finish,
    favorites: m.mybooks_tab_favorites,
    downloaded: m.mybooks_tab_downloaded,
  };

  const PAGE_SIZE = 60;

  let books = $state<BookWithInteractionOut[]>([]);
  let total = $state(0);
  let loading = $state(true);
  let loadingMore = $state(false);
  let requestSeq = 0;
  // The downloaded shelf's membership is the device's list of ids, paged
  // here through the server's book list; `cursor` counts ids consumed
  // (a book since removed from the server is skipped, not shown).
  let downloadedIds: string[] = [];
  let cursor = $state(0);

  async function fetchPage(
    tab: TabKey,
    offset: number,
  ): Promise<{ items: BookWithInteractionOut[]; total: number }> {
    if (tab !== "downloaded") {
      return booksApi.getMyBooks({
        ...getTabQuery(tab),
        limit: PAGE_SIZE,
        offset,
      });
    }
    if (offset === 0) {
      const { downloadedServerIds } =
        await import("$lib/services/downloadedBooks");
      downloadedIds = await downloadedServerIds();
    }
    const slice = downloadedIds.slice(cursor, cursor + PAGE_SIZE);
    const page = slice.length
      ? await booksApi.getAll({ ids: slice, limit: slice.length })
      : { items: [] as BookWithInteractionOut[] };
    const byId = new Map(page.items.map((b) => [b.id, b]));
    cursor += slice.length;
    return {
      items: slice.flatMap((id) => byId.get(id) ?? []),
      total: downloadedIds.length,
    };
  }

  // Derive the active shelf from the URL so back/forward navigation works
  let urlTab = $derived(
    (page.url.searchParams.get("tab") as TabKey | null) ?? "currently_reading",
  );
  let activeTab = $derived(urlTab in shelfNames ? urlTab : "currently_reading");
  // A copy removed elsewhere (its book page) leaves the Downloaded shelf
  // even when this page comes back from its snapshot. Downloaded again
  // since? Then it is linked again and stays.
  let gone = $derived(
    activeTab === "downloaded"
      ? books.filter(
          (b) => $removedDownloads.has(b.id) && !$linkedServerBookIds.has(b.id),
        ).length
      : 0,
  );
  let shown = $derived(
    gone === 0
      ? books
      : books.filter(
          (b) => !$removedDownloads.has(b.id) || $linkedServerBookIds.has(b.id),
        ),
  );
  let hasMore = $derived(
    activeTab === "downloaded"
      ? cursor < downloadedIds.length
      : books.length < total,
  );

  function getTabQuery(tab: Exclude<TabKey, "downloaded">) {
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
    cursor = 0;
    try {
      const result = await fetchPage(tab, 0);
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
      const result = await fetchPage(tab, books.length);
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

  // Back from a book: the list comes back as it was (every page loaded so
  // far, and the scroll position), without a refetch.
  let restoredTab: TabKey | null = null;
  export const snapshot = scrollSnapshot({
    capture: () => ({
      tab: activeTab,
      books,
      total,
      downloadedIds,
      cursor,
    }),
    restore: (d) => {
      requestSeq += 1;
      restoredTab = d.tab;
      books = d.books;
      total = d.total;
      downloadedIds = d.downloadedIds ?? [];
      cursor = d.cursor ?? 0;
      loading = false;
      loadingMore = false;
    },
  });

  // Load books whenever activeTab changes (including back/forward navigation)
  $effect(() => {
    const tab = activeTab;
    if (restoredTab === tab) {
      restoredTab = null;
      return;
    }
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
  {:else if shown.length === 0}
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
        {:else if activeTab === "downloaded"}
          {m.mybooks_empty_downloaded()}
        {:else}
          {m.mybooks_empty_default()}
        {/if}
      </p>
    </div>
  {:else}
    <p class="text-sm text-muted-foreground mb-4">
      {m.browser_showing({ total: String(total - gone) })}
    </p>
    <BookGrid books={shown} />
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
