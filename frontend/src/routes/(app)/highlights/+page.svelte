<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import { confirmDialog } from "$lib/stores/confirm";
  import ShareHighlightModal from "$lib/components/ShareHighlightModal.svelte";
  import type { HighlightOut } from "$lib/types";
  import { Highlighter, Share2, Trash2 } from "@lucide/svelte";
  import { HighlightListSkeleton } from "$lib/components/skeletons";
  import { getLocale } from "$lib/paraglide/runtime.js";
  import * as m from "$lib/paraglide/messages.js";

  function formatDate(iso: string): string {
    try {
      return new Date(iso).toLocaleDateString(getLocale(), {
        month: "short",
        day: "numeric",
      });
    } catch {
      return "";
    }
  }

  let highlights = $state<HighlightOut[]>([]);
  let bookData = $state<Record<string, { title: string; authors: string[] }>>(
    {},
  );
  let loading = $state(true);
  let total = $state(0);
  let loadingMore = $state(false);
  const PAGE_SIZE = 200;

  // Share modal state
  let shareHighlight = $state<HighlightOut | null>(null);
  let shareModalOpen = $state(false);

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

  async function fetchBookData(items: HighlightOut[]) {
    const bookIds = [
      ...new Set(items.map((h) => h.book_id).filter((id) => !(id in bookData))),
    ];
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
    bookData = { ...bookData, ...data };
  }

  onMount(async () => {
    try {
      const page = await booksApi.getAllHighlights(PAGE_SIZE, 0);
      highlights = page.items;
      total = page.total;
      await fetchBookData(page.items);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  });

  async function loadMore() {
    loadingMore = true;
    try {
      const page = await booksApi.getAllHighlights(
        PAGE_SIZE,
        highlights.length,
      );
      highlights = [...highlights, ...page.items];
      total = page.total;
      await fetchBookData(page.items);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loadingMore = false;
    }
  }

  async function handleDelete(hl: HighlightOut) {
    if (
      !(await confirmDialog({
        title: m.highlights_delete_confirm(),
        destructive: true,
      }))
    )
      return;
    const prev = highlights;
    // Optimistically remove, then delete immediately (no delayed undo).
    highlights = highlights.filter((h) => h.id !== hl.id);
    try {
      await booksApi.deleteHighlight(hl.book_id, hl.id);
      toastStore.success(m.highlights_removed());
    } catch (e) {
      toastStore.error((e as Error).message);
      highlights = prev;
    }
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
      <section class="mb-8 last:mb-0">
        <!-- Book header -->
        <a
          href="/books/{bookId}"
          class="group flex items-baseline gap-2 border-b border-border/60 pb-2 mb-4"
        >
          <h2
            class="text-base font-semibold text-foreground group-hover:text-primary transition-colors"
          >
            {bookTitles()[bookId] ?? m.common_untitled()}
          </h2>
          <span class="shrink-0 text-xs text-muted-foreground">
            {m.highlights_entry_count({
              count: String(bookHighlights.length),
            })}
          </span>
        </a>

        <!-- Highlights -->
        <div class="flex flex-col gap-5">
          {#each bookHighlights as hl (hl.id)}
            <div
              class="group/hl relative cursor-pointer rounded-r-lg bg-card border-l-2 border-border p-4 transition-colors hover:border-primary/50"
              role="button"
              tabindex="0"
              onclick={() =>
                goto(
                  `/books/${hl.book_id}/read?cfi=${encodeURIComponent(hl.cfi_range)}`,
                )}
              onkeydown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  goto(
                    `/books/${hl.book_id}/read?cfi=${encodeURIComponent(hl.cfi_range)}`,
                  );
                }
              }}
            >
              <p class="text-foreground leading-relaxed pr-16">{hl.text}</p>
              {#if hl.note}
                <p class="mt-1.5 text-sm italic text-muted-foreground pr-16">
                  {hl.note}
                </p>
              {/if}
              <p class="mt-1.5 text-xs text-muted-foreground/70">
                {formatDate(hl.created_at)}
              </p>

              <!-- Actions: always shown on touch, hover-revealed on desktop -->
              <div
                class="absolute right-2 top-2 flex items-center gap-1 opacity-100 transition-opacity focus-within:opacity-100 sm:opacity-0 sm:group-hover/hl:opacity-100"
              >
                <button
                  class="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  title={m.highlight_action_share()}
                  onclick={(e) => {
                    e.stopPropagation();
                    handleShare(hl);
                  }}
                >
                  <Share2 size={16} />
                </button>
                <button
                  class="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-destructive"
                  title={m.highlight_action_delete()}
                  onclick={(e) => {
                    e.stopPropagation();
                    handleDelete(hl);
                  }}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </div>
          {/each}
        </div>
      </section>
    {/each}
    {#if highlights.length < total}
      <div class="flex justify-center mt-8">
        <button
          class="px-6 py-2.5 bg-secondary hover:bg-secondary/80 text-foreground font-medium rounded-xl transition-colors disabled:opacity-50"
          onclick={loadMore}
          disabled={loadingMore}
        >
          {m.browser_load_more()}
        </button>
      </div>
    {/if}
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
