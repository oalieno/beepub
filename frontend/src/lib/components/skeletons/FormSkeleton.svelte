<script lang="ts">
  import { Skeleton } from "$lib/components/ui/skeleton";

  let { cards = 4 }: { cards?: number } = $props();
</script>

<div role="status" aria-label="Loading" class="space-y-6">
  {#each Array(cards) as _}
    <div class="bg-card card-soft rounded-2xl p-6 space-y-4">
      <!-- Card header -->
      <div>
        <Skeleton class="h-6 w-40 mb-1.5" />
        <Skeleton class="h-4 w-72" />
      </div>
      <!-- Card content: form fields -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <div class="space-y-1.5">
          <Skeleton class="h-4 w-24" />
          <Skeleton class="h-9 w-full rounded-md" />
        </div>
        <div class="space-y-1.5">
          <Skeleton class="h-4 w-28" />
          <Skeleton class="h-9 w-full rounded-md" />
        </div>
      </div>
    </div>
  {/each}
</div>
