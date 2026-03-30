<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { adminApi, aiApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import type { AiStatus, JobStatus } from "$lib/types";
  import {
    FileText,
    Search,
    BookOpen,
    Tags,
    ScanSearch,
    LibraryBig,
    LoaderCircle,
    Square,
    TriangleAlert,
  } from "@lucide/svelte";
  import { FormSkeleton } from "$lib/components/skeletons";

  let jobs = $state<JobStatus[]>([]);
  let aiStatus = $state<AiStatus | null>(null);
  let loading = $state(true);
  let triggeringJob = $state<string | null>(null);
  let stoppingJob = $state<string | null>(null);
  let pollInterval: ReturnType<typeof setInterval> | null = null;

  const JOB_ICONS: Record<string, typeof FileText> = {
    text_extraction: FileText,
    embedding: Search,
    summarize: BookOpen,
    auto_tag: Tags,
    book_embedding: LibraryBig,
  };

  /** Maps job keys that require AI to their corresponding AiStatus field. */
  const JOB_AI_FEATURE: Record<string, keyof AiStatus> = {
    embedding: "embedding",
    summarize: "tag",
    auto_tag: "tag",
    book_embedding: "embedding",
  };

  const STALE_THRESHOLD_S = 7200; // 2 hours

  function isAiReady(jobKey: string): boolean {
    const feature = JOB_AI_FEATURE[jobKey];
    if (!feature) return true; // non-AI job, always ready
    return aiStatus?.[feature] ?? false;
  }

  function isStale(job: JobStatus): boolean {
    if (!job.progress?.last_activity) return false;
    return Date.now() / 1000 - job.progress.last_activity > STALE_THRESHOLD_S;
  }

  async function fetchJobs() {
    try {
      const res = await adminApi.getJobs();
      jobs = res.jobs;
    } catch (e) {
      if (loading) {
        toastStore.error((e as Error).message);
      }
    } finally {
      loading = false;
    }
  }

  async function stopJob(jobType: string) {
    stoppingJob = jobType;
    try {
      await adminApi.stopJob(jobType);
      toastStore.success(`Job stopped: ${jobType}`);
      await fetchJobs();
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      stoppingJob = null;
    }
  }

  async function triggerJob(jobType: string) {
    triggeringJob = jobType;
    try {
      await adminApi.triggerJob(jobType);
      toastStore.success(`Job started: ${jobType}`);
      await fetchJobs();
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      triggeringJob = null;
    }
  }

  onMount(async () => {
    await Promise.all([
      fetchJobs(),
      aiApi.getStatus().then((s) => (aiStatus = s)),
    ]);
    pollInterval = setInterval(fetchJobs, 3000);
  });

  onDestroy(() => {
    if (pollInterval) clearInterval(pollInterval);
  });
</script>

<svelte:head>
  <title>Jobs - Admin - BeePub</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6 mx-auto" style="max-width: 1000px;">
  <div class="mb-8">
    <a
      href="/admin"
      class="text-muted-foreground hover:text-foreground text-sm mb-1 inline-block"
      >&larr; Admin</a
    >
    <h1 class="text-3xl font-bold text-foreground">Jobs</h1>
    <p class="text-muted-foreground mt-1">
      Monitor and trigger background processing tasks
    </p>
  </div>

  {#if loading}
    <FormSkeleton cards={6} />
  {:else}
    <div class="space-y-3">
      {#each jobs as job (job.key)}
        {@const Icon = JOB_ICONS[job.key] ?? FileText}
        {@const isTriggering = triggeringJob === job.key}
        {@const running = job.active && job.missing > 0}
        {@const p = job.progress}
        {@const stale = isStale(job)}
        {@const pct =
          p && p.total > 0
            ? Math.round(((p.completed + p.failed) / p.total) * 100)
            : 0}

        <div
          class="bg-card card-soft rounded-2xl overflow-hidden flex border border-border/50"
        >
          <!-- Main content -->
          <div class="flex-1 px-5 py-4 sm:px-6 sm:py-5 min-w-0">
            <!-- Header row -->
            <div class="flex items-center gap-2.5">
              <Icon
                class="text-muted-foreground shrink-0"
                size={18}
                strokeWidth={1.75}
              />
              <span
                class="font-semibold text-foreground font-sans text-base leading-none"
              >
                {job.label}
              </span>
              {#if job.requires_ai}
                <span
                  class="text-[10px] font-semibold uppercase tracking-wide px-2 py-1 rounded-md bg-purple-500/15 text-purple-600 dark:text-purple-400 leading-none"
                >
                  AI
                </span>
              {/if}
              {#if running && !stale}
                <LoaderCircle
                  class="text-primary animate-spin shrink-0"
                  size={15}
                />
              {/if}
              {#if stale && running}
                <TriangleAlert class="text-amber-500 shrink-0" size={15} />
              {/if}
            </div>

            <p class="text-muted-foreground text-sm mt-1 mb-4 ml-[1.75rem]">
              {job.description}
            </p>

            <!-- Progress bar (when running with progress data) -->
            {#if running && p && p.total > 0}
              <div class="ml-[1.75rem] mb-3">
                <div class="flex items-center gap-3 mb-1.5">
                  <span
                    class="text-xs sm:text-sm font-semibold text-foreground font-sans tabular-nums"
                  >
                    {p.completed.toLocaleString()}/{p.total.toLocaleString()}
                  </span>
                  {#if p.failed > 0}
                    <span
                      class="text-xs font-medium text-destructive font-sans tabular-nums"
                    >
                      {p.failed.toLocaleString()} failed
                    </span>
                  {/if}
                  {#if stale}
                    <span class="text-xs font-medium text-amber-500">
                      Stalled
                    </span>
                  {/if}
                  <span
                    class="text-xs text-muted-foreground font-sans tabular-nums ml-auto"
                  >
                    {pct}%
                  </span>
                </div>
                <div class="h-1.5 rounded-full bg-muted overflow-hidden">
                  <div
                    class="h-full rounded-full transition-all duration-500 ease-out {stale
                      ? 'bg-amber-500'
                      : 'bg-primary'}"
                    style="width: {pct}%"
                  ></div>
                </div>
              </div>
            {/if}

            <!-- Status bar -->
            <div
              class="inline-flex items-stretch rounded-lg overflow-hidden border border-border/50"
            >
              <div
                class="flex items-center gap-2 sm:gap-5 px-2.5 sm:px-3.5 py-2"
              >
                <span class="text-xs sm:text-sm text-muted-foreground"
                  >Missing</span
                >
                <span
                  class="text-xs sm:text-sm font-semibold text-foreground font-sans tabular-nums"
                >
                  {job.missing.toLocaleString()}
                </span>
              </div>
              {#if job.blocked > 0}
                <div class="w-px bg-border/50"></div>
                <div
                  class="flex items-center gap-2 sm:gap-5 px-2.5 sm:px-3.5 py-2 bg-muted/50"
                >
                  <span class="text-xs sm:text-sm text-muted-foreground"
                    >{job.blocked_label}</span
                  >
                  <span
                    class="text-xs sm:text-sm font-semibold text-muted-foreground font-sans tabular-nums"
                  >
                    {job.blocked.toLocaleString()}
                  </span>
                </div>
              {/if}
            </div>
          </div>

          <!-- Action buttons -->
          <div
            class="flex flex-col border-l border-border/50 shrink-0 w-[4.5rem] sm:w-20"
          >
            {#if running}
              <button
                class="flex-1 flex flex-col items-center justify-center gap-1.5 hover:bg-destructive/10 active:bg-destructive/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                disabled={stoppingJob === job.key}
                onclick={() => stopJob(job.key)}
                title="Stop this job"
              >
                {#if stoppingJob === job.key}
                  <LoaderCircle
                    class="text-destructive animate-spin"
                    size={18}
                  />
                {:else}
                  <Square size={16} class="text-destructive fill-destructive" />
                {/if}
                <span class="text-xs text-destructive font-sans font-medium"
                  >Stop</span
                >
              </button>
            {:else}
              <button
                class="flex-1 flex flex-col items-center justify-center gap-1.5 hover:bg-muted/60 active:bg-muted transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                disabled={isTriggering ||
                  job.missing === 0 ||
                  !isAiReady(job.key)}
                onclick={() => triggerJob(job.key)}
                title={!isAiReady(job.key)
                  ? "AI provider not configured — check Admin Settings"
                  : "Process unprocessed books"}
              >
                {#if isTriggering}
                  <LoaderCircle class="text-primary animate-spin" size={18} />
                {:else}
                  <ScanSearch size={18} class="text-muted-foreground" />
                {/if}
                <span
                  class="text-xs text-muted-foreground font-sans font-medium"
                  >Run</span
                >
              </button>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
