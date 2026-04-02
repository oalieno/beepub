<script lang="ts">
  import { Search, X, ArrowUpDown, SlidersHorizontal } from "@lucide/svelte";
  import * as Select from "$lib/components/ui/select";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import type { BookOut, PaginatedBooks } from "$lib/types";
  import { toastStore } from "$lib/stores/toast";

  const SORT_OPTIONS = [
    { value: "added_at:desc", label: "Newest added" },
    { value: "added_at:asc", label: "Oldest added" },
    { value: "display_title:asc", label: "Title A → Z" },
    { value: "display_title:desc", label: "Title Z → A" },
    { value: "series_index:asc", label: "Series order ↑" },
    { value: "series_index:desc", label: "Series order ↓" },
  ] as const;

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
    emptyMessage = "No books found",
    onStateChange,
  }: {
    fetchBooks: FetchBooksFn;
    initialSearch?: string;
    initialTag?: string;
    initialAuthor?: string;
    initialSeries?: string;
    initialSort?: string;
    emptyMessage?: string;
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

  let books = $state<BookOut[]>([]);
  let totalBooks = $state(0);
  let hasMore = $derived(books.length < totalBooks);
  let loading = $state(true);
  let loadingMore = $state(false);
  // svelte-ignore state_referenced_locally
  let searchQuery = $state(initialSearch);
  // svelte-ignore state_referenced_locally
  let filterAuthor = $state(initialAuthor);
  // svelte-ignore state_referenced_locally
  let filterTag = $state(initialTag);
  // svelte-ignore state_referenced_locally
  let filterSeries = $state(initialSeries);

  // Auto-select series order when series filter is active
  // svelte-ignore state_referenced_locally
  let sortValue = $state(
    initialSeries && initialSort === "added_at:desc"
      ? "series_index:asc"
      : initialSort,
  );
  let sortBy = $derived(sortValue.split(":")[0]);
  let sortOrder = $derived(sortValue.split(":")[1]);
  let sortLabel = $derived(
    SORT_OPTIONS.find((o) => o.value === sortValue)?.label ?? "Newest added",
  );

  // Filter panel
  let showFilters = $state(false);
  // svelte-ignore state_referenced_locally
  let filterAuthorInput = $state(initialAuthor);
  // svelte-ignore state_referenced_locally
  let filterTagInput = $state(initialTag);
  // svelte-ignore state_referenced_locally
  let filterSeriesInput = $state(initialSeries);

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

  export function restoreState(state: BookBrowserState) {
    books = state.books;
    totalBooks = state.totalBooks;
    searchQuery = state.searchQuery;
    filterAuthor = state.filterAuthor;
    filterTag = state.filterTag;
    filterSeries = state.filterSeries;
    sortValue = state.sortValue;
    loading = false;
  }

  // Initial load
  loadData();
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
      placeholder="Search by title, author, or topic..."
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
      Filters
    </button>

    {#if filterAuthor}
      <button
        class="inline-flex items-center gap-1 h-8 text-xs px-3 rounded-full bg-primary/15 text-primary font-medium hover:bg-primary/25 transition-colors"
        onclick={() => clearFilter("author")}
      >
        Author: {filterAuthor}
        <X size={12} />
      </button>
    {/if}
    {#if filterSeries}
      <button
        class="inline-flex items-center gap-1 h-8 text-xs px-3 rounded-full bg-primary/15 text-primary font-medium hover:bg-primary/25 transition-colors"
        onclick={() => clearFilter("series")}
      >
        Series: {filterSeries}
        <X size={12} />
      </button>
    {/if}
    {#if filterTag}
      <button
        class="inline-flex items-center gap-1 h-8 text-xs px-3 rounded-full bg-primary/15 text-primary font-medium hover:bg-primary/25 transition-colors"
        onclick={() => clearFilter("tag")}
      >
        Tag: {filterTag}
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
          placeholder="Filter by author..."
          class="w-full bg-card card-soft rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
          onkeydown={(e) => e.key === "Enter" && applyFilterInput("author")}
        />
        {#if filterAuthorInput && filterAuthorInput !== filterAuthor}
          <button
            class="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-primary font-medium"
            onclick={() => applyFilterInput("author")}
          >
            Apply
          </button>
        {/if}
      </div>
      <div class="relative">
        <input
          type="text"
          bind:value={filterTagInput}
          placeholder="Filter by tag..."
          class="w-full bg-card card-soft rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
          onkeydown={(e) => e.key === "Enter" && applyFilterInput("tag")}
        />
        {#if filterTagInput && filterTagInput !== filterTag}
          <button
            class="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-primary font-medium"
            onclick={() => applyFilterInput("tag")}
          >
            Apply
          </button>
        {/if}
      </div>
      <div class="relative">
        <input
          type="text"
          bind:value={filterSeriesInput}
          placeholder="Filter by series..."
          class="w-full bg-card card-soft rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
          onkeydown={(e) => e.key === "Enter" && applyFilterInput("series")}
        />
        {#if filterSeriesInput && filterSeriesInput !== filterSeries}
          <button
            class="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-primary font-medium"
            onclick={() => applyFilterInput("series")}
          >
            Apply
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
    <p class="text-muted-foreground text-lg">{emptyMessage}</p>
  </div>
{:else}
  <p class="text-muted-foreground text-sm mb-4">
    Showing {books.length} of {totalBooks.toLocaleString()} books
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
            Loading...
          </span>
        {:else}
          Load more
        {/if}
      </button>
    </div>
  {/if}
{/if}
