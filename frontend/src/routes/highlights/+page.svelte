<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import { booksApi } from '$lib/api/books';
  import { toastStore } from '$lib/stores/toast';
  import HighlightList from '$lib/components/HighlightList.svelte';
  import type { HighlightOut, BookOut } from '$lib/types';
  import { Highlighter } from '@lucide/svelte';

  let highlights = $state<HighlightOut[]>([]);
  let bookTitles = $state<Record<string, string>>({});
  let loading = $state(true);

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
    if (!$authStore.token) { goto('/login'); return; }
    try {
      highlights = await booksApi.getAllHighlights($authStore.token);

      // Fetch book titles for all unique book IDs
      const bookIds = [...new Set(highlights.map((h) => h.book_id))];
      const titles: Record<string, string> = {};
      await Promise.all(
        bookIds.map(async (id) => {
          try {
            const book = await booksApi.get(id, $authStore.token!);
            titles[id] = book.display_title ?? book.epub_title ?? 'Untitled';
          } catch {
            titles[id] = 'Unknown Book';
          }
        })
      );
      bookTitles = titles;
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  });

  async function handleDelete(hl: HighlightOut) {
    if (!$authStore.token) return;
    try {
      await booksApi.deleteHighlight(hl.book_id, hl.id, $authStore.token);
      highlights = highlights.filter((h) => h.id !== hl.id);
      toastStore.success('Highlight removed');
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>Highlights - BeePub</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
  <div class="flex items-center gap-3 mb-6">
    <div class="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
      <Highlighter size={20} class="text-primary" />
    </div>
    <div>
      <h1 class="text-2xl font-bold text-foreground">Highlights</h1>
      <p class="text-sm text-muted-foreground">All your highlights across books</p>
    </div>
  </div>

  {#if loading}
    <div class="flex items-center justify-center h-40">
      <div class="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-primary"></div>
    </div>
  {:else if highlights.length === 0}
    <div class="text-center py-16">
      <Highlighter size={40} class="text-muted-foreground/30 mx-auto mb-3" />
      <p class="text-muted-foreground">No highlights yet.</p>
      <p class="text-sm text-muted-foreground/60 mt-1">Select text while reading to create highlights.</p>
    </div>
  {:else}
    {#each Object.entries(groupedHighlights()) as [bookId, bookHighlights] (bookId)}
      <div class="mb-6">
        <a
          href="/books/{bookId}"
          class="text-sm font-semibold text-foreground hover:text-primary transition-colors mb-2 block"
        >
          {bookTitles[bookId] ?? 'Unknown Book'}
        </a>
        <div class="bg-card card-soft rounded-2xl p-3">
          <HighlightList
            highlights={bookHighlights}
            onselect={(hl) => goto(`/books/${hl.book_id}/read`)}
            ondelete={handleDelete}
          />
        </div>
      </div>
    {/each}
  {/if}
</div>
