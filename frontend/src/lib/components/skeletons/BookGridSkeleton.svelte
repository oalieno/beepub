<script lang="ts">
  import BookCardSkeleton from "./BookCardSkeleton.svelte";

  let { count = 12 }: { count?: number } = $props();
</script>

<div
  role="status"
  aria-label="Loading"
  class="grid gap-4 items-start"
  style="grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));"
>
  {#each Array(count) as _}
    <BookCardSkeleton />
  {/each}
</div>
