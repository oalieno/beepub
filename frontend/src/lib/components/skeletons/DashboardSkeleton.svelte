<script lang="ts">
  import { Skeleton } from "$lib/components/ui/skeleton";
</script>

<div role="status" aria-label="Loading">
  <!-- Stat row -->
  <div class="bg-card card-soft rounded-2xl overflow-hidden mb-6">
    <div class="flex divide-x divide-border">
      {#each Array(3) as _}
        <div class="flex-1 flex flex-col items-center py-3 px-2 gap-0.5">
          <Skeleton class="h-5 w-10" />
          <Skeleton class="h-3 w-8" />
        </div>
      {/each}
    </div>
  </div>

  <!-- Link list -->
  <div class="bg-card card-soft rounded-2xl overflow-hidden">
    {#each Array(7) as _, i}
      {#if i > 0}
        <div class="flex justify-center">
          <div
            class="w-4/5 h-px bg-border"
            style="transform: scaleY(0.5);"
          ></div>
        </div>
      {/if}
      <div class="flex items-center gap-3 px-4 py-3.5">
        <Skeleton class="w-5 h-5 rounded shrink-0" />
        <Skeleton class="h-4 w-24 flex-1" />
        <Skeleton class="w-4 h-4 rounded" />
      </div>
    {/each}
  </div>
</div>
