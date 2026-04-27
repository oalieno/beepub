<script lang="ts">
  import { Search, X, ArrowUpDown, SlidersHorizontal } from "@lucide/svelte";
  import * as Select from "$lib/components/ui/select";
  import * as m from "$lib/paraglide/messages.js";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { localizedTagLabel } from "$lib/tags";
  import type { BookOut, PaginatedBooks } from "$lib/types";
  import { toastStore } from "$lib/stores/toast";

  const SORT_OPTIONS = $derived([
    { value: "added_at:desc", label: m.browser_sort_newest() },
    { value: "added_at:asc", label: m.browser_sort_oldest() },
    { value: "display_title:asc", label: m.browser_sort_title_asc() },
    { value: "display_title:desc", label: m.browser_sort_title_desc() },
    { value: "series_index:asc", label: m.browser_sort_series_asc() },
    { value: "series_index:desc", label: m.browser_sort_series_desc() },
  ]);

  const PAGE_SIZE = 60;

  type FetchBooksFn = (params: {
    search?: string;
    author?: string;
    tag?: string;
    series?: string;
    sort?: string;
    order?: string;
    limit?: number;
    offset?: number;
  }) => Promise<PaginatedBooks>;

  let {
    fetchBooks,
    initialSearch = "",
    initialTag = "",
    initialAuthor = "",
    initialSeries = "",
    initialSort = "added_at:desc",
    emptyMessage = "",
    restoreData,
    onStateChange,
  }: {
    fetchBooks: FetchBooksFn;
    initialSearch?: string;
    initialTag?: string;
    initialAuthor?: string;
    initialSeries?: string;
    initialSort?: string;
    emptyMessage?: string;
    restoreData?: BookBrowserState | null;
    onStateChange?: (state: BookBrowserState) => void;
  } = $props();

  export interface BookBrowserState {
    books: BookOut[];
    totalBooks: number;
    searchQuery: string;
    filterAuthor: string;
    filterTag: string;
    filterSeries: string;
    sortValue: string;
  }

  // Compute all initial values once from restoreData or initial* props.
  // These props are intentionally captured once at creation time.
  // svelte-ignore state_referenced_locally
  const isRestoring = !!restoreData;
  // svelte-ignore state_referenced_locally
  const init: BookBrowserState = restoreData ?? {
    books: [],
    totalBooks: 0,
    searchQuery: initialSearch,
    filterAuthor: initialAuthor,
    filterTag: initialTag,
    filterSeries: initialSeries,
    sortValue:
      initialSeries && initialSort === "added_at:desc"
        ? "series_index:asc"
        : initialSort,
  };

  let books = $state<BookOut[]>(init.books);
  let totalBooks = $state(init.totalBooks);
  let hasMore = $derived(books.length < totalBooks);
  let loading = $state(!isRestoring);
  let loadingMore = $state(false);
  let searchQuery = $state(init.searchQuery);
  let filterAuthor = $state(init.filterAuthor);
  let filterTag = $state(init.filterTag);
  let filterSeries = $state(init.filterSeries);
  let sortValue = $state(init.sortValue);
  let sortBy = $derived(sortValue.split(":")[0]);
  let sortOrder = $derived(sortValue.split(":")[1]);
  let sortLabel = $derived(
    SORT_OPTIONS.find((o) => o.value === sortValue)?.label ??
      m.browser_sort_newest(),
  );

  // Filter panel
  let showFilters = $state(false);
  let filterAuthorInput = $state(init.filterAuthor);
  let filterTagInput = $state(init.filterTag);
  let filterSeriesInput = $state(init.filterSeries);

  // Debounce timer for search input
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  function notifyStateChange() {
    onStateChange?.({
      books,
      totalBooks,
      searchQuery,
      filterAuthor,
      filterTag,
      filterSeries,
      sortValue,
    });
  }

  async function loadData() {
    loading = true;
    try {
      const result = await fetchBooks({
        search: searchQuery || undefined,
        author: filterAuthor || undefined,
        tag: filterTag || undefined,
        series: filterSeries || undefined,
        sort: sortBy,
        order: sortOrder,
        limit: PAGE_SIZE,
        offset: 0,
      });
      books = result.items;
      totalBooks = result.total;
      notifyStateChange();
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function loadMore() {
    if (loadingMore || !hasMore) return;
    loadingMore = true;
    try {
      const result = await fetchBooks({
        search: searchQuery || undefined,
        author: filterAuthor || undefined,
        tag: filterTag || undefined,
        series: filterSeries || undefined,
        sort: sortBy,
        order: sortOrder,
        limit: PAGE_SIZE,
        offset: books.length,
      });
      books = [...books, ...result.items];
      totalBooks = result.total;
      notifyStateChange();
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loadingMore = false;
    }
  }

  function handleSearchInput() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      loadData();
      notifyStateChange();
    }, 300);
  }

  function handleImmediateChange() {
    loadData();
    notifyStateChange();
  }

  function applyFilterInput(type: "author" | "tag" | "series") {
    if (type === "author") filterAuthor = filterAuthorInput.trim();
    else if (type === "tag") filterTag = filterTagInput.trim();
    else filterSeries = filterSeriesInput.trim();
    handleImmediateChange();
  }

  function clearFilter(type: "author" | "tag" | "series") {
    if (type === "author") {
      filterAuthor = "";
      filterAuthorInput = "";
    } else if (type === "tag") {
      filterTag = "";
      filterTagInput = "";
    } else {
      filterSeries = "";
      filterSeriesInput = "";
    }
    handleImmediateChange();
  }

  // Expose state for parent snapshot/URL sync
  export function getState(): BookBrowserState {
    return {
      books,
      totalBooks,
      searchQuery,
      filterAuthor,
      filterTag,
      filterSeries,
      sortValue,
    };
  }

  // Initial load (skip if restoring from snapshot)
  if (!isRestoring) {
    loadData();
  }
