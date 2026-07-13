<script lang="ts">
  import { onMount } from "svelte";
  import * as m from "$lib/paraglide/messages.js";

  let {
    data = [],
    year,
  }: {
    data: { date: string; seconds: number }[];
    year: number;
  } = $props();

  // On phones the 53-column year grid is ~750px wide — it either clips or
  // buries "now" behind a scroll hunt. Default to the trailing weeks there,
  // with a toggle to expand to the full year.
  const COMPACT_WEEKS = 16;
  let isNarrow = $state(false);
  let expanded = $state(false);
  let scrollEl: HTMLDivElement | undefined = $state();

  onMount(() => {
    const mq = window.matchMedia("(max-width: 640px)");
    isNarrow = mq.matches;
    const onChange = (e: MediaQueryListEvent) => (isNarrow = e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  });

  let compact = $derived(isNarrow && !expanded);

  $effect(() => {
    // Expanding reveals the whole year; bring the week containing today
    // to the right edge. scrollWidth would land on the year's empty
    // future tail instead of "now".
    if (expanded && scrollEl) {
      const frac = (endWeekIndex + 1) / weeks.length;
      scrollEl.scrollLeft = Math.max(
        0,
        scrollEl.scrollWidth * frac - scrollEl.clientWidth,
      );
    }
  });

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

  // The week containing today; falls back to the year's last week when
  // viewing a past year.
  let endWeekIndex = $derived.by(() => {
    const today = new Date();
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    const idx = weeks.findIndex((w) => w.some((c) => c.date === todayStr));
    return idx === -1 ? weeks.length - 1 : idx;
  });

  let visibleWeeks = $derived.by(() => {
    if (!compact) return weeks;
    return weeks.slice(
      Math.max(0, endWeekIndex - (COMPACT_WEEKS - 1)),
      endWeekIndex + 1,
    );
  });

  let totalSeconds = $derived(data.reduce((sum, d) => sum + d.seconds, 0));
  let totalHours = $derived(Math.floor(totalSeconds / 3600));
  let remainingMinutes = $derived(Math.floor((totalSeconds % 3600) / 60));

  function formatTooltip(date: string, seconds: number): string {
    if (!date) return "";
    if (seconds === 0) return `${date}: ${m.heatmap_no_reading()}`;
    const h = Math.floor(seconds / 3600);
    const min = Math.floor((seconds % 3600) / 60);
    const timeStr =
      h > 0
        ? m.time_hours_minutes({ hours: String(h), minutes: String(min) })
        : m.time_minutes({ minutes: String(min) });
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
      {m.heatmap_title({ year: String(year) })}
    </h3>
    <span class="text-sm text-muted-foreground">
      {#if totalHours > 0}
        {m.heatmap_total_time({
          hours: String(totalHours),
          minutes: String(remainingMinutes),
        })}
      {:else}
        {m.heatmap_total_minutes({ minutes: String(remainingMinutes) })}
      {/if}
    </span>
  </div>

  <div
    class="max-w-full overflow-x-auto scrollbar-thin pb-2"
    bind:this={scrollEl}
  >
    <div
      class="grid w-full min-w-max gap-[3px]"
      style="grid-template-columns: repeat({visibleWeeks.length}, minmax(11px, 1fr)); grid-template-rows: repeat(7, minmax(11px, 1fr));"
    >
      {#each { length: 7 } as _, dayIndex}
        {#each visibleWeeks as week}
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
    class="mt-1 flex flex-wrap items-center justify-between gap-1.5 text-xs text-muted-foreground"
  >
    {#if isNarrow}
      <button
        class="text-primary underline underline-offset-4 hover:opacity-80 transition-opacity"
        onclick={() => (expanded = !expanded)}
      >
        {expanded
          ? m.heatmap_show_recent({ count: String(COMPACT_WEEKS) })
          : m.heatmap_show_year()}
      </button>
    {:else}
      <span></span>
    {/if}
    <div class="flex items-center gap-1.5">
      <span>{m.heatmap_less()}</span>
      <div
        class="size-[11px] rounded-[2px]"
        style="background: var(--muted)"
      ></div>
      {#each LEVELS as color}
        <div
          class="size-[11px] rounded-[2px]"
          style="background: {color}"
        ></div>
      {/each}
      <span>{m.heatmap_more()}</span>
    </div>
  </div>
</div>
