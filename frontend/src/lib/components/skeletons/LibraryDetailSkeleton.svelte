<script lang="ts">
  import { Skeleton } from "$lib/components/ui/skeleton";
  import BookGridSkeleton from "./BookGridSkeleton.svelte";
</script>

<div role="status" aria-label="Loading">
  <!-- Header: badges + title -->
  <div class="mb-8">
    <div class="flex items-center gap-2 mb-1">
      <Skeleton class="h-6 w-14 rounded-full" />
      <Skeleton class="h-6 w-20 rounded-full" />
    </div>
    <Skeleton class="h-9 w-48 mt-1" />
  </div>

  <!-- Search bar -->
  <div class="mb-6">
    <Skeleton class="w-full h-12 rounded-xl" />
  </div>

  <!-- Sort row -->
  <div class="flex justify-end mb-4">
    <Skeleton class="h-9 w-36 rounded-lg" />
  </div>

  <!-- Book count -->
  <Skeleton class="h-4 w-40 mb-4" />

  <!-- Book grid -->
  <BookGridSkeleton count={12} />
</div>
