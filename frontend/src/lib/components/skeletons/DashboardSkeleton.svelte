<script lang="ts">
  import { Skeleton } from "$lib/components/ui/skeleton";
</script>

<div role="status" aria-label="Loading">
  <!-- Stat cards -->
  <div class="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-10">
    {#each Array(3) as _}
      <div class="bg-card card-soft rounded-2xl p-6 flex flex-col items-center">
        <Skeleton class="w-12 h-12 rounded-xl mb-3" />
        <Skeleton class="h-8 w-16 mb-1" />
        <Skeleton class="h-4 w-12" />
      </div>
    {/each}
  </div>

  <!-- Link cards -->
  <div class="space-y-3">
    {#each Array(6) as _}
      <div class="bg-card card-soft rounded-2xl p-5 flex items-center gap-4">
        <Skeleton class="w-10 h-10 rounded-xl shrink-0" />
        <div class="flex-1 space-y-1.5">
          <Skeleton class="h-5 w-28" />
          <Skeleton class="h-4 w-48" />
        </div>
      </div>
    {/each}
  </div>
</div>
