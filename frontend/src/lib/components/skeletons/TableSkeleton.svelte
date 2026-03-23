<script lang="ts">
  import { Skeleton } from "$lib/components/ui/skeleton";

  let { rows = 5, columns = 4 }: { rows?: number; columns?: number } = $props();
</script>

<div role="status" aria-label="Loading">
  <div class="bg-card card-soft rounded-2xl overflow-hidden">
    <!-- Table header -->
    <div class="flex gap-4 px-5 py-3.5 border-b border-border/50">
      {#each Array(columns) as _, i}
        <Skeleton
          class="h-3.5 rounded {i === 0
            ? 'w-28'
            : i === columns - 1
              ? 'w-16'
              : 'w-24'}"
        />
      {/each}
    </div>
    <!-- Table rows -->
    {#each Array(rows) as _}
      <div
        class="flex items-center gap-4 px-5 py-3.5 border-b border-border/10 last:border-b-0"
      >
        {#each Array(columns) as _, i}
          <Skeleton
            class="h-4 rounded {i === 0
              ? 'w-24'
              : i === columns - 1
                ? 'w-20'
                : 'w-32'}"
          />
        {/each}
      </div>
    {/each}
  </div>
</div>
