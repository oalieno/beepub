<script lang="ts">
  import { ChevronLeft, ChevronRight } from "@lucide/svelte";
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

  const categoryStyles: Record<string, string> = {
    genre: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
    mood: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300",
    topic:
      "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  };
</script>

<div class="flex-shrink-0 w-full md:w-64 order-first md:order-none">
  <div class="flex flex-col gap-4 text-sm">
    {#if book.display_series}
      {@const total = seriesNeighbors?.progress?.total_in_library ?? 0}
      {@const currentIdx = book.display_series_index}
      <div>
        <span class="text-muted-foreground block text-xs mb-0.5">Series</span>
        <div class="flex items-baseline gap-2">
          <button
            class="text-foreground font-medium hover:text-primary hover:underline transition-colors"
            onclick={() => onfilter("series", book.display_series!)}
          >
            {book.display_series}
          </button>
          {#if currentIdx != null}
            <span class="text-muted-foreground text-xs whitespace-nowrap">
              vol. {formatSeriesIndex(currentIdx)}{#if total > 0}{" "}of {total}{/if}
            </span>
          {/if}
        </div>
        {#if seriesNeighbors?.previous || seriesNeighbors?.next}
          <div class="flex items-center gap-1.5 mt-2">
            {#if seriesNeighbors?.previous}
              <a
                href="/books/{seriesNeighbors.previous.id}"
                class="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded-full text-muted-foreground hover:text-primary hover:bg-accent transition-colors"
                title={seriesNeighbors.previous.title ?? "Previous"}
              >
                <ChevronLeft class="w-3.5 h-3.5" />
              </a>
            {:else}
              <div class="w-6"></div>
            {/if}
            {#if currentIdx != null && total > 0}
              <div
                class="flex-1 h-1.5 rounded-full bg-secondary overflow-hidden"
              >
                <div
                  class="h-full rounded-full bg-primary transition-all"
                  style="width: {Math.min((currentIdx / total) * 100, 100)}%"
                ></div>
              </div>
            {:else}
              <div class="flex-1"></div>
            {/if}
            {#if seriesNeighbors?.next}
              <a
                href="/books/{seriesNeighbors.next.id}"
                class="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded-full text-muted-foreground hover:text-primary hover:bg-accent transition-colors"
                title={seriesNeighbors.next.title ?? "Next"}
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
    {#if book.publisher ?? book.epub_publisher}
      <div>
        <span class="text-muted-foreground block text-xs mb-0.5">Publisher</span
        >
        <span class="text-foreground font-medium"
          >{book.publisher ?? book.epub_publisher}</span
        >
      </div>
    {/if}
    {#if book.published_date ?? book.epub_published_date}
      <div>
        <span class="text-muted-foreground block text-xs mb-0.5">Published</span
        >
        <span class="text-foreground font-medium"
          >{book.published_date ?? book.epub_published_date}</span
        >
      </div>
    {/if}
    {#if book.epub_language}
      <div>
        <span class="text-muted-foreground block text-xs mb-0.5">Language</span>
        <span class="text-foreground font-medium">{book.epub_language}</span>
      </div>
    {/if}
    {#if book.epub_isbn}
      <div>
        <span class="text-muted-foreground block text-xs mb-0.5">ISBN</span>
        <span class="text-foreground font-medium">{book.epub_isbn}</span>
      </div>
    {/if}
    <div>
      <span class="text-muted-foreground block text-xs mb-0.5">File Size</span>
      <span class="text-foreground font-medium"
        >{book.file_size < 1_048_576
          ? (book.file_size / 1024).toFixed(1) + " KB"
          : (book.file_size / 1_048_576).toFixed(1) + " MB"}</span
      >
    </div>
    {#if book.word_count}
      <div>
        <span class="text-muted-foreground block text-xs mb-0.5"
          >Word Count</span
        >
        <span class="text-foreground font-medium"
          >{book.word_count.toLocaleString()}</span
        >
      </div>
    {/if}
    {#if (book.display_tags ?? []).length > 0}
      <div>
        <span class="text-muted-foreground block text-xs mb-1">Tags</span>
        <div class="flex flex-wrap gap-1.5">
          {#each book.display_tags ?? [] as tag}
            <button
              class="text-xs px-2 py-0.5 rounded-full bg-secondary text-foreground hover:bg-secondary/80 transition-colors"
              onclick={() => onfilter("tag", tag)}
            >
              {tag}
            </button>
          {/each}
        </div>
      </div>
    {/if}
    {#if (book.ai_tags ?? []).length > 0}
      <div>
        <span class="text-muted-foreground block text-xs mb-1">AI Tags</span>
        <div class="flex flex-wrap gap-1.5">
          {#each book.ai_tags ?? [] as aiTag}
            <button
              class="text-xs px-2 py-0.5 rounded-full transition-colors hover:opacity-80 {categoryStyles[
                aiTag.category
              ] ?? 'bg-secondary text-foreground'}"
              onclick={() => onfilter("tag", aiTag.tag)}
              title="{aiTag.category} · {Math.round(
                aiTag.confidence * 100,
              )}% confidence"
            >
              {aiTag.label}
            </button>
          {/each}
        </div>
      </div>
    {/if}
  </div>
</div>
