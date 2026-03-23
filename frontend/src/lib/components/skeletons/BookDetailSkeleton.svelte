<script lang="ts">
  import { Skeleton } from "$lib/components/ui/skeleton";
</script>

<div role="status" aria-label="Loading">
  <!-- Back button placeholder -->
  <Skeleton class="h-5 w-16 mb-6" />

  <!-- Hero Section -->
  <div class="flex flex-col md:flex-row gap-12">
    <!-- Cover -->
    <div
      class="flex-shrink-0 w-64 mx-auto md:mx-0 flex justify-center md:self-start"
    >
      <Skeleton class="w-full aspect-[2/3] rounded-sm" />
    </div>

    <!-- Info -->
    <div class="flex-1 min-w-0 flex flex-col pt-6 space-y-5">
      <!-- Title -->
      <div>
        <Skeleton class="h-10 w-3/4 mb-3" />
        <Skeleton class="h-5 w-1/3" />
      </div>

      <!-- Rating -->
      <div>
        <Skeleton class="h-4 w-20 mb-2" />
        <div class="flex gap-1">
          {#each Array(5) as _}
            <Skeleton class="h-6 w-6 rounded-full" />
          {/each}
        </div>
      </div>

      <!-- Status / Actions -->
      <div class="flex gap-3 mt-4">
        <Skeleton class="h-10 w-32 rounded-lg" />
        <Skeleton class="h-10 w-10 rounded-lg" />
        <Skeleton class="h-10 w-10 rounded-lg" />
      </div>

      <!-- Description -->
      <div class="space-y-2 mt-6">
        <Skeleton class="h-4 w-full" />
        <Skeleton class="h-4 w-full" />
        <Skeleton class="h-4 w-5/6" />
        <Skeleton class="h-4 w-2/3" />
      </div>
    </div>
  </div>
</div>
