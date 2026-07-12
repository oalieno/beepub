<script lang="ts">
  import type { BookOut } from "$lib/types";
  import BookCard from "./BookCard.svelte";

  let {
    books = [],
    columns = "default",
  }: {
    books?: BookOut[];
    columns?: string;
  } = $props();
</script>

<div
  class="grid gap-4 items-start {columns === 'default' ? 'book-grid' : columns}"
  style={columns === "default"
    ? "grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));"
    : ""}
>
  {#each books as book (book.id)}
    <BookCard {book} />
  {/each}
</div>
