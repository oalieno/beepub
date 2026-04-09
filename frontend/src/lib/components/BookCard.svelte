<script lang="ts">
  import { goto } from "$app/navigation";
  import type { BookOut, ReadingStatus } from "$lib/types";
  import {
    TriangleAlert,
    BookOpen,
    Bookmark,
    Check,
    Image,
    Layers,
  } from "@lucide/svelte";
  import { booksApi } from "$lib/api/books";
  import { coverUrl } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import * as m from "$lib/paraglide/messages.js";

  let {
    book,
    readingStatus = null,
    onStatusChange,
  }: {
    book: BookOut;
    readingStatus?: ReadingStatus | null;
    onStatusChange?: (bookId: string, status: ReadingStatus | null) => void;
  } = $props();

  let loading = $state(false);

  async function toggleWantToRead(e: MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    if (loading) return;

    const newStatus: ReadingStatus | null =
      readingStatus === "want_to_read" ? null : "want_to_read";

    loading = true;
    try {
      await booksApi.updateReadingStatus(book.id, {
        reading_status: newStatus,
      });
      onStatusChange?.(book.id, newStatus);
    } finally {
      loading = false;
    }
  }
</script>

<div
  role="button"
  tabindex="0"
  class="text-left w-full group cursor-pointer"
  style="-webkit-tap-highlight-color: transparent;"
  onclick={() => goto(`/books/${book.id}`)}
  onkeydown={(e) => e.key === "Enter" && goto(`/books/${book.id}`)}
>
  <!-- Cover -->
  <div
    class="aspect-[2/3] mb-3 flex items-end justify-center overflow-hidden rounded-sm"
  >
    <div
      class="relative inline-flex book-shadow-hover transition-all duration-300"
    >
      {#if book.cover_path}
        <img
          use:authedSrc={coverUrl(book.id)}
          alt="{book.display_title} cover"
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
            >{book.display_title ?? m.common_untitled()}</span
          >
        </div>
      {/if}

      <!-- Image book badge — top-left -->
      {#if book.is_image_book}
        <div
          class="absolute top-2 left-2 p-1 bg-secondary/80 backdrop-blur-sm rounded-full"
        >
          <Image size={13} class="text-muted-foreground" />
        </div>
      {/if}

      <!-- Issue report badge — top-left, below image badge -->
      {#if book.has_unresolved_reports}
        <div
          class="absolute left-2 p-1 bg-destructive/80 backdrop-blur-sm rounded-full"
          style:top={book.is_image_book ? "2.25rem" : "0.5rem"}
        >
          <TriangleAlert size={13} class="text-destructive-foreground" />
        </div>
      {/if}

      <!-- Editions count pill — bottom-left -->
      {#if book.edition_count && book.edition_count > 1}
        <div
          class="absolute bottom-2 left-2 bg-black/60 backdrop-blur-sm rounded-full text-[11px] px-1.5 py-0.5 text-white font-medium flex items-center gap-0.5"
        >
          <Layers size={10} />
          {book.edition_count}
        </div>
      {/if}

      <!-- Status overlay — anchored to cover image -->
      {#if onStatusChange}
        {#if readingStatus === "read"}
          <div class="absolute top-2 right-2 p-1 bg-primary rounded-full">
            <Check
              size={13}
              strokeWidth={3}
              class="drop-shadow-md text-white"
            />
          </div>
        {:else}
          <button
            class="absolute -top-2 right-0 p-1 transition-opacity duration-200
              {readingStatus === 'want_to_read'
              ? 'opacity-100'
              : 'opacity-60 can-hover:opacity-0 can-hover:group-hover:opacity-100'}"
            style="-webkit-tap-highlight-color: transparent; touch-action: manipulation;"
            onclick={toggleWantToRead}
            title={readingStatus === "want_to_read"
              ? "Remove from Want to Read"
              : "Add to Want to Read"}
          >
            <Bookmark
              size={26}
              strokeWidth={readingStatus === "want_to_read" ? 0 : 2}
              class="drop-shadow-md transition-colors {readingStatus ===
              'want_to_read'
                ? 'fill-primary text-primary'
                : 'fill-background/60 text-foreground/70'}"
            />
          </button>
        {/if}
      {/if}
    </div>
  </div>

  <!-- Info below cover — fixed height so grid rows align -->
  <div class="min-h-[3rem]">
    <h3
      class="font-medium text-sm line-clamp-2 leading-snug text-foreground group-hover:text-primary transition-colors"
    >
      {book.display_title ?? m.common_untitled()}
    </h3>
    <p class="text-muted-foreground text-xs mt-0.5 line-clamp-1">
      {(book.display_authors ?? []).join(", ") || "\u00A0"}
    </p>
    {#if book.display_series}
      <p
        class="text-muted-foreground/70 text-xs mt-0.5 flex items-baseline min-w-0"
      >
        <span class="truncate">{book.display_series}</span
        >{#if book.display_series_index != null}<span class="shrink-0"
            >&nbsp;[{book.display_series_index}]</span
          >{/if}
      </p>
    {/if}
  </div>
</div>
