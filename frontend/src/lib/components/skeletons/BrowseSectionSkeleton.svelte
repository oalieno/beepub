<script lang="ts">
  import { Skeleton } from "$lib/components/ui/skeleton";
  import BookCardSkeleton from "./BookCardSkeleton.svelte";

  let { sections = 3 }: { sections?: number } = $props();
</script>

<div role="status" aria-label="Loading" class="space-y-10">
  {#each Array(sections) as _}
    <div>
      <div class="flex items-center justify-between mb-3">
        <Skeleton class="h-6 w-32" />
        <Skeleton class="h-4 w-16" />
      </div>
      <div class="flex gap-4 overflow-hidden pb-4 -mx-2 px-2">
        {#each Array(6) as _}
          <div class="flex-shrink-0 w-[140px] sm:w-[160px]">
            <BookCardSkeleton />
          </div>
        {/each}
      </div>
    </div>
  {/each}
</div>
