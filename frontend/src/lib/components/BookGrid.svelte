<script lang="ts">
  import type { BookOut, ReadingStatus } from "$lib/types";
  import { booksApi } from "$lib/api/books";
  import { authStore } from "$lib/stores/auth";
  import { onMount } from "svelte";
  import BookCard from "./BookCard.svelte";

  let {
    books = [],
    columns = "default",
    enableInteractions = false,
    interactionMap: externalMap,
  }: {
    books?: BookOut[];
    columns?: string;
    enableInteractions?: boolean;
    interactionMap?: Record<string, ReadingStatus | null>;
  } = $props();

  let internalMap = $state<Record<string, ReadingStatus | null>>({});

  let activeMap = $derived(externalMap ?? internalMap);

  async function fetchInteractions(bookIds: string[]) {
    const token = $authStore.token;
    if (!token || bookIds.length === 0) return;
    try {
      const resp = await booksApi.getBatchInteractions(bookIds, token);
      const newMap: Record<string, ReadingStatus | null> = {};
      for (const [id, item] of Object.entries(resp.interactions)) {
        newMap[id] = (item.reading_status as ReadingStatus) ?? null;
      }
      internalMap = newMap;
    } catch {
      // silently fail
    }
  }

  function handleStatusChange(bookId: string, status: ReadingStatus | null) {
    if (externalMap) {
      externalMap[bookId] = status;
    } else {
      internalMap = { ...internalMap, [bookId]: status };
    }
  }

  onMount(() => {
    if (enableInteractions && !externalMap && books.length > 0) {
      fetchInteractions(books.map((b) => b.id));
    }
  });

  // Re-fetch when books change (e.g. pagination)
  $effect(() => {
    if (enableInteractions && !externalMap && books.length > 0) {
      fetchInteractions(books.map((b) => b.id));
    }
  });
</script>

<div
  class="grid gap-4 items-start {columns === 'default'
    ? 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6'
    : columns}"
>
  {#each books as book (book.id)}
    {#if enableInteractions || externalMap}
      <BookCard
        {book}
        readingStatus={activeMap[book.id] ?? null}
        onStatusChange={handleStatusChange}
      />
    {:else}
      <BookCard {book} />
    {/if}
  {/each}
</div>
