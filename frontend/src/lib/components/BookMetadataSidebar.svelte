<script lang="ts">
  import { ChevronLeft, ChevronRight } from "@lucide/svelte";
  import * as m from "$lib/paraglide/messages.js";
  import { localizedTagLabel } from "$lib/tags";
  import type { BookOut, SeriesNeighborsOut } from "$lib/types";

  let {
    book,
    seriesNeighbors,
    onfilter,
  }: {
    book: BookOut;
    seriesNeighbors: SeriesNeighborsOut | null;
    onfilter: (param: string, value: string) => void;
  } = $props();

  function formatSeriesIndex(idx: number | null | undefined): string {
    return idx == null ? "" : String(idx);
  }

  function seriesDisplayTotal(
    progress: SeriesNeighborsOut["progress"] | undefined,
  ): number | null {
    const total = progress?.max_series_index ?? progress?.total_in_library;
    return total == null || total <= 0 ? null : total;
  }

  function seriesProgressPercent(
    currentIdx: number | null | undefined,
    total: number | null,
  ): number | null {
    if (currentIdx == null || total == null || total <= 0) return null;
    return Math.min((currentIdx / total) * 100, 100);
  }

  type PopularityTier = {
    label: string;
    level: number;
    text: string;
    fill: string;
  };

  function popularityTier(
    score: number | null | undefined,
  ): PopularityTier | null {
    if (score == null || score <= 0) return null;
    if (score >= 80)
      return {
        label: m.popularity_tier_phenomenon(),
        level: 5,
        text: "text-rose-600 dark:text-rose-400",
        fill: "bg-rose-500",
      };
    if (score >= 60)
      return {
        label: m.popularity_tier_popular(),
        level: 4,
        text: "text-amber-600 dark:text-amber-400",
        fill: "bg-amber-500",
      };
    if (score >= 40)
      return {
        label: m.popularity_tier_known(),
        level: 3,
        text: "text-emerald-600 dark:text-emerald-400",
        fill: "bg-emerald-500",
      };
    if (score >= 20)
      return {
        label: m.popularity_tier_niche(),
        level: 2,
        text: "text-sky-600 dark:text-sky-400",
        fill: "bg-sky-500",
      };
    return {
      label: m.popularity_tier_obscure(),
      level: 1,
      text: "text-slate-500 dark:text-slate-400",
      fill: "bg-slate-400",
    };
  }

  const categoryStyles: Record<string, string> = {
    genre: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
    subgenre:
      "bg-cyan-100 text-cyan-800 dark:bg-cyan-900/30 dark:text-cyan-300",
    mood: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300",
    theme:
      "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
    trope: "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300",
  };
</script>

