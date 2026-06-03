<script lang="ts">
  import { goto } from "$app/navigation";
  import type { SeriesOut } from "$lib/types";
  import { BookOpen, Layers } from "@lucide/svelte";
  import { coverUrl } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import StarRating from "./StarRating.svelte";
  import * as m from "$lib/paraglide/messages.js";

  let {
    series,
    showRating = true,
  }: {
    series: SeriesOut;
    showRating?: boolean;
  } = $props();

  let cover = $derived(series.cover_book);

  function openDetail() {
    goto(`/series?name=${encodeURIComponent(series.series_name)}`);
  }
</script>

<div
  role="button"
  tabindex="0"
  class="text-left w-full group cursor-pointer"
  style="-webkit-tap-highlight-color: transparent;"
  onclick={openDetail}
  onkeydown={(e) => e.key === "Enter" && openDetail()}
>
  <!-- Cover -->
  <div
    class="aspect-[2/3] mb-3 flex items-end justify-center overflow-hidden rounded-sm"
  >
    <div
      class="relative inline-flex book-shadow-hover transition-all duration-300"
    >
      {#if cover?.cover_path}
        <img
          use:authedSrc={coverUrl(cover.id, cover.updated_at)}
          alt="{series.series_name} cover"
          class="w-full h-full object-cover rounded-sm book-shadow"
          loading="lazy"
        />
      {:else}
        <div
          class="w-full aspect-[2/3] bg-secondary rounded-sm flex flex-col items-center justify-center gap-2 p-4 book-shadow"
        >
          <BookOpen class="text-muted-foreground/30" size={36} />
          <span
            class="text-muted-foreground/60 text-xs text-center line-clamp-3"
            >{series.series_name}</span
          >
        </div>
      {/if}

      <!-- Volume count pill -->
      <div
        class="absolute bottom-2 left-2 bg-black/60 backdrop-blur-sm rounded-full text-[11px] px-1.5 py-0.5 text-white font-medium flex items-center gap-0.5"
      >
        <Layers size={10} />
        {series.book_count}
      </div>
    </div>
  </div>

  <!-- Info -->
  <div class="min-h-[3rem]">
    <h3
      class="font-medium text-sm line-clamp-2 leading-snug text-foreground group-hover:text-primary transition-colors"
    >
      {series.series_name}
    </h3>
    <p class="text-muted-foreground text-xs mt-0.5">
      {m.series_book_count({ count: String(series.book_count) })}
    </p>
    {#if showRating && series.effective_rating != null}
      <div class="mt-1">
        <StarRating value={series.effective_rating} size={16} readonly />
      </div>
    {/if}
  </div>
</div>
