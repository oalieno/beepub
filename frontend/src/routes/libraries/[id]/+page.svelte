<script lang="ts">
  import { tick } from "svelte";
  import { page } from "$app/state";
  import { replaceState, afterNavigate } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { librariesApi } from "$lib/api/libraries";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import Modal from "$lib/components/Modal.svelte";
  import type { LibraryOut, BookOut } from "$lib/types";
  import { UserRole } from "$lib/types";
  import { Upload, Search, X, HardDrive, ArrowUpDown } from "@lucide/svelte";
  import * as Select from "$lib/components/ui/select";
  import Spinner from "$lib/components/Spinner.svelte";
  import { LibraryDetailSkeleton } from "$lib/components/skeletons";
  import type { Snapshot } from "./$types";

  const SORT_OPTIONS = [
    { value: "added_at:desc", label: "Newest added" },
    { value: "added_at:asc", label: "Oldest added" },
    { value: "display_title:asc", label: "Title A \u2192 Z" },
    { value: "display_title:desc", label: "Title Z \u2192 A" },
    { value: "series_index:asc", label: "Series order \u2191" },
    { value: "series_index:desc", label: "Series order \u2193" },
  ] as const;

  const PAGE_SIZE = 60;

  let libraryId = $derived(page.params.id as string);

  let library = $state<LibraryOut | null>(null);
  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);
  let isCalibre = $derived(!!library?.calibre_path);
  let canUpload = $derived(isAdmin && !isCalibre);
  let books = $state<BookOut[]>([]);
  let totalBooks = $state(0);
  let hasMore = $derived(books.length < totalBooks);
  let loading = $state(true);
  let loadingMore = $state(false);
  let searchQuery = $state((page.url.searchParams.get("search") ?? "").trim());
  let filterAuthor = $state((page.url.searchParams.get("author") ?? "").trim());
  let filterTag = $state((page.url.searchParams.get("tag") ?? "").trim());
  let filterSeries = $state((page.url.searchParams.get("series") ?? "").trim());
  let sortValue = $state(page.url.searchParams.get("sort") || "added_at:desc");
  let sortBy = $derived(sortValue.split(":")[0]);
  let sortOrder = $derived(sortValue.split(":")[1]);
  let sortLabel = $derived(
    SORT_OPTIONS.find((o) => o.value === sortValue)?.label ?? "Newest added",
  );
  let uploading = $state(false);
  let fileInput: HTMLInputElement;
  let showUploadModal = $state(false);
  let dragOver = $state(false);
  let restoredFromSnapshot = $state(false);
  let pendingScrollY = $state(0);

  interface PageSnapshot {
    books: BookOut[];
    totalBooks: number;
    library: LibraryOut | null;
    scrollY: number;
    searchQuery: string;
    filterAuthor: string;
    filterTag: string;
    filterSeries: string;
    sortValue: string;
  }

  export const snapshot: Snapshot<PageSnapshot> = {
    capture: () => ({
      books,
      totalBooks,
      library,
      scrollY: window.scrollY,
      searchQuery,
      filterAuthor,
      filterTag,
      filterSeries,
      sortValue,
    }),
    restore: (data) => {
      books = data.books;
      totalBooks = data.totalBooks;
      library = data.library;
      searchQuery = data.searchQuery;
      filterAuthor = data.filterAuthor;
      filterTag = data.filterTag;
      filterSeries = data.filterSeries;
      sortValue = data.sortValue;
      pendingScrollY = data.scrollY;
      restoredFromSnapshot = true;
    },
  };

  afterNavigate(async () => {
    if (restoredFromSnapshot) {
      restoredFromSnapshot = false;
      loading = false;
      await tick();
      window.scrollTo(0, pendingScrollY);
      return;
    }

    const params = new URLSearchParams(window.location.search);
    const search = (params.get("search") ?? "").trim();
    const author = (params.get("author") ?? "").trim();
    const tag = (params.get("tag") ?? "").trim();
    const series = (params.get("series") ?? "").trim();
    const sort = params.get("sort") || "added_at:desc";
    searchQuery = search;
    filterAuthor = author;
    filterTag = tag;
    filterSeries = series;
    // Auto-select series order when series filter is active
    const effectiveSort =
      series && sort === "added_at:desc" ? "series_index:asc" : sort;
    sortValue = effectiveSort;
    const [s, o] = effectiveSort.split(":");
    loadData(search, s, o);
  });

  async function loadData(
    search = searchQuery,
    sort = sortBy,
    order = sortOrder,
  ) {
    loading = true;
    try {
      const [lib, result] = await Promise.all([
        librariesApi.get(libraryId),
        librariesApi.getBooks(libraryId, {
          search: search || undefined,
          author: filterAuthor || undefined,
          tag: filterTag || undefined,
          series: filterSeries || undefined,
          sort,
          order,
          limit: PAGE_SIZE,
          offset: 0,
        }),
      ]);
      library = lib;
      books = result.items;
      totalBooks = result.total;
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
      const result = await librariesApi.getBooks(libraryId, {
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
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loadingMore = false;
    }
  }

  function syncUrlParams() {
    const url = new URL(page.url);
    if (searchQuery) url.searchParams.set("search", searchQuery);
    else url.searchParams.delete("search");
    if (filterAuthor) url.searchParams.set("author", filterAuthor);
    else url.searchParams.delete("author");
    if (filterTag) url.searchParams.set("tag", filterTag);
    else url.searchParams.delete("tag");
    if (filterSeries) url.searchParams.set("series", filterSeries);
    else url.searchParams.delete("series");
    if (sortValue !== "added_at:desc") url.searchParams.set("sort", sortValue);
    else url.searchParams.delete("sort");
    replaceState(url, {});
  }

  function clearFilter(type: "author" | "tag" | "series") {
    if (type === "author") filterAuthor = "";
    else if (type === "tag") filterTag = "";
    else filterSeries = "";
    syncUrlParams();
    loadData(searchQuery, sortBy, sortOrder);
  }

  async function handleSearch() {
    syncUrlParams();
    try {
      const result = await librariesApi.getBooks(libraryId, {
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
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleUpload(files: FileList | null) {
    if (!files || files.length === 0) return;
    uploading = true;
    let successCount = 0;
    for (const file of Array.from(files)) {
      try {
        await booksApi.upload(file, libraryId);
        successCount++;
      } catch (e) {
        toastStore.error(
          `Failed to upload ${file.name}: ${(e as Error).message}`,
        );
      }
    }
    if (successCount > 0) {
      toastStore.success(`Uploaded ${successCount} book(s)`);
      await loadData();
    }
    uploading = false;
    showUploadModal = false;
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    dragOver = false;
    handleUpload(e.dataTransfer?.files ?? null);
  }
</script>

<svelte:head>
  <title>{library?.name ?? "Library"} - BeePub</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
  {#if loading}
    <LibraryDetailSkeleton />
  {:else if library}
    <div
      class="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-8"
    >
      <div>
        <div class="flex items-center gap-2 mb-1">
          <span
            class="text-xs px-2.5 py-1 rounded-full font-medium {library.visibility ===
            'public'
              ? 'bg-primary/15 text-primary'
              : 'bg-secondary text-muted-foreground'}"
          >
            {library.visibility}
          </span>
          {#if isCalibre}
            <span
              class="text-xs px-2.5 py-1 rounded-full font-medium bg-amber-500/15 text-amber-600 flex items-center gap-1"
            >
              <HardDrive size={12} />
              Calibre
            </span>
          {/if}
        </div>
        <h1 class="text-3xl font-bold text-foreground">{library.name}</h1>
        {#if library.description}
          <p class="text-muted-foreground mt-1">{library.description}</p>
        {/if}
      </div>
      {#if canUpload}
        <button
          class="flex items-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-medium px-5 py-2.5 rounded-xl transition-colors"
          onclick={() => (showUploadModal = true)}
        >
          <Upload size={16} />
          Upload Books
        </button>
      {/if}
    </div>

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
          oninput={handleSearch}
          placeholder="Search by title, author, or topic..."
          class="w-full bg-card card-soft rounded-xl pl-10 pr-10 py-3 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
        {#if searchQuery}
          <button
            class="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            onclick={() => {
              searchQuery = "";
              handleSearch();
            }}
          >
            <X size={16} />
          </button>
        {/if}
      </div>

      <!-- Filters & sort -->
      <div class="flex flex-wrap items-center gap-2">
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

        <div class="ml-auto">
          <Select.Root
            type="single"
            value={sortValue}
            onValueChange={(v) => {
              if (v) {
                sortValue = v;
                handleSearch();
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
        </div>
      </div>
    </div>

    {#if books.length === 0 && !loading}
      <div
        class="border-2 border-dashed rounded-2xl p-12 text-center transition-colors {dragOver
          ? 'border-primary bg-primary/5'
          : 'border-border'}"
        ondragover={canUpload
          ? (e) => {
              e.preventDefault();
              dragOver = true;
            }
          : undefined}
        ondragleave={canUpload ? () => (dragOver = false) : undefined}
        ondrop={canUpload ? onDrop : undefined}
        role="region"
        aria-label="Drop zone"
      >
        <Upload class="mx-auto text-muted-foreground/30 mb-4" size={48} />
        <p class="text-muted-foreground text-lg">No books yet</p>
        <p class="text-muted-foreground/70 text-sm mt-1">
          {#if isCalibre}
            Sync from Calibre to add books.
          {:else if isAdmin}
            Upload EPUBs or drag and drop here.
          {:else}
            No books in this library.
          {/if}
        </p>
      </div>
    {:else if books.length > 0}
      <p class="text-muted-foreground text-sm mb-4">
        Showing {books.length} of {totalBooks.toLocaleString()} books
      </p>
      <div
        ondragover={canUpload
          ? (e) => {
              e.preventDefault();
              dragOver = true;
            }
          : undefined}
        ondragleave={canUpload ? () => (dragOver = false) : undefined}
        ondrop={canUpload ? onDrop : undefined}
        role="region"
        aria-label="Books"
      >
        <BookGrid {books} enableInteractions />
      </div>
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
  {/if}
</div>

<Modal
  title="Upload Books"
  open={showUploadModal}
  onclose={() => (showUploadModal = false)}
>
  <div class="space-y-4">
    <div
      class="border-2 border-dashed border-border rounded-2xl p-10 text-center cursor-pointer hover:border-primary/50 hover:bg-primary/5 transition-colors"
      onclick={() => fileInput?.click()}
      ondragover={(e) => e.preventDefault()}
      ondrop={(e) => {
        e.preventDefault();
        handleUpload(e.dataTransfer?.files ?? null);
      }}
      role="button"
      tabindex="0"
      onkeydown={(e) => e.key === "Enter" && fileInput?.click()}
    >
      <Upload class="mx-auto text-muted-foreground/40 mb-3" size={36} />
      <p class="text-foreground font-medium">Click or drag files</p>
      <p class="text-muted-foreground text-sm mt-1">EPUB format supported</p>
      <input
        bind:this={fileInput}
        type="file"
        accept=".epub"
        multiple
        class="hidden"
        onchange={(e) => handleUpload(e.currentTarget.files)}
      />
    </div>
    {#if uploading}
      <div class="flex items-center gap-2 text-primary text-sm">
        <Spinner size="sm" />
        Uploading...
      </div>
    {/if}
  </div>
</Modal>
