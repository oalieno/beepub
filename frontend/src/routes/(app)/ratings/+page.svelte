<script lang="ts">
  import { onMount } from "svelte";
  import { booksApi } from "$lib/api/books";
  import { seriesApi } from "$lib/api/series";
  import { authApi } from "$lib/api/auth";
  import { authStore } from "$lib/stores/auth";
  import { toastStore } from "$lib/stores/toast";
  import BookCard from "$lib/components/BookCard.svelte";
  import SeriesCard from "$lib/components/SeriesCard.svelte";
  import { BookGridSkeleton } from "$lib/components/skeletons";
  import * as Select from "$lib/components/ui/select";
  import { Star } from "@lucide/svelte";
  import {
    TIER_PRESETS,
    DEFAULT_PRESET_KEY,
    resolveBands,
    tierFor,
  } from "$lib/tiers";
  import type { BookWithInteractionOut, SeriesOut } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";
  import { getLocale } from "$lib/paraglide/runtime.js";

  const PAGE_SIZE = 100;

  // A tier entry is either a series (one unit, by effective rating) or a
  // standalone book (no series).
  type RatedItem =
    | { kind: "series"; series: SeriesOut; rating: number }
    | { kind: "book"; book: BookWithInteractionOut; rating: number };

  let items = $state<RatedItem[]>([]);
  let loading = $state(true);

  // Active tier bands come from the user's theme, or the default preset.
  let activeBands = $derived(resolveBands($authStore.user?.tier_theme));

  // Which preset is currently applied (for the Select trigger label).
  let selectedKey = $derived.by(() => {
    const theme = $authStore.user?.tier_theme;
    if (!theme || theme.length === 0) return DEFAULT_PRESET_KEY;
    const sig = theme.map((b) => b.label).join("|");
    const match = TIER_PRESETS.find(
      (p) => p.bands.map((b) => b.label).join("|") === sig,
    );
    return match?.key ?? DEFAULT_PRESET_KEY;
  });
  let selectedName = $derived(
    TIER_PRESETS.find((p) => p.key === selectedKey)?.name ?? "",
  );

  // The 夯到拉 preset is only offered when the UI is in Chinese.
  let visiblePresets = $derived(
    TIER_PRESETS.filter((p) => !p.chineseOnly || getLocale().startsWith("zh")),
  );

  // Items grouped into tier rows (highest band first), each sorted by rating.
  let grouped = $derived.by(() => {
    const bands = activeBands;
    const map = new Map(bands.map((b) => [b, [] as RatedItem[]]));
    for (const it of items) {
      const band = tierFor(it.rating, bands);
      if (band) map.get(band)?.push(it);
    }
    for (const arr of map.values()) {
      arr.sort((a, b) => b.rating - a.rating);
    }
    return bands.map((band) => ({ band, items: map.get(band) ?? [] }));
  });

  async function fetchAllRatedBooks(): Promise<BookWithInteractionOut[]> {
    const collected: BookWithInteractionOut[] = [];
    let offset = 0;
    for (;;) {
      const res = await booksApi.getAll({
        has_rating: true,
        limit: PAGE_SIZE,
        offset,
      });
      collected.push(...res.items);
      if (collected.length >= res.total || res.items.length === 0) break;
      offset += PAGE_SIZE;
    }
    return collected;
  }

  async function loadAll() {
    loading = true;
    try {
      const [seriesList, ratedBooks] = await Promise.all([
        seriesApi.listRated(),
        fetchAllRatedBooks(),
      ]);
      // Series as units (effective rating = explicit, else best volume).
      const seriesItems: RatedItem[] = seriesList
        .filter((s) => s.effective_rating != null)
        .map((s) => ({
          kind: "series" as const,
          series: s,
          rating: s.effective_rating as number,
        }));
      // Standalone rated books only — series books are covered by their series.
      const standalone: RatedItem[] = ratedBooks
        .filter((b) => !b.display_series && b.user_rating != null)
        .map((b) => ({
          kind: "book" as const,
          book: b,
          rating: b.user_rating as number,
        }));
      items = [...seriesItems, ...standalone];
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function applyTheme(key: string) {
    const preset = TIER_PRESETS.find((p) => p.key === key);
    if (!preset || !$authStore.user) return;
    try {
      const updated = await authApi.updateTierTheme(preset.bands);
      authStore.setUser(updated);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  onMount(loadAll);
</script>

<svelte:head>
  <title>{m.ratings_page_title()}</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6">
  <!-- Header: title + view toggle + theme picker -->
  <div class="flex flex-wrap items-center justify-between gap-3 mb-6">
    <div>
      <h1 class="text-2xl font-bold text-foreground">{m.ratings_heading()}</h1>
      {#if !loading && items.length > 0}
        <p class="text-sm text-muted-foreground mt-0.5">
          {m.ratings_count({ count: String(items.length) })}
        </p>
      {/if}
    </div>

    <div class="flex items-center gap-2">
      <!-- Theme picker -->
      <Select.Root
        type="single"
        value={selectedKey}
        onValueChange={(v) => v && applyTheme(v)}
      >
        <Select.Trigger
          class="w-[150px] bg-background"
          aria-label={m.ratings_theme()}
        >
          {selectedName}
        </Select.Trigger>
        <Select.Content align="end">
          {#each visiblePresets as preset}
            <Select.Item value={preset.key}>{preset.name}</Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
    </div>
  </div>

  {#if loading}
    <BookGridSkeleton count={12} />
  {:else if items.length === 0}
    <div class="flex flex-col items-center justify-center py-24 text-center">
      <div class="mb-4 p-3 bg-primary/10 rounded-xl">
        <Star class="text-primary/50" size={28} />
      </div>
      <p class="text-foreground text-lg font-medium mb-2">
        {m.ratings_empty()}
      </p>
      <p class="text-muted-foreground text-sm max-w-xs">
        {m.ratings_empty_hint()}
      </p>
    </div>
  {:else}
    <!-- Tier table -->
    <div class="flex flex-col gap-3">
      {#each grouped as row (row.band.label)}
        {#if row.items.length > 0}
          <div class="flex gap-3 items-stretch">
            <!-- Tier label cell -->
            <div
              class="shrink-0 w-16 sm:w-20 rounded-lg flex items-center justify-center px-1 py-3 font-bold text-center"
              style="background-color: {row.band.color};"
            >
              <span
                class="text-sm sm:text-base text-black/80 leading-tight break-words"
              >
                {row.band.label}
              </span>
            </div>
            <!-- Covers -->
            <div class="flex-1 min-w-0 rounded-lg bg-muted/40 p-3">
              <div class="tier-grid gap-4 items-start">
                {#each row.items as it (it.kind === "series" ? `s:${it.series.series_key}` : `b:${it.book.id}`)}
                  {#if it.kind === "series"}
                    <SeriesCard series={it.series} showRating={false} />
                  {:else}
                    <BookCard book={it.book} />
                  {/if}
                {/each}
              </div>
            </div>
          </div>
        {/if}
      {/each}
    </div>
  {/if}
</div>

<style>
  /* Denser cover grid inside tier rows */
  :global(.tier-grid) {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  }
</style>
