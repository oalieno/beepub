<script lang="ts">
  import { Flame, ChevronDown, X, Check } from "@lucide/svelte";
  import * as Popover from "$lib/components/ui/popover";
  import { Input } from "$lib/components/ui/input";
  import type { ReadingStats } from "$lib/types";

  let {
    stats,
    readingActivity = [],
    onGoalUpdate,
  }: {
    stats: ReadingStats;
    readingActivity?: { date: string; seconds: number }[];
    onGoalUpdate: (goalSeconds: number | null) => Promise<void>;
  } = $props();

  let goalOpen = $state(false);
  let customMinutes = $state("");
  let saving = $state(false);

  let goalMinutes = $derived(
    stats.goal_seconds != null ? Math.floor(stats.goal_seconds / 60) : null,
  );
  let progressPercent = $derived(
    stats.goal_seconds != null && stats.goal_seconds > 0
      ? Math.min(
          100,
          Math.round((stats.today_seconds / stats.goal_seconds) * 100),
        )
      : null,
  );
  let goalMet = $derived(progressPercent != null && progressPercent >= 100);

  const DAY_LABELS = ["M", "T", "W", "T", "F", "S", "S"];

  let weekDays = $derived.by(() => {
    const activityMap = new Map<string, number>();
    for (const d of readingActivity) activityMap.set(d.date, d.seconds);

    const today = new Date();
    const todayDow = (today.getDay() + 6) % 7; // Mon=0
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    const days: {
      label: string;
      date: string;
      hasReading: boolean;
      isToday: boolean;
    }[] = [];

    for (let i = 0; i < 7; i++) {
      const d = new Date(today);
      d.setDate(today.getDate() - todayDow + i);
      const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      days.push({
        label: DAY_LABELS[i],
        date: dateStr,
        hasReading: (activityMap.get(dateStr) ?? 0) > 0,
        isToday: dateStr === todayStr,
      });
    }
    return days;
  });

  const PRESETS = [
    { mins: 5, label: "5m" },
    { mins: 15, label: "15m" },
    { mins: 30, label: "30m" },
    { mins: 60, label: "1h" },
  ];

  async function setGoal(minutes: number | null) {
    saving = true;
    try {
      await onGoalUpdate(minutes != null ? minutes * 60 : null);
      goalOpen = false;
      customMinutes = "";
    } finally {
      saving = false;
    }
  }

  function handleCustomGoal() {
    const mins = parseInt(customMinutes);
    if (mins > 0 && mins <= 1440) {
      setGoal(mins);
    }
  }

  function formatTime(seconds: number): string {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }
</script>

