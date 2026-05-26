<script lang="ts">
  import type { BookOut, ReadingStatus } from "$lib/types";
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
    // Reading status per book id, supplied inline by the page that owns the
    // list. Callers that show interactions are expected to provide this.
    interactionMap?: Record<string, ReadingStatus | null>;
  } = $props();

  // Fallback store for optimistic toggle updates when no external map is given.
  let internalMap = $state<Record<string, ReadingStatus | null>>({});

  let activeMap = $derived(externalMap ?? internalMap);

  function handleStatusChange(bookId: string, status: ReadingStatus | null) {
    if (externalMap) {
      externalMap[bookId] = status;
    } else {
      internalMap = { ...internalMap, [bookId]: status };
    }
  }
</script>

<div
  class="grid gap-4 items-start {columns === 'default' ? 'book-grid' : columns}"
  style={columns === "default"
    ? "grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));"
    : ""}
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
