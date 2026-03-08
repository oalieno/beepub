<script lang="ts">
  import type { BookOut } from "$lib/types";
  import BookCard from "./BookCard.svelte";

  let {
    books = [],
    columns = "default",
  }: { books?: BookOut[]; columns?: string } = $props();
</script>

<div
  class="grid gap-4 items-start {columns === 'default'
    ? 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6'
    : columns}"
>
  {#each books as book (book.id)}
    <BookCard {book} />
  {/each}
</div>