<div class="flex flex-col sm:flex-row sm:items-center gap-4">
  <!-- Left: Streak + Today -->
  <div class="flex items-center gap-5">
    <!-- Streak -->
    <div class="flex items-center gap-2.5">
      <div
        class="flex items-center justify-center size-10 rounded-xl {stats.current_streak >
        0
          ? 'bg-orange-500/15 text-orange-500'
          : 'bg-muted text-muted-foreground'}"
      >
        <Flame size={20} />
      </div>
      <div>
        <p class="text-2xl font-bold leading-none text-foreground">
          {stats.current_streak}
        </p>
        <p class="text-xs text-muted-foreground mt-0.5">
          day{stats.current_streak !== 1 ? "s" : ""} streak
        </p>
      </div>
    </div>

    <!-- Divider -->
    <div class="w-px h-10 bg-border"></div>

    <!-- Today's reading -->
    <div>
      <div class="flex items-baseline gap-1.5">
        <p class="text-2xl font-bold leading-none text-foreground">
          {formatTime(stats.today_seconds)}
        </p>
        {#if goalMinutes != null}
          <span class="text-xs text-muted-foreground">/ {goalMinutes}m</span>
        {/if}
      </div>
      {#if goalMinutes != null && progressPercent != null}
        <div class="flex items-center gap-2 mt-1">
          <div
            class="h-1.5 w-20 rounded-full bg-muted-foreground/15 overflow-hidden"
          >
            <div
              class="h-full rounded-full transition-all duration-300 {goalMet
                ? 'bg-primary'
                : 'bg-primary/70'}"
              style="width: {progressPercent}%"
            ></div>
          </div>
          <span class="text-xs text-muted-foreground">{progressPercent}%</span>
        </div>
      {:else}
        <p class="text-xs text-muted-foreground mt-0.5">today</p>
      {/if}
    </div>
  </div>

  <!-- Right: Week indicator + Goal setting -->
  <div class="sm:ml-auto flex items-center gap-4">
    <!-- Week days -->
    <div class="flex items-center gap-2">
      {#each weekDays as day}
        <div
          class="flex flex-col items-center gap-1"
          title="{day.date}: {day.hasReading ? 'Read' : 'No reading'}"
        >
          <span
            class="text-[10px] leading-none {day.isToday
              ? 'text-foreground font-semibold'
              : 'text-muted-foreground'}">{day.label}</span
          >
          <div
            class="size-5 rounded-full flex items-center justify-center {day.hasReading
              ? 'bg-primary text-primary-foreground'
              : 'bg-muted'}"
          >
            {#if day.hasReading}
              <Check size={10} strokeWidth={3} />
            {/if}
          </div>
        </div>
      {/each}
    </div>

    <!-- Goal setting -->
    <Popover.Root bind:open={goalOpen}>
      <Popover.Trigger>
        {#snippet child({ props })}
          <button
            {...props}
            class="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-0.5 cursor-pointer"
          >
            {goalMinutes != null ? "Goal" : "Set goal"}
            <ChevronDown size={12} />
          </button>
        {/snippet}
      </Popover.Trigger>
      <Popover.Content class="w-64 p-0 overflow-hidden" align="end">
        <!-- Header -->
        <div class="px-4 pt-4 pb-3">
          <p
            class="text-sm font-semibold text-foreground"
            style="font-family: var(--font-heading)"
          >
            Daily Reading Goal
          </p>
          <p class="text-xs text-muted-foreground mt-0.5">
            How long do you want to read each day?
          </p>
        </div>

        <!-- Preset pills -->
        <div class="px-4 pb-3">
          <div class="grid grid-cols-4 gap-1.5">
            {#each PRESETS as preset}
              <button
                class="h-8 rounded-lg text-sm font-medium transition-all cursor-pointer
                  {goalMinutes === preset.mins
                  ? 'bg-primary text-primary-foreground shadow-sm'
                  : 'bg-secondary text-secondary-foreground hover:bg-secondary/80'}"
                onclick={() => setGoal(preset.mins)}
                disabled={saving}
              >
                {preset.label}
              </button>
            {/each}
          </div>
        </div>

        <!-- Custom input -->
        <div class="px-4 pb-3">
          <form
            class="flex gap-1.5"
            onsubmit={(e) => {
              e.preventDefault();
              handleCustomGoal();
            }}
          >
            <Input
              type="number"
              placeholder="Custom minutes"
              class="h-9 text-sm"
              bind:value={customMinutes}
              min="1"
              max="1440"
            />
            <button
              type="submit"
              class="h-9 px-3 rounded-lg text-sm font-medium bg-secondary text-secondary-foreground hover:bg-secondary/80 transition-colors shrink-0 cursor-pointer disabled:opacity-50"
              disabled={saving || !customMinutes}
            >
              Set
            </button>
          </form>
        </div>

        <!-- Remove goal -->
        {#if goalMinutes != null}
          <div class="border-t border-border">
            <button
              class="w-full py-2.5 text-xs text-muted-foreground hover:text-destructive hover:bg-destructive/5 transition-colors flex items-center justify-center gap-1 cursor-pointer"
              onclick={() => setGoal(null)}
              disabled={saving}
            >
              <X size={12} />
              Remove goal
            </button>
          </div>
        {/if}
      </Popover.Content>
    </Popover.Root>
  </div>
</div>
