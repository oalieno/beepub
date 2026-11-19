<script lang="ts">
  import { Skeleton } from "#lib/components/ui/skeleton/index.ts";

  let { rows = 14 }: { rows?: number } = $props();

  // The library table's own columns (BookTable), so the rows that load in
  // land where their placeholders were. Varied widths: a column of
  // identical bars reads as stripes, not as text.
  const TITLE = ["w-3/5", "w-2/5", "w-4/5", "w-1/2", "w-2/3"];
  const AUTHORS = ["w-1/2", "w-1/3", "w-2/3"];
  const SERIES = ["w-3/5", "", "w-1/2", ""];
</script>

<div
  class="bg-card card-soft rounded-xl overflow-hidden h-full"
  role="status"
  aria-label="Loading"
>
  <table class="w-full text-sm table-fixed">
    <colgroup>
      <col />
      <col class="w-[22%]" />
      <col class="w-[18%]" />
      <col class="w-24" />
      <col class="w-24" />
      <col class="w-36" />
      <col class="w-12" />
    </colgroup>
    <thead>
      <tr class="border-b border-border">
        {#each ["w-10", "w-12", "w-10", "w-10", "w-8", "w-14"] as width, i (i)}
          <th class="px-3 py-3">
            <Skeleton class="h-3 {width}" />
          </th>
        {/each}
        <th></th>
      </tr>
    </thead>
    <tbody>
      {#each Array(rows) as _, i (i)}
        <tr class="border-b border-border/50 last:border-0">
          <td class="px-3 py-3">
            <Skeleton class="h-4 {TITLE[i % TITLE.length]}" />
          </td>
          <td class="px-3 py-3">
            <Skeleton class="h-4 {AUTHORS[i % AUTHORS.length]}" />
          </td>
          <td class="px-3 py-3">
            {#if SERIES[i % SERIES.length]}
              <Skeleton class="h-4 {SERIES[i % SERIES.length]}" />
            {/if}
          </td>
          <td class="px-3 py-3"></td>
          <td class="px-3 py-3"><Skeleton class="h-4 w-12" /></td>
          <td class="px-3 py-3"><Skeleton class="h-4 w-24" /></td>
          <td></td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
