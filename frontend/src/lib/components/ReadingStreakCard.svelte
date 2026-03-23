<script lang="ts">
  import { Flame, Check, Pencil, Target, Minus, Plus } from "@lucide/svelte";
  import * as Popover from "$lib/components/ui/popover";
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

  const STEP_VALUES = [5, 10, 15, 20, 30, 45, 60, 90, 120];

  let pendingMinutes = $state(15);

  // Sync pendingMinutes when popover opens
  $effect(() => {
    if (goalOpen) {
      pendingMinutes = goalMinutes ?? 15;
    }
  });

  async function setGoal(minutes: number | null) {
    saving = true;
    try {
      await onGoalUpdate(minutes != null ? minutes * 60 : null);
      goalOpen = false;
    } finally {
      saving = false;
    }
  }

  function stepGoal(delta: number) {
    const current = pendingMinutes;
    // Find next preset value in direction
    if (delta > 0) {
      const next = STEP_VALUES.find((p) => p > current);
      pendingMinutes = next ?? Math.min(current + 15, 480);
    } else {
      const prev = [...STEP_VALUES].reverse().find((p) => p < current);
      pendingMinutes = prev ?? Math.max(current - 5, 1);
    }
  }

  function formatGoalDisplay(mins: number): string {
    if (mins >= 60) {
      const h = Math.floor(mins / 60);
      const m = mins % 60;
      return m > 0 ? `${h}h ${m}m` : `${h}h`;
    }
    return `${mins}m`;
  }

  function formatTime(seconds: number): string {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }
</script>

<div class="group flex flex-col sm:flex-row sm:items-center gap-4">
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

    <!-- Today's reading + inline goal -->
    <div>
      <div class="flex items-baseline gap-1.5">
        <p class="text-2xl font-bold leading-none text-foreground">
          {formatTime(stats.today_seconds)}
        </p>
        <Popover.Root bind:open={goalOpen}>
          <Popover.Trigger>
            {#snippet child({ props })}
              {#if goalMinutes != null}
                <button
                  {...props}
                  class="text-xs text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-0.5 cursor-pointer rounded px-1 -mx-1 hover:bg-muted"
                >
                  / {goalMinutes}m
                  <Pencil
                    size={10}
                    class="opacity-0 group-hover:opacity-100 transition-opacity"
                  />
                </button>
              {:else}
                <button
                  {...props}
                  class="text-xs text-muted-foreground/60 hover:text-muted-foreground transition-colors inline-flex items-center gap-1 cursor-pointer rounded px-1 -mx-1 hover:bg-muted"
                >
                  <Target size={12} />
                  set goal
                </button>
              {/if}
            {/snippet}
          </Popover.Trigger>
          <Popover.Content class="w-56 p-0 overflow-hidden" align="start">
            <!-- Stepper -->
            <div class="px-5 pt-5 pb-4">
              <p class="text-xs text-muted-foreground text-center mb-3">
                Daily goal
              </p>
              <div class="flex items-center justify-center gap-4">
                <button
                  class="size-8 rounded-full bg-secondary hover:bg-secondary/70 text-secondary-foreground flex items-center justify-center transition-colors cursor-pointer disabled:opacity-30"
                  onclick={() => stepGoal(-1)}
                  disabled={saving || pendingMinutes <= 1}
                >
                  <Minus size={14} />
                </button>
                <span
                  class="text-2xl font-bold text-foreground tabular-nums min-w-[5ch] text-center whitespace-nowrap"
                >
                  {formatGoalDisplay(pendingMinutes)}
                </span>
                <button
                  class="size-8 rounded-full bg-secondary hover:bg-secondary/70 text-secondary-foreground flex items-center justify-center transition-colors cursor-pointer disabled:opacity-30"
                  onclick={() => stepGoal(1)}
                  disabled={saving || pendingMinutes >= 480}
                >
                  <Plus size={14} />
                </button>
              </div>
            </div>

            <!-- Actions -->
            <div class="px-5 pb-4 flex flex-col gap-1.5">
              <button
                class="w-full h-9 rounded-lg text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors cursor-pointer disabled:opacity-50"
                onclick={() => setGoal(pendingMinutes)}
                disabled={saving || pendingMinutes === goalMinutes}
              >
                {goalMinutes != null ? "Update goal" : "Set goal"}
              </button>
              {#if goalMinutes != null}
                <button
                  class="w-full h-9 rounded-lg text-sm text-muted-foreground hover:text-destructive hover:bg-destructive/5 transition-colors cursor-pointer"
                  onclick={() => setGoal(null)}
                  disabled={saving}
                >
                  Remove goal
                </button>
              {/if}
            </div>
          </Popover.Content>
        </Popover.Root>
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
      {:else if goalMinutes == null}
        <p class="text-xs text-muted-foreground mt-0.5">today</p>
      {/if}
    </div>
  </div>

  <!-- Right: Week indicator -->
  <div class="sm:ml-auto flex items-center">
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
  </div>
</div>
