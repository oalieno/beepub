<script lang="ts">
  import { goto } from "$app/navigation";
  import type { BookOut, ReadingStatus } from "$lib/types";
  import { BookOpen, Bookmark } from "@lucide/svelte";
  import { booksApi } from "$lib/api/books";
  import { authStore } from "$lib/stores/auth";

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

    const token = $authStore.token;
    if (!token) return;

    const newStatus: ReadingStatus | null =
      readingStatus === "want_to_read" ? null : "want_to_read";

    loading = true;
    try {
      await booksApi.updateReadingStatus(
        book.id,
        { reading_status: newStatus },
        token,
      );
      onStatusChange?.(book.id, newStatus);
    } finally {
      loading = false;
    }
  }
</script>

<button
  class="text-left w-full group"
  style="-webkit-tap-highlight-color: transparent;"
  onclick={() => goto(`/books/${book.id}`)}
>
  <!-- Cover -->
  <div class="h-56 sm:h-64 mb-3 flex items-end justify-center">
    <div class="relative inline-flex">
      {#if book.cover_path}
        <img
          src="/covers/{book.id}.jpg"
          alt="{book.display_title} cover"
          class="max-h-56 sm:max-h-64 w-auto max-w-full rounded-sm book-shadow book-shadow-hover transition-all duration-300"
          loading="lazy"
        />
      {:else}
        <div
          class="h-56 sm:h-64 aspect-[2/3] bg-secondary rounded-sm flex flex-col items-center justify-center gap-2 p-4 book-shadow"
        >
          <BookOpen class="text-muted-foreground/30" size={36} />
          <span class="text-muted-foreground/60 text-xs text-center line-clamp-3"
            >{book.display_title ?? "Untitled"}</span
          >
        </div>
      {/if}

      <!-- Bookmark overlay — anchored to cover image -->
      {#if onStatusChange}
        <button
          class="absolute -top-1 -right-1 p-1 transition-opacity duration-200
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
    </div>
  </div>

  <!-- Info below cover — fixed height so grid rows align -->
  <div class="min-h-[3rem]">
    <h3
      class="font-medium text-sm line-clamp-2 leading-snug text-foreground group-hover:text-primary transition-colors"
    >
      {book.display_title ?? "Untitled"}
    </h3>
    <p class="text-muted-foreground text-xs mt-0.5 line-clamp-1">
      {(book.display_authors ?? []).join(", ") || "\u00A0"}
    </p>
  </div>
</button>
