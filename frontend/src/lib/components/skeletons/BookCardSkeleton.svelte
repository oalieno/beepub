<script lang="ts">
  import { Skeleton } from "$lib/components/ui/skeleton";
</script>

<div class="w-full">
  <div class="h-56 sm:h-64 mb-3 flex items-end justify-center">
    <Skeleton class="h-56 sm:h-64 aspect-[2/3] rounded-sm" />
  </div>
  <div class="min-h-[3rem]">
    <Skeleton class="h-4 w-3/4 mb-1.5" />
    <Skeleton class="h-3 w-1/2" />
  </div>
</div>
