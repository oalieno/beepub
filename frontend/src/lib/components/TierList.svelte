<script lang="ts" module>
  import type { LibraryFeedItem } from "$lib/types";

  // One placed unit: a book or a whole series, with the rating that decides
  // which tier it lands in (null = unrated).
  export interface TierEntry {
    rating: number | null;
    item: LibraryFeedItem;
  }
</script>

<script lang="ts">
  import type { TierBand } from "$lib/types";
  import { tierFor } from "$lib/tiers";
  import BookCard from "./BookCard.svelte";
  import SeriesCard from "./SeriesCard.svelte";
  import * as m from "$lib/paraglide/messages.js";

  let {
    entries,
    bands,
    showUnrated = true,
  }: {
    entries: TierEntry[];
    bands: TierBand[];
    showUnrated?: boolean;
  } = $props();

  // Group entries into tier rows (highest band first), each sorted by rating.
  // Unrated entries collect into a trailing bucket.
  let rows = $derived.by(() => {
    const map = new Map<TierBand, TierEntry[]>(bands.map((b) => [b, []]));
    const unrated: TierEntry[] = [];
    for (const e of entries) {
      if (e.rating == null) {
        unrated.push(e);
        continue;
      }
      const band = tierFor(e.rating, bands);
      if (band) map.get(band)?.push(e);
      else unrated.push(e);
    }
    for (const arr of map.values()) arr.sort((a, b) => b.rating! - a.rating!);
    const out = bands.map((band) => ({
      label: band.label,
      color: band.color,
      entries: map.get(band) ?? [],
    }));
    if (showUnrated && unrated.length > 0) {
      out.push({ label: m.tier_unrated(), color: "", entries: unrated });
    }
    return out;
  });

  function key(e: TierEntry) {
    return e.item.type === "series"
      ? `s:${e.item.series.series_key}`
      : `b:${e.item.book.id}`;
  }
</script>

<div class="flex flex-col gap-8">
  {#each rows as row (row.label)}
    {#if row.entries.length > 0}
      <section class="flex gap-4">
        <!-- Tier colour rail (muted neutral for the unrated bucket) -->
        <span
          class="shrink-0 w-1.5 rounded-full {row.color ? '' : 'bg-muted'}"
          style={row.color ? `background-color: ${row.color};` : ""}
        ></span>
        <div class="flex-1 min-w-0">
          <div class="flex items-baseline gap-3 mb-3">
            <h2 class="shrink-0 text-lg font-bold text-foreground leading-none">
              {row.label}
            </h2>
            <span class="h-px flex-1 bg-border"></span>
          </div>
          <div class="tier-grid gap-4 items-start">
            {#each row.entries as e (key(e))}
              {#if e.item.type === "series"}
                <SeriesCard series={e.item.series} showRating={false} />
              {:else}
                <BookCard book={e.item.book} />
              {/if}
            {/each}
          </div>
        </div>
      </section>
    {/if}
  {/each}
</div>

<style>
  /* Denser cover grid inside tier rows */
  .tier-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  }
</style>