</script>

<!-- Search & toolbar -->
<div class="mb-6 space-y-4">
  <!-- Search -->
  <div class="relative">
    <Search
      class="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground"
      size={16}
    />
    <input
      type="text"
      bind:value={searchQuery}
      oninput={handleSearchInput}
      placeholder={m.browser_search_placeholder()}
      class="w-full bg-card card-soft rounded-xl pl-10 pr-10 py-3 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
    />
    {#if searchQuery}
      <button
        class="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        onclick={() => {
          searchQuery = "";
          clearTimeout(searchTimer);
          handleImmediateChange();
        }}
      >
        <X size={16} />
      </button>
    {/if}
  </div>

  <!-- Sort & filters -->
  <div class="flex flex-wrap items-center gap-2">
    <Select.Root
      type="single"
      value={sortValue}
      onValueChange={(v) => {
        if (v) {
          sortValue = v;
          handleImmediateChange();
        }
      }}
    >
      <Select.Trigger
        class="!h-8 inline-flex items-center gap-1.5 text-xs px-2.5 rounded-full bg-secondary text-muted-foreground font-medium hover:bg-secondary/80 transition-colors border-none shadow-none"
      >
        <ArrowUpDown size={12} />
        {sortLabel}
      </Select.Trigger>
      <Select.Content>
        {#each SORT_OPTIONS as opt}
          <Select.Item value={opt.value}>{opt.label}</Select.Item>
        {/each}
      </Select.Content>
    </Select.Root>

    <button
      class="inline-flex items-center gap-1.5 h-8 text-xs px-2.5 rounded-full font-medium transition-colors {showFilters
        ? 'bg-primary/15 text-primary'
        : 'bg-secondary text-muted-foreground hover:bg-secondary/80'}"
      onclick={() => (showFilters = !showFilters)}
    >
      <SlidersHorizontal size={12} />
      {m.browser_filters()}
    </button>

    {#if filterAuthor}
      <button
        class="inline-flex items-center gap-1 h-8 text-xs px-3 rounded-full bg-primary/15 text-primary font-medium hover:bg-primary/25 transition-colors"
        onclick={() => clearFilter("author")}
      >
        {m.browser_filter_author({ author: filterAuthor })}
        <X size={12} />
      </button>
    {/if}
    {#if filterSeries}
      <button
        class="inline-flex items-center gap-1 h-8 text-xs px-3 rounded-full bg-primary/15 text-primary font-medium hover:bg-primary/25 transition-colors"
        onclick={() => clearFilter("series")}
      >
        {m.browser_filter_series({ series: filterSeries })}
        <X size={12} />
      </button>
    {/if}
    {#if filterTag}
      <button
        class="inline-flex items-center gap-1 h-8 text-xs px-3 rounded-full bg-primary/15 text-primary font-medium hover:bg-primary/25 transition-colors"
        onclick={() => clearFilter("tag")}
      >
        {m.browser_filter_tag({ tag: localizedTagLabel(filterTag) })}
        <X size={12} />
      </button>
    {/if}
  </div>

  <!-- Filter panel -->
  {#if showFilters}
    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
      <div class="relative">
        <input
          type="text"
          bind:value={filterAuthorInput}
          placeholder={m.browser_filter_author_placeholder()}
          class="w-full bg-card card-soft rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
          onkeydown={(e) => e.key === "Enter" && applyFilterInput("author")}
        />
        {#if filterAuthorInput && filterAuthorInput !== filterAuthor}
          <button
            class="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-primary font-medium"
            onclick={() => applyFilterInput("author")}
          >
            {m.browser_apply()}
          </button>
        {/if}
      </div>
      <div class="relative">
        <input
          type="text"
          bind:value={filterTagInput}
          placeholder={m.browser_filter_tag_placeholder()}
          class="w-full bg-card card-soft rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
          onkeydown={(e) => e.key === "Enter" && applyFilterInput("tag")}
        />
        {#if filterTagInput && filterTagInput !== filterTag}
          <button
            class="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-primary font-medium"
            onclick={() => applyFilterInput("tag")}
          >
            {m.browser_apply()}
          </button>
        {/if}
      </div>
      <div class="relative">
        <input
          type="text"
          bind:value={filterSeriesInput}
          placeholder={m.browser_filter_series_placeholder()}
          class="w-full bg-card card-soft rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
          onkeydown={(e) => e.key === "Enter" && applyFilterInput("series")}
        />
        {#if filterSeriesInput && filterSeriesInput !== filterSeries}
          <button
            class="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-primary font-medium"
            onclick={() => applyFilterInput("series")}
          >
            {m.browser_apply()}
          </button>
        {/if}
      </div>
    </div>
  {/if}
</div>

{#if loading}
  <div
    class="grid gap-4 items-start book-grid"
    style="grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));"
  >
    {#each Array(12) as _}
      <div class="animate-pulse">
        <div class="aspect-[2/3] bg-muted rounded-xl"></div>
        <div class="mt-2 h-3 bg-muted rounded w-3/4"></div>
        <div class="mt-1 h-2.5 bg-muted rounded w-1/2"></div>
      </div>
    {/each}
  </div>
{:else if books.length === 0}
  <div
    class="border-2 border-dashed border-border rounded-2xl p-12 text-center"
  >
    <p class="text-muted-foreground text-lg">
      {emptyMessage || m.browser_no_books()}
    </p>
  </div>
{:else}
  <p class="text-muted-foreground text-sm mb-4">
    {m.browser_showing({
      count: String(books.length),
      total: String(totalBooks),
    })}
  </p>
  <BookGrid {books} enableInteractions />
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