<div class="flex-shrink-0 w-full md:w-64 order-first md:order-none">
  <div class="flex flex-col gap-4 text-sm">
    {#if book.display_series}
      {@const total = seriesDisplayTotal(seriesNeighbors?.progress)}
      {@const currentIdx = book.display_series_index}
      {@const progressPercent = seriesProgressPercent(currentIdx, total)}
      <div>
        <span class="text-muted-foreground block text-xs mb-0.5"
          >{m.metadata_label_series()}</span
        >
        <div>
          <button
            class="text-foreground font-medium hover:text-primary hover:underline transition-colors text-left"
            onclick={() => onfilter("series", book.display_series!)}
          >
            {book.display_series}
          </button>
          {#if currentIdx != null}
            <span class="text-muted-foreground text-xs block mt-0.5">
              {#if total}{m.metadata_series_vol_of({
                  index: formatSeriesIndex(currentIdx),
                  total: formatSeriesIndex(total),
                })}{:else}{m.metadata_series_vol({
                  index: formatSeriesIndex(currentIdx),
                })}{/if}
            </span>
          {/if}
        </div>
        {#if seriesNeighbors?.previous || seriesNeighbors?.next}
          <div class="flex items-center gap-1.5 mt-2">
            {#if seriesNeighbors?.previous}
              <a
                href="/books/{seriesNeighbors.previous.id}"
                data-sveltekit-replacestate
                class="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded-full text-muted-foreground hover:text-primary hover:bg-accent transition-colors"
                title={seriesNeighbors.previous.title ?? m.metadata_previous()}
              >
                <ChevronLeft class="w-3.5 h-3.5" />
              </a>
            {:else}
              <div class="w-6"></div>
            {/if}
            {#if progressPercent != null}
              <div
                class="flex-1 h-1.5 rounded-full bg-secondary overflow-hidden"
              >
                <div
                  class="h-full rounded-full bg-primary transition-all"
                  style="width: {progressPercent}%"
                ></div>
              </div>
            {:else}
              <div class="flex-1"></div>
            {/if}
            {#if seriesNeighbors?.next}
              <a
                href="/books/{seriesNeighbors.next.id}"
                data-sveltekit-replacestate
                class="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded-full text-muted-foreground hover:text-primary hover:bg-accent transition-colors"
                title={seriesNeighbors.next.title ?? m.metadata_next()}
              >
                <ChevronRight class="w-3.5 h-3.5" />
              </a>
            {:else}
              <div class="w-6"></div>
            {/if}
          </div>
        {/if}
      </div>
    {/if}
    {#if book.library_names?.length > 0}
      <div>
        <span class="text-muted-foreground block text-xs mb-0.5"
          >{book.library_names.length === 1
            ? m.metadata_label_library()
            : m.metadata_label_libraries()}</span
        >
        <div class="flex flex-wrap gap-1.5">
          {#each book.library_names as name}
            <span class="text-foreground font-medium">{name}</span>
          {/each}
        </div>
      </div>
    {/if}
    {#if popularityTier(book.popularity_score)}
      {@const pop = popularityTier(book.popularity_score)!}
      <div>
        <span class="text-muted-foreground block text-xs mb-1"
          >{m.metadata_label_popularity()}</span
        >
        <div class="flex items-baseline justify-between gap-2 mb-1.5">
          <span class="font-medium {pop.text}">{pop.label}</span>
          <span class="text-muted-foreground text-xs tabular-nums"
            >{book.popularity_score}<span class="opacity-50"> / 100</span></span
          >
        </div>
        <div class="flex items-center gap-1">
          {#each [1, 2, 3, 4, 5] as step (step)}
            <div
              class="h-1.5 flex-1 rounded-full {step <= pop.level
                ? pop.fill
                : 'bg-secondary'}"
            ></div>
          {/each}
        </div>
      </div>
    {/if}
    {#if book.publisher ?? book.epub_publisher}
      <div>
        <span class="text-muted-foreground block text-xs mb-0.5"
          >{m.metadata_label_publisher()}</span
        >
        <span class="text-foreground font-medium"
          >{book.publisher ?? book.epub_publisher}</span
        >
      </div>
    {/if}
    {#if book.published_date ?? book.epub_published_date}
      <div>
        <span class="text-muted-foreground block text-xs mb-0.5"
          >{m.metadata_label_published()}</span
        >
        <span class="text-foreground font-medium"
          >{book.published_date ?? book.epub_published_date}</span
        >
      </div>
    {/if}
    {#if book.epub_language}
      <div>
        <span class="text-muted-foreground block text-xs mb-0.5"
          >{m.metadata_label_language()}</span
        >
        <span class="text-foreground font-medium">{book.epub_language}</span>
      </div>
    {/if}
    {#if book.epub_isbn}
      <div>
        <span class="text-muted-foreground block text-xs mb-0.5"
          >{m.metadata_label_isbn()}</span
        >
        <span class="text-foreground font-medium">{book.epub_isbn}</span>
      </div>
    {/if}
    <div>
      <span class="text-muted-foreground block text-xs mb-0.5"
        >{m.metadata_label_file_size()}</span
      >
      <span class="text-foreground font-medium"
        >{book.file_size < 1_048_576
          ? (book.file_size / 1024).toFixed(1) + " KB"
          : (book.file_size / 1_048_576).toFixed(1) + " MB"}</span
      >
    </div>
    {#if book.word_count}
      <div>
        <span class="text-muted-foreground block text-xs mb-0.5"
          >{m.metadata_label_word_count()}</span
        >
        <span class="text-foreground font-medium"
          >{book.word_count.toLocaleString()}</span
        >
      </div>
    {/if}
    {#if (book.book_tags ?? []).length > 0}
      <div>
        <span class="text-muted-foreground block text-xs mb-1"
          >{m.metadata_label_tags()}</span
        >
        <div class="flex flex-wrap gap-1.5">
          {#each book.book_tags ?? [] as bookTag}
            <button
              class="text-xs px-2 py-0.5 rounded-full transition-colors hover:opacity-80 {categoryStyles[
                bookTag.category
              ] ?? 'bg-secondary text-foreground'}"
              onclick={() => onfilter("tag", bookTag.tag)}
              title="{bookTag.category} · {Math.round(
                bookTag.confidence * 100,
              )}%"
            >
              {localizedTagLabel(bookTag.tag, bookTag.label)}
            </button>
          {/each}
        </div>
      </div>
    {/if}
  </div>
</div>
