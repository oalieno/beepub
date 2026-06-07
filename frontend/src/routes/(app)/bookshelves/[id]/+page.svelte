<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { bookshelvesApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import BookCard from "$lib/components/BookCard.svelte";
  import SeriesCard from "$lib/components/SeriesCard.svelte";
  import TierList from "$lib/components/TierList.svelte";
  import type { TierEntry } from "$lib/components/TierList.svelte";
  import { BookGridSkeleton } from "$lib/components/skeletons";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import * as Select from "$lib/components/ui/select";
  import { BookOpen, LayoutGrid, Layers, X } from "@lucide/svelte";
  import BackButton from "$lib/components/BackButton.svelte";
  import {
    TIER_PRESETS,
    DEFAULT_PRESET_KEY,
    bandsForKey,
    loadShelfThemeKey,
    saveShelfThemeKey,
  } from "$lib/tiers";
  import * as m from "$lib/paraglide/messages.js";
  import { getLocale } from "$lib/paraglide/runtime.js";
  import type {
    BookshelfOut,
    LibraryFeedItem,
    ReadingStatus,
  } from "$lib/types";

  let shelfId = $derived(page.params.id as string);

  let shelf = $state<BookshelfOut | null>(null);
  let items = $state<LibraryFeedItem[]>([]);
  // Reading status per book id, supplied inline by each book item.
  let interactions = $state<Record<string, ReadingStatus | null>>({});
  let loading = $state(true);

  let viewMode = $state<"grid" | "tier">("grid");
  // Tier theme is a client-only preference (per shelf, in localStorage).
  let themeKey = $state(DEFAULT_PRESET_KEY);

  // Placed units for the tier list: each item by its rating (null = unrated).
  let entries = $derived<TierEntry[]>(
    items.map((it) => ({
      rating: it.type === "series" ? it.series.rating : it.book.user_rating,
      item: it,
    })),
  );

  let activeBands = $derived(bandsForKey(themeKey));
  let selectedName = $derived(
    TIER_PRESETS.find((p) => p.key === themeKey)?.name ?? "",
  );
  // The 夯到拉 preset is only offered when the UI is in Chinese.
  let visiblePresets = $derived(
    TIER_PRESETS.filter((p) => !p.chineseOnly || getLocale().startsWith("zh")),
  );

  function itemKey(it: LibraryFeedItem) {
    return it.type === "series"
      ? `s:${it.series.library_id}:${it.series.series_key}`
      : `b:${it.book.id}`;
  }

  onMount(async () => {
    themeKey = loadShelfThemeKey(shelfId);
    await loadData();
  });

  async function loadData() {
    loading = true;
    try {
      const [s, list] = await Promise.all([
        bookshelvesApi.get(shelfId),
        bookshelvesApi.getItems(shelfId),
      ]);
      shelf = s;
      items = list;
      interactions = Object.fromEntries(
        list
          .filter((x) => x.type === "book")
          .map((x) => [x.book!.id, x.book!.reading_status ?? null]),
      );
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  function setTheme(key: string) {
    themeKey = key;
    saveShelfThemeKey(shelfId, key);
  }

  function handleStatusChange(bookId: string, status: ReadingStatus | null) {
    interactions[bookId] = status;
  }

  async function removeItem(target: LibraryFeedItem) {
    if (!confirm(m.bookshelf_remove_confirm())) return;
    const index = items.findIndex((x) => itemKey(x) === itemKey(target));
    if (index === -1) return;
    const removed = items[index];
    const prev = items;

    // Optimistically remove, then delete immediately (no delayed undo).
    items = items.filter((_, i) => i !== index);
    try {
      if (removed.type === "series") {
        await bookshelvesApi.removeSeries(
          shelfId,
          removed.series.series_key,
          removed.series.library_id,
        );
      } else {
        await bookshelvesApi.removeBook(shelfId, removed.book.id);
      }
      toastStore.success(
        removed.type === "series"
          ? m.bookshelf_series_removed()
          : m.bookshelf_removed(),
      );
    } catch (e) {
      toastStore.error((e as Error).message);
      items = prev;
    }
  }
</script>

<svelte:head>
  <title>{m.bookshelf_page_title({ name: shelf?.name ?? "Bookshelf" })}</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6">
  {#if loading}
    <div class="mb-8">
      <Skeleton class="h-4 w-20 mb-1" />
      <Skeleton class="h-9 w-48" />
    </div>
    <BookGridSkeleton count={12} />
  {:else if shelf}
    <div class="mb-6">
      <div class="mb-1">
        <BackButton href="/bookshelves" label={m.nav_shelves()} />
      </div>
      <h1 class="text-3xl font-bold text-foreground">{shelf.name}</h1>
      {#if shelf.description}
        <p class="text-muted-foreground mt-1">{shelf.description}</p>
      {/if}
    </div>

    {#if items.length === 0}
      <div class="flex flex-col items-center justify-center py-24 text-center">
        <div class="mb-4 p-3 bg-primary/10 rounded-xl">
          <BookOpen class="text-primary/50" size={28} />
        </div>
        <p class="text-foreground text-lg font-medium mb-2">
          {m.bookshelf_empty()}
        </p>
        <p class="text-muted-foreground text-sm max-w-xs">
          {m.bookshelf_empty_subtitle()}
        </p>
      </div>
    {:else}
      <!-- Toolbar: Grid | Tier toggle + (tier) theme picker -->
      <div class="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div class="inline-flex items-center gap-1 rounded-md bg-muted p-1">
          <button
            type="button"
            onclick={() => (viewMode = "grid")}
            aria-pressed={viewMode === "grid"}
            class="inline-flex items-center gap-1.5 rounded-sm px-3 py-1.5 text-sm font-medium transition-colors {viewMode ===
            'grid'
              ? 'bg-background text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'}"
          >
            <LayoutGrid size={15} />
            {m.bookshelf_view_grid()}
          </button>
          <button
            type="button"
            onclick={() => (viewMode = "tier")}
            aria-pressed={viewMode === "tier"}
            class="inline-flex items-center gap-1.5 rounded-sm px-3 py-1.5 text-sm font-medium transition-colors {viewMode ===
            'tier'
              ? 'bg-background text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'}"
          >
            <Layers size={15} />
            {m.bookshelf_view_tier()}
          </button>
        </div>

        {#if viewMode === "tier"}
          <Select.Root
            type="single"
            value={themeKey}
            onValueChange={(v) => v && setTheme(v)}
          >
            <Select.Trigger
              class="w-[150px] bg-background"
              aria-label={m.tier_theme_label()}
            >
              {selectedName}
            </Select.Trigger>
            <Select.Content align="end">
              {#each visiblePresets as preset}
                <Select.Item value={preset.key}>{preset.name}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        {/if}
      </div>

      {#if viewMode === "tier"}
        <TierList {entries} bands={activeBands} />
      {:else}
        <div
          class="grid gap-4 items-start"
          style="grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));"
        >
          {#each items as it (itemKey(it))}
            <div class="group/item relative">
              <button
                type="button"
                onclick={() => removeItem(it)}
                aria-label={m.bookshelf_remove()}
                class="absolute right-1.5 top-1.5 z-10 rounded-full bg-background/90 p-1 text-muted-foreground opacity-0 shadow-sm transition-opacity hover:text-foreground group-hover/item:opacity-100"
              >
                <X size={14} />
              </button>
              {#if it.type === "series"}
                <SeriesCard series={it.series} showRating={false} />
              {:else}
                <BookCard
                  book={it.book}
                  readingStatus={interactions[it.book.id] ?? null}
                  onStatusChange={handleStatusChange}
                />
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    {/if}
  {/if}
</div>
