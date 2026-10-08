<script lang="ts">
  import {
    Search,
    X,
    ArrowUpDown,
    SlidersHorizontal,
    Layers,
    BookOpen,
    BookX,
    LayoutGrid,
    List,
  } from "@lucide/svelte";
  import * as Select from "$lib/components/ui/select";
  import * as m from "$lib/paraglide/messages.js";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import BookTable from "$lib/components/BookTable.svelte";
  import BookCard from "$lib/components/BookCard.svelte";
  import SeriesCard from "$lib/components/SeriesCard.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { localizedTagLabel } from "$lib/tags";
  import type {
    BookWithInteractionOut,
    GroupedItem,
    PaginatedBooksWithInteraction,
    PaginatedGrouped,
  } from "$lib/types";
  import { toastStore } from "$lib/stores/toast";

  // "Most relevant" exists only while there is a query to be relevant to.
  const RELEVANCE = "relevance:asc";

  const PAGE_SIZE = 60;

  interface FetchParams {
    search?: string;
    author?: string;
    tag?: string;
    series?: string;
    format?: string;
    sort?: string;
    order?: string;
    limit?: number;
    offset?: number;
  }

  type FetchBooksFn = (
    params: FetchParams,
  ) => Promise<PaginatedBooksWithInteraction>;
  type FetchGroupedFn = (params: FetchParams) => Promise<PaginatedGrouped>;

  let {
    fetchBooks,
    fetchGrouped,
    collapsible = false,
    initialSearch = "",
    initialTag = "",
    initialAuthor = "",
    initialSeries = "",
    initialFormat = "",
    initialSort = "added_at:desc",
    initialCollapse = false,
    emptyMessage = "",
    searchPlaceholder = "",
    restoreData,
    onStateChange,
    searchEverywhereHref,
  }: {
    fetchBooks: FetchBooksFn;
    fetchGrouped?: FetchGroupedFn;
    collapsible?: boolean;
    initialSearch?: string;
    initialTag?: string;
    initialAuthor?: string;
    initialSeries?: string;
    initialFormat?: string;
    initialSort?: string;
    initialCollapse?: boolean;
    emptyMessage?: string;
    searchPlaceholder?: string;
    restoreData?: BookBrowserState | null;
    onStateChange?: (state: BookBrowserState) => void;
    // Where the same search runs over every library — given by a list that
    // is only one of them; an empty result then offers it.
    searchEverywhereHref?: (query: string) => string;
  } = $props();

  export interface BookBrowserState {
    books: BookWithInteractionOut[];
    // The grouped list's items. The key keeps its old name: this object is
    // the page snapshot SvelteKit stores in sessionStorage, and a snapshot
    // taken before the rename must still restore.
    feedItems: GroupedItem[];
    totalBooks: number;
    searchQuery: string;
    filterAuthor: string;
    filterTag: string;
    filterSeries: string;
    // Optional for snapshot compatibility (snapshots predating the field).
    filterFormat?: string;
    sortValue: string;
    collapse: boolean;
  }

  // Desktop-only table view (calibre-style, #70) — carries the metadata
  // the cover cards deliberately dropped. The preference persists per
  // browser; phones always render the grid.
  const VIEW_KEY = "library-view";
  let viewMode = $state<"grid" | "table">(
    typeof localStorage !== "undefined" &&
      localStorage.getItem(VIEW_KEY) === "table"
      ? "table"
      : "grid",
  );
  let isDesktop = $state(false);

  $effect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    isDesktop = mq.matches;
    const onChange = (e: MediaQueryListEvent) => (isDesktop = e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  });

  let tableView = $derived(viewMode === "table" && isDesktop);

  // Compute all initial values once from restoreData or initial* props.
  // These props are intentionally captured once at creation time.
  // svelte-ignore state_referenced_locally
  const isRestoring = !!restoreData;
  // svelte-ignore state_referenced_locally
  const init: BookBrowserState = restoreData ?? {
    books: [],
    feedItems: [],
    totalBooks: 0,
    searchQuery: initialSearch,
    filterAuthor: initialAuthor,
    filterTag: initialTag,
    filterSeries: initialSeries,
    filterFormat: initialFormat,
    // Arriving with a search already typed (the search window's Enter)
    // is starting a search: most relevant first, as when it is typed here.
    sortValue:
      initialSort !== "added_at:desc"
        ? initialSort
        : initialSeries
          ? "series_index:asc"
          : initialSearch.trim()
            ? RELEVANCE
            : initialSort,
    // The table is flat — series live in their own column.
    // svelte-ignore state_referenced_locally
    collapse: collapsible && initialCollapse && viewMode !== "table",
  };

  let books = $state<BookWithInteractionOut[]>(init.books);
  let groupedItems = $state<GroupedItem[]>(init.feedItems);
  let totalBooks = $state(init.totalBooks);
  let collapse = $state(init.collapse);
  let filterFormat = $state(init.filterFormat ?? "");
  // The grouped list groups by series; a format filter needs the flat list, so it
  // overrides collapse the same way the table view does.
  let flatForced = $derived(!!filterFormat);
  let shownCount = $derived(
    collapse && !flatForced ? groupedItems.length : books.length,
  );
  let hasMore = $derived(shownCount < totalBooks);

  // Series the grouped list holds more than once — the same name kept in
  // two libraries. Those cards say which library each is.
  let sharedSeriesKeys = $derived.by(() => {
    const seen = new Set<string>();
    const shared = new Set<string>();
    for (const item of groupedItems) {
      if (item.type !== "series") continue;
      const key = item.series.series_key;
      if (seen.has(key)) shared.add(key);
      seen.add(key);
    }
    return shared;
  });
  let loading = $state(!isRestoring);
  let loadingMore = $state(false);
  let searchQuery = $state(init.searchQuery);
  let filterAuthor = $state(init.filterAuthor);
  let filterTag = $state(init.filterTag);
  let filterSeries = $state(init.filterSeries);
  // Zero results means two different things: nothing matched the active
  // filters (search semantics, "not found") vs. the collection is
  // simply still empty (no failure at all).
  let hasActiveFilters = $derived(
    !!(
      searchQuery.trim() ||
      filterAuthor ||
      filterTag ||
      filterSeries ||
      filterFormat
    ),
  );
  let sortValue = $state(
    init.sortValue === RELEVANCE && !init.searchQuery.trim()
      ? "added_at:desc"
      : init.sortValue,
  );
  // Starting a search switches to relevance; clearing it goes back to
  // the order the user was browsing in (unless they picked another
  // order meanwhile — then that pick stands).
  let searching = !!init.searchQuery.trim();
  // svelte-ignore state_referenced_locally
  let sortBeforeSearch = sortValue === RELEVANCE ? "added_at:desc" : sortValue;

  function syncSortToSearch() {
    const active = !!searchQuery.trim();
    if (active && !searching && sortValue !== RELEVANCE) {
      sortBeforeSearch = sortValue;
      sortValue = RELEVANCE;
    } else if (!active && searching && sortValue === RELEVANCE) {
      sortValue = sortBeforeSearch;
    }
    searching = active;
  }
  let sortBy = $derived(sortValue.split(":")[0]);
  let sortOrder = $derived(sortValue.split(":")[1]);
  // series_index sort is meaningless once series collapse into one card, so it
  // is dropped from the menu while collapsed.
  const SORT_OPTIONS = $derived(
    [
      ...(searchQuery.trim()
        ? [{ value: RELEVANCE, label: m.browser_sort_relevance() }]
        : []),
      { value: "added_at:desc", label: m.browser_sort_newest() },
      { value: "added_at:asc", label: m.browser_sort_oldest() },
      { value: "display_title:asc", label: m.browser_sort_title_asc() },
      { value: "display_title:desc", label: m.browser_sort_title_desc() },
      { value: "series_index:asc", label: m.browser_sort_series_asc() },
      { value: "series_index:desc", label: m.browser_sort_series_desc() },
      {
        value: "popularity_score:desc",
        label: m.browser_sort_popularity_desc(),
      },
      { value: "popularity_score:asc", label: m.browser_sort_popularity_asc() },
    ].filter((o) => !(collapse && o.value.startsWith("series_index"))),
  );

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
      feedItems: groupedItems,
      totalBooks,
      searchQuery,
      filterAuthor,
      filterTag,
      filterSeries,
      filterFormat,
      sortValue,
      collapse,
    });
  }

  function queryParams(offset: number): FetchParams {
    return {
      search: searchQuery || undefined,
      author: filterAuthor || undefined,
      tag: filterTag || undefined,
      series: filterSeries || undefined,
      format: filterFormat || undefined,
      sort: sortBy,
      order: sortOrder,
      limit: PAGE_SIZE,
      offset,
    };
  }

  // Rapid filter/search changes keep several fetches in flight; only the
  // newest may write state. An older response finishing last would
  // otherwise clear `loading` early (flashing "no books" while the newer
  // fetch runs) or overwrite the newer results.
  let loadGen = 0;

  async function loadData() {
    const gen = ++loadGen;
    loading = true;
    try {
      if (collapse && !flatForced && fetchGrouped) {
        const result = await fetchGrouped(queryParams(0));
        if (gen !== loadGen) return;
        groupedItems = result.items;
        totalBooks = result.total;
      } else {
        const result = await fetchBooks(queryParams(0));
        if (gen !== loadGen) return;
        books = result.items;
        totalBooks = result.total;
      }
      notifyStateChange();
    } catch (e) {
      if (gen !== loadGen) return;
      toastStore.error((e as Error).message);
    } finally {
      if (gen === loadGen) loading = false;
    }
  }

  async function loadMore() {
    if (loadingMore || !hasMore) return;
    const gen = loadGen;
    loadingMore = true;
    try {
      if (collapse && !flatForced && fetchGrouped) {
        const result = await fetchGrouped(queryParams(groupedItems.length));
        if (gen !== loadGen) return;
        groupedItems = [...groupedItems, ...result.items];
        totalBooks = result.total;
      } else {
        const result = await fetchBooks(queryParams(books.length));
        if (gen !== loadGen) return;
        books = [...books, ...result.items];
        totalBooks = result.total;
      }
      notifyStateChange();
    } catch (e) {
      if (gen === loadGen) toastStore.error((e as Error).message);
    } finally {
      loadingMore = false;
    }
  }

  function toggleCollapse() {
    collapse = !collapse;
    // series_index ordering has no meaning collapsed; fall back to newest.
    if (collapse && sortValue.startsWith("series_index")) {
      sortValue = "added_at:desc";
    }
    handleImmediateChange();
  }

  function setViewMode(mode: "grid" | "table") {
    if (mode === viewMode) return;
    viewMode = mode;
    localStorage.setItem(VIEW_KEY, mode);
    if (mode === "table" && collapse) {
      collapse = false;
      handleImmediateChange();
    }
  }

  function handleSearchInput() {
    clearTimeout(searchTimer);
    syncSortToSearch();
    // Show the loading state right away. Otherwise, during the debounce
    // window (and a slow request), `loading` stays false while the old/empty
    // results render — briefly flashing "no books found" before the fetch.
    loading = true;
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

  function clearFilter(type: "author" | "tag" | "series" | "format") {
    if (type === "author") {
      filterAuthor = "";
      filterAuthorInput = "";
    } else if (type === "tag") {
      filterTag = "";
      filterTagInput = "";
    } else if (type === "format") {
      filterFormat = "";
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
      feedItems: groupedItems,
      totalBooks,
      searchQuery,
      filterAuthor,
      filterTag,
      filterSeries,
      sortValue,
      collapse,
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
      placeholder={searchPlaceholder || m.browser_search_all()}
      class="w-full bg-card card-soft rounded-xl pl-10 pr-10 py-3 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
    />
    {#if searchQuery}
      <button
        aria-label={m.common_clear()}
        class="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        onclick={() => {
          searchQuery = "";
          clearTimeout(searchTimer);
          syncSortToSearch();
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

    {#if collapsible && !tableView}
      <button
        class="inline-flex items-center gap-1.5 h-8 text-xs px-2.5 rounded-full font-medium transition-colors {collapse
          ? 'bg-primary/15 text-primary'
          : 'bg-secondary text-muted-foreground hover:bg-secondary/80'}"
        onclick={toggleCollapse}
        aria-pressed={collapse}
      >
        <Layers size={12} />
        {m.browser_collapse_series()}
      </button>
    {/if}

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
    {#if filterFormat}
      <button
        class="inline-flex items-center gap-1 h-8 text-xs px-3 rounded-full bg-primary/15 text-primary font-medium hover:bg-primary/25 transition-colors"
        onclick={() => clearFilter("format")}
      >
        {filterFormat === "physical"
          ? m.physical_badge()
          : ["txt", "mobi", "azw3", "cbz"].includes(filterFormat)
            ? m.converted_badge({ format: filterFormat.toUpperCase() })
            : filterFormat}
        <X size={12} />
      </button>
    {/if}

    <div class="ml-auto flex items-center gap-2">
      {#if !loading && shownCount > 0}
        <span class="shrink-0 text-xs text-muted-foreground">
          {m.browser_showing({ total: String(totalBooks) })}
        </span>
      {/if}
      <div
        class="hidden md:flex items-center rounded-full bg-secondary p-0.5"
        role="group"
        aria-label={m.browser_view_label()}
      >
        <button
          class="p-1.5 rounded-full transition-colors {viewMode === 'grid'
            ? 'bg-card text-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground'}"
          title={m.browser_view_grid()}
          aria-label={m.browser_view_grid()}
          aria-pressed={viewMode === "grid"}
          onclick={() => setViewMode("grid")}
        >
          <LayoutGrid size={14} />
        </button>
        <button
          class="p-1.5 rounded-full transition-colors {viewMode === 'table'
            ? 'bg-card text-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground'}"
          title={m.browser_view_table()}
          aria-label={m.browser_view_table()}
          aria-pressed={viewMode === "table"}
          onclick={() => setViewMode("table")}
        >
          <List size={14} />
        </button>
      </div>
    </div>
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
  {#if tableView}
    <div class="space-y-1.5">
      {#each Array(10) as _}
        <div class="h-14 bg-muted rounded-lg animate-pulse"></div>
      {/each}
    </div>
  {:else}
    <div
      class="grid gap-4 items-start book-grid"
      style="grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));"
    >
      {#each Array(12) as _}
        <div class="animate-pulse">
          <div class="aspect-[2/3] bg-muted rounded-xl"></div>
          <div class="mt-2 h-3 bg-muted rounded w-3/4"></div>
          <div class="mt-1 h-2.5 bg-muted rounded w-1/2"></div>
        </div>
      {/each}
    </div>
  {/if}
{:else if shownCount === 0}
  <div class="flex flex-col items-center justify-center text-center py-20">
    <div
      class="flex items-center justify-center w-14 h-14 rounded-full bg-muted mb-5"
    >
      {#if hasActiveFilters}
        <BookX size={24} strokeWidth={1.5} class="text-muted-foreground" />
      {:else}
        <BookOpen size={24} strokeWidth={1.5} class="text-muted-foreground" />
      {/if}
    </div>
    <p class="text-foreground text-lg font-medium">
      {hasActiveFilters
        ? m.browser_no_matches()
        : emptyMessage || m.browser_no_books()}
    </p>
    {#if searchEverywhereHref && searchQuery.trim()}
      <a
        class="mt-3 text-sm text-primary underline underline-offset-4 hover:opacity-80 transition-opacity"
        href={searchEverywhereHref(searchQuery.trim())}
        data-testid="search-everywhere"
      >
        {m.browser_search_everywhere()}
      </a>
    {/if}
  </div>
{:else}
  {#if tableView}
    <BookTable
      {books}
      {sortValue}
      onSort={(v) => {
        sortValue = v;
        handleImmediateChange();
      }}
    />
  {:else if collapse}
    <!-- One grid, mixing whole-series cards and standalone book cards -->
    <div
      class="grid gap-4 items-start book-grid"
      style="grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));"
    >
      {#each groupedItems as item (item.type === "series" ? `s:${item.series.library_id}:${item.series.series_key}` : `b:${item.book.id}`)}
        {#if item.type === "series"}
          <SeriesCard
            series={item.series}
            showLibrary={sharedSeriesKeys.has(item.series.series_key)}
          />
        {:else}
          <BookCard book={item.book} />
        {/if}
      {/each}
    </div>
  {:else}
    <BookGrid {books} />
  {/if}
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
