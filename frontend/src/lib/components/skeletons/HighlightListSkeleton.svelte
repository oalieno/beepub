<script lang="ts">
  import { Skeleton } from "$lib/components/ui/skeleton";

  let { groups = 3 }: { groups?: number } = $props();
</script>

<div role="status" aria-label="Loading">
  {#each Array(groups) as _, gi}
    <div class="mb-6">
      <!-- Book title -->
      <Skeleton class="h-4 w-40 mb-2" />
      <!-- Highlight cards -->
      <div class="bg-card card-soft rounded-2xl p-3 space-y-3">
        {#each Array(gi === 0 ? 3 : 2) as _}
          <div class="space-y-2 py-2">
            <Skeleton class="h-3.5 w-full" />
            <Skeleton class="h-3.5 w-5/6" />
          </div>
        {/each}
      </div>
    </div>
  {/each}
</div>
