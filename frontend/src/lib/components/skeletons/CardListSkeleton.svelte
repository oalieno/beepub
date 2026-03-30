<script lang="ts">
  import { Skeleton } from "$lib/components/ui/skeleton";

  let { count = 4 }: { count?: number } = $props();
</script>

<div
  role="status"
  aria-label="Loading"
  class="grid grid-cols-1 gap-5 collection-grid"
>
  {#each Array(count) as _}
    <div class="bg-card card-soft rounded-2xl overflow-hidden">
      <!-- Hero cover area -->
      <Skeleton class="h-60 w-full rounded-none" />
      <!-- Info bar -->
      <div class="p-4 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <Skeleton class="h-4 w-4 rounded-full" />
          <Skeleton class="h-5 w-32" />
        </div>
        <div class="flex items-center gap-2">
          <Skeleton class="h-5 w-14 rounded-full" />
          <Skeleton class="h-4 w-16" />
        </div>
      </div>
    </div>
  {/each}
</div>

<style>
  @media (min-width: 640px) {
    .collection-grid {
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    }
  }
</style>
