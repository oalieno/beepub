<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import HighlightList from "$lib/components/HighlightList.svelte";
  import ShareHighlightModal from "$lib/components/ShareHighlightModal.svelte";
  import type { HighlightOut } from "$lib/types";
  import { Highlighter } from "@lucide/svelte";
  import { HighlightListSkeleton } from "$lib/components/skeletons";
  import * as m from "$lib/paraglide/messages.js";

  let highlights = $state<HighlightOut[]>([]);
  let bookData = $state<Record<string, { title: string; authors: string[] }>>(
    {},
  );
  let loading = $state(true);

  // Share modal state
  let shareHighlight = $state<HighlightOut | null>(null);
  let shareModalOpen = $state(false);

  // Undo delete state
  let pendingDeleteTimer: ReturnType<typeof setTimeout> | null = null;

  // Derived: book titles for HighlightList
  let bookTitles = $derived(() => {
    const titles: Record<string, string> = {};
    for (const [id, data] of Object.entries(bookData)) {
      titles[id] = data.title;
    }
    return titles;
  });

  // Group highlights by book_id
  let groupedHighlights = $derived(() => {
    const groups: Record<string, HighlightOut[]> = {};
    for (const hl of highlights) {
      if (!groups[hl.book_id]) groups[hl.book_id] = [];
      groups[hl.book_id].push(hl);
    }
    return groups;
  });

  onMount(async () => {
    try {
      highlights = await booksApi.getAllHighlights();

      // Fetch book data for all unique book IDs
      const bookIds = [...new Set(highlights.map((h) => h.book_id))];
      const data: Record<string, { title: string; authors: string[] }> = {};
      await Promise.all(
        bookIds.map(async (id) => {
          try {
            const book = await booksApi.get(id);
            data[id] = {
              title: book.display_title ?? book.epub_title ?? "Untitled",
              authors: book.display_authors ?? book.epub_authors ?? [],
            };
          } catch {
            data[id] = { title: m.common_untitled(), authors: [] };
          }
        }),
      );
      bookData = data;
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  });

  function handleDelete(hl: HighlightOut) {
    // Optimistically remove from UI
    highlights = highlights.filter((h) => h.id !== hl.id);

    if (pendingDeleteTimer) clearTimeout(pendingDeleteTimer);

    toastStore.info(m.highlights_removed(), {
      action: {
        label: m.highlights_undo(),
        onclick: () => {
          if (pendingDeleteTimer) clearTimeout(pendingDeleteTimer);
          pendingDeleteTimer = null;
          highlights = [...highlights, hl];
        },
      },
      duration: 5000,
    });

    pendingDeleteTimer = setTimeout(async () => {
      try {
        await booksApi.deleteHighlight(hl.book_id, hl.id);
      } catch (e) {
        toastStore.error((e as Error).message);
        highlights = [...highlights, hl];
      }
      pendingDeleteTimer = null;
    }, 5000);
  }

  function handleShare(hl: HighlightOut) {
    shareHighlight = hl;
    shareModalOpen = true;
  }
</script>

<svelte:head>
  <title>{m.highlights_page_title()}</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
  {#if loading}
    <HighlightListSkeleton groups={3} />
  {:else if highlights.length === 0}
    <div class="flex flex-col items-center justify-center py-24 text-center">
      <div class="mb-4 p-3 bg-primary/10 rounded-xl">
        <Highlighter class="text-primary/50" size={28} />
      </div>
      <p class="text-foreground text-lg font-medium mb-2">
        {m.highlights_no_highlights()}
      </p>
      <p class="text-muted-foreground text-sm max-w-xs">
        {m.highlights_empty_description()}
      </p>
    </div>
  {:else}
    {#each Object.entries(groupedHighlights()) as [bookId, bookHighlights] (bookId)}
      <div class="mb-6">
        <a
          href="/books/{bookId}"
          class="text-sm font-semibold text-foreground hover:text-primary transition-colors mb-2 block"
        >
          {bookTitles()[bookId] ?? m.common_untitled()}
        </a>
        <div class="bg-card card-soft rounded-2xl p-3">
          <HighlightList
            highlights={bookHighlights}
            onselect={(hl) => goto(`/books/${hl.book_id}/read`)}
            ondelete={handleDelete}
            onshare={handleShare}
          />
        </div>
      </div>
    {/each}
  {/if}
</div>

<ShareHighlightModal
  open={shareModalOpen}
  highlight={shareHighlight}
  bookTitle={shareHighlight
    ? (bookData[shareHighlight.book_id]?.title ?? "")
    : ""}
  bookAuthors={shareHighlight
    ? (bookData[shareHighlight.book_id]?.authors ?? [])
    : []}
  onclose={() => {
    shareModalOpen = false;
    shareHighlight = null;
  }}
/>
