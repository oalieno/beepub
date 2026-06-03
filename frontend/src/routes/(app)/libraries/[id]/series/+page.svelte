<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { librariesApi } from "$lib/api/libraries";
  import { toastStore } from "$lib/stores/toast";
  import SeriesCard from "$lib/components/SeriesCard.svelte";
  import LibraryViewToggle from "$lib/components/LibraryViewToggle.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { BookGridSkeleton } from "$lib/components/skeletons";
  import { Search, Layers, X, HardDrive } from "@lucide/svelte";
  import type { LibraryOut, SeriesOut } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";

  const PAGE_SIZE = 60;

  let libraryId = $derived(page.params.id as string);
  let library = $state<LibraryOut | null>(null);
  let isCalibre = $derived(!!library?.calibre_path);

  function clearSearch() {
    search = "";
    if (searchTimer) clearTimeout(searchTimer);
    requestSeq += 1;
    loadFirst(requestSeq);
  }

  let series = $state<SeriesOut[]>([]);
  let total = $state(0);
  let loading = $state(true);
  let loadingMore = $state(false);
  let search = $state("");
  let requestSeq = 0;
  let hasMore = $derived(series.length < total);
  let searchTimer: ReturnType<typeof setTimeout> | null = null;

  async function loadFirst(seq: number) {
    loading = true;
    try {
      const res = await librariesApi.getSeries(libraryId, {
        search: search.trim() || undefined,
        limit: PAGE_SIZE,
        offset: 0,
      });
      if (seq !== requestSeq) return;
      series = res.items;
      total = res.total;
    } catch (e) {
      if (seq === requestSeq) toastStore.error((e as Error).message);
    } finally {
      if (seq === requestSeq) loading = false;
    }
  }

  async function loadMore() {
    if (loading || loadingMore || !hasMore) return;
    const seq = requestSeq;
    loadingMore = true;
    try {
      const res = await librariesApi.getSeries(libraryId, {
        search: search.trim() || undefined,
        limit: PAGE_SIZE,
        offset: series.length,
      });
      if (seq !== requestSeq) return;
      series = [...series, ...res.items];
      total = res.total;
    } catch (e) {
      if (seq === requestSeq) toastStore.error((e as Error).message);
    } finally {
      if (seq === requestSeq) loadingMore = false;
    }
  }

  function onSearchInput() {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      requestSeq += 1;
      loadFirst(requestSeq);
    }, 300);
  }

  onMount(async () => {
    try {
      library = await librariesApi.get(libraryId);
    } catch {
      // title is non-critical
    }
    requestSeq += 1;
    await loadFirst(requestSeq);
  });
</script>

<svelte:head>
  <title>{m.library_page_title({ name: library?.name ?? "Library" })}</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6">
  <!-- Header (mirrors the library books page) -->
  <div
    class="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-8"
  >
    <div>
      <div class="flex items-center gap-2 mb-1">
        {#if isCalibre}
          <span
            class="text-xs px-2.5 py-1 rounded-full font-medium bg-amber-500/15 text-amber-600 flex items-center gap-1"
          >
            <HardDrive size={12} />
            {m.library_calibre_badge()}
          </span>
        {/if}
      </div>
      <h1 class="text-3xl font-bold text-foreground">{library?.name ?? ""}</h1>
      {#if library?.description}
        <p class="text-muted-foreground mt-1">{library.description}</p>
      {/if}
      <div class="mt-3">
        <LibraryViewToggle {libraryId} active="series" />
      </div>
    </div>
  </div>

  <!-- Search (mirrors the books browser) -->
  <div class="mb-6">
    <div class="relative">
      <Search
        class="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground"
        size={16}
      />
      <input
        type="text"
        bind:value={search}
        oninput={onSearchInput}
        placeholder={m.series_search_placeholder()}
        class="w-full bg-card card-soft rounded-xl pl-10 pr-10 py-3 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
      {#if search}
        <button
          class="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          onclick={clearSearch}
        >
          <X size={16} />
        </button>
      {/if}
    </div>
  </div>

  {#if loading}
    <BookGridSkeleton count={12} />
  {:else if series.length === 0}
    <div class="flex flex-col items-center justify-center py-24 text-center">
      <div class="mb-4 p-3 bg-primary/10 rounded-xl">
        <Layers class="text-primary/50" size={28} />
      </div>
      <p class="text-foreground text-lg font-medium mb-2">{m.series_empty()}</p>
    </div>
  {:else}
    <p class="text-sm text-muted-foreground mb-4">
      {m.series_count({ count: String(total) })}
    </p>
    <div
      class="grid gap-4 items-start"
      style="grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));"
    >
      {#each series as s (s.series_key)}
        <SeriesCard series={s} />
      {/each}
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
