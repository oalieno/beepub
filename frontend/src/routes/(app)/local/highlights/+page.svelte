<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { isNative } from "$lib/platform";
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

  // Share modal state
  let shareHighlight = $state<HighlightOut | null>(null);
  let shareModalOpen = $state(false);

  // Group highlights by book_id (insertion order = recency of the newest
  // highlight, because the flat list is sorted before grouping)
  let groupedHighlights = $derived(() => {
    const groups: Record<string, HighlightOut[]> = {};
    for (const hl of highlights) {
      if (!groups[hl.book_id]) groups[hl.book_id] = [];
      groups[hl.book_id].push(hl);
    }
    return groups;
  });

  onMount(async () => {
    if (!isNative()) {
      loading = false;
      return;
    }
    try {
      const { listLocalBooks } = await import("$lib/services/localLibrary");
      const { readLocalHighlightRecords } = await import("$lib/reading/local");
      const books = await listLocalBooks();
      const all: HighlightOut[] = [];
      const data: Record<string, { title: string; authors: string[] }> = {};
      await Promise.all(
        books.map(async (book) => {
          const records = await readLocalHighlightRecords(book.id);
          const live = records.filter((h) => h.deleted_at === null);
          if (live.length === 0) return;
          all.push(...live);
          data[book.id] = { title: book.title, authors: book.authors };
        }),
      );
      all.sort((a, b) => b.created_at.localeCompare(a.created_at));
      highlights = all;
      bookData = data;
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  });

  async function handleDelete(hl: HighlightOut) {
    if (
      !(await confirmDialog({
        title: m.highlights_delete_confirm(),
        destructive: true,
      }))
    )
      return;
    const prev = highlights;
    highlights = highlights.filter((h) => h.id !== hl.id);
    try {
      const { localSync } = await import("$lib/reading/local");
      await localSync.deleteHighlight(hl.book_id, hl.id);
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
  {:else if !isNative()}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      <Highlighter class="mx-auto mb-4 text-muted-foreground/30" size={48} />
      <p class="text-muted-foreground text-lg">
        {m.local_native_only()}
      </p>
    </div>
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
        <!-- Book header — local books have no detail page, open the reader -->
        <a
          href="/books/{bookId}/read"
          class="group flex items-baseline gap-2 border-b border-border/60 pb-2 mb-4"
        >
          <h2
            class="text-base font-semibold text-foreground group-hover:text-primary transition-colors"
          >
            {bookData[bookId]?.title ?? m.common_untitled()}
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
