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
          <div
            class="flex-shrink-0 w-[calc(50%-8px)] sm:w-[calc(33.33%-11px)] md:w-[calc(25%-12px)] lg:w-[calc(20%-13px)] xl:w-[calc(16.66%-14px)]"
          >
            <BookCardSkeleton />
          </div>
        {/each}
      </div>
    </div>
  {/each}
</div>
