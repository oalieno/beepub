<script lang="ts">
  import { Skeleton } from "$lib/components/ui/skeleton";
  import BookGridSkeleton from "./BookGridSkeleton.svelte";
</script>

<div role="status" aria-label="Loading">
  <!-- Hero greeting -->
  <section class="mb-12">
    <div
      class="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-2"
    >
      <div>
        <Skeleton class="h-12 w-80 mb-3" />
        <Skeleton class="h-5 w-64 mt-3" />
      </div>
      <div class="flex items-center gap-6 text-center">
        <div class="flex flex-col items-center">
          <Skeleton class="h-9 w-12 mb-1" />
          <Skeleton class="h-3 w-14" />
        </div>
        <div class="w-px h-8 bg-border"></div>
        <div class="flex flex-col items-center">
          <Skeleton class="h-9 w-16 mb-1" />
          <Skeleton class="h-3 w-10" />
        </div>
      </div>
    </div>
  </section>

  <!-- Continue Reading row -->
  <section class="mb-12">
    <div class="mb-6">
      <Skeleton class="h-7 w-48 mb-2" />
      <Skeleton class="h-4 w-52" />
    </div>
    <div class="flex gap-4 overflow-hidden pb-2">
      {#each Array(5) as _}
        <div class="shrink-0 w-[140px]">
          <Skeleton class="aspect-[2/3] rounded-xl mb-2" />
          <Skeleton class="h-4 w-full mb-1" />
          <Skeleton class="h-3 w-10" />
        </div>
      {/each}
    </div>
  </section>

  <!-- Reading Activity Heatmap -->
  <section class="mb-12">
    <div class="bg-card card-soft rounded-2xl p-4 sm:p-6">
      <Skeleton class="h-16 w-full mb-4" />
      <Skeleton class="h-32 w-full" />
    </div>
  </section>

  <!-- Recent Books grid -->
  <section class="mb-12">
    <div class="mb-6">
      <Skeleton class="h-7 w-40 mb-2" />
      <Skeleton class="h-4 w-56" />
    </div>
    <BookGridSkeleton count={12} />
  </section>
</div>
