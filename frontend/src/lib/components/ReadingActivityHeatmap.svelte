<script lang="ts">
  let {
    data = [],
    year,
  }: {
    data: { date: string; seconds: number }[];
    year: number;
  } = $props();

  const LEVELS = [
    "var(--hm-1)",
    "var(--hm-2)",
    "var(--hm-3)",
    "var(--hm-4)",
    "var(--hm-5)",
  ];

  let secondsMap = $derived.by(() => {
    const map = new Map<string, number>();
    for (const d of data) map.set(d.date, d.seconds);
    return map;
  });

  let maxSeconds = $derived(Math.max(1, ...data.map((d) => d.seconds)));

  function getLevel(seconds: number): number {
    if (seconds === 0) return -1;
    const ratio = seconds / maxSeconds;
    if (ratio <= 0.2) return 0;
    if (ratio <= 0.4) return 1;
    if (ratio <= 0.6) return 2;
    if (ratio <= 0.8) return 3;
    return 4;
  }

  let weeks = $derived.by(() => {
    const result: { date: string; seconds: number }[][] = [];
    const jan1 = new Date(year, 0, 1);
    const dayOfWeek = (jan1.getDay() + 6) % 7;
    const start = new Date(jan1);
    start.setDate(start.getDate() - dayOfWeek);

    for (let w = 0; w < 53; w++) {
      const week: { date: string; seconds: number }[] = [];
      for (let d = 0; d < 7; d++) {
        const current = new Date(start);
        current.setDate(start.getDate() + w * 7 + d);
        const dateStr = `${current.getFullYear()}-${String(current.getMonth() + 1).padStart(2, "0")}-${String(current.getDate()).padStart(2, "0")}`;
        const inYear = current.getFullYear() === year;
        week.push({
          date: inYear ? dateStr : "",
          seconds: inYear ? (secondsMap.get(dateStr) ?? 0) : -1,
        });
      }
      result.push(week);
    }
    return result;
  });

  let totalSeconds = $derived(data.reduce((sum, d) => sum + d.seconds, 0));
  let totalHours = $derived(Math.floor(totalSeconds / 3600));
  let remainingMinutes = $derived(Math.floor((totalSeconds % 3600) / 60));

  function formatTooltip(date: string, seconds: number): string {
    if (!date) return "";
    if (seconds === 0) return `${date}: No reading`;
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const timeStr = h > 0 ? `${h}h ${m}m` : `${m}m`;
    return `${date}: ${timeStr}`;
  }
</script>

<div
  style="
    --hm-1: color-mix(in srgb, var(--primary) 20%, transparent);
    --hm-2: color-mix(in srgb, var(--primary) 40%, transparent);
    --hm-3: color-mix(in srgb, var(--primary) 60%, transparent);
    --hm-4: color-mix(in srgb, var(--primary) 80%, transparent);
    --hm-5: var(--primary);
  "
>
  <div class="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
    <h3 class="text-lg font-semibold text-foreground">
      Reading Activity ({year})
    </h3>
    <span class="text-sm text-muted-foreground">
      {#if totalHours > 0}
        {totalHours}h {remainingMinutes}m total
      {:else}
        {remainingMinutes}m total
      {/if}
    </span>
  </div>

  <div class="max-w-full overflow-x-auto pb-2">
    <div
      class="grid w-full min-w-max gap-[3px]"
      style="grid-template-columns: repeat({weeks.length}, minmax(11px, 1fr)); grid-template-rows: repeat(7, minmax(11px, 1fr));"
    >
      {#each { length: 7 } as _, dayIndex}
        {#each weeks as week}
          {@const cell = week[dayIndex]}
          {#if cell.seconds === -1}
            <div class="w-full aspect-square"></div>
          {:else}
            {@const level = getLevel(cell.seconds)}
            <div
              class="w-full aspect-square rounded-[2px]"
              style="background: {level >= 0 ? LEVELS[level] : 'var(--muted)'}"
              title={formatTooltip(cell.date, cell.seconds)}
            ></div>
          {/if}
        {/each}
      {/each}
    </div>
  </div>

  <div
    class="mt-1 flex flex-wrap items-center justify-start gap-1.5 text-xs text-muted-foreground sm:justify-end"
  >
    <span>Less</span>
    <div
      class="size-[11px] rounded-[2px]"
      style="background: var(--muted)"
    ></div>
    {#each LEVELS as color}
      <div class="size-[11px] rounded-[2px]" style="background: {color}"></div>
    {/each}
    <span>More</span>
  </div>
</div>
