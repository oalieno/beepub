<script lang="ts">
  import BookCardSkeleton from "./BookCardSkeleton.svelte";

  let { count = 12 }: { count?: number } = $props();
</script>

<div
  role="status"
  aria-label="Loading"
  class="grid gap-4 items-start grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6"
>
  {#each Array(count) as _}
    <BookCardSkeleton />
  {/each}
</div>
