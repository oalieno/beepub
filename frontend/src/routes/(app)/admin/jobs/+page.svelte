<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { adminApi } from "$lib/api/admin";
  import { aiApi } from "$lib/api/bookshelves";
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
  } from "@lucide/svelte";
  import { FormSkeleton } from "$lib/components/skeletons";
  import BackButton from "$lib/components/BackButton.svelte";
  import * as m from "$lib/paraglide/messages.js";

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
    metadata_backfill: ScanSearch,
  };

  /** Maps job keys that require AI to their corresponding AiStatus field. */
  const JOB_AI_FEATURE: Record<string, keyof AiStatus> = {
    embedding: "embedding",
    summarize: "tag",
    auto_tag: "tag",
    book_embedding: "embedding",
  };

  function isAiReady(jobKey: string): boolean {
    const feature = JOB_AI_FEATURE[jobKey];
    if (!feature) return true;
    return aiStatus?.[feature] ?? false;
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
  <title>{m.admin_jobs_title()}</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
  <div class="mb-8">
    <div class="mb-1">
      <BackButton href="/admin" label={m.nav_admin()} />
    </div>
    <h1 class="text-3xl font-bold text-foreground">{m.admin_jobs_heading()}</h1>
    <p class="text-muted-foreground mt-1">
      {m.admin_jobs_subtitle()}
    </p>
  </div>

  {#if loading}
    <FormSkeleton cards={6} />
  {:else}
    <div class="space-y-3">
      {#each jobs as job (job.key)}
        {@const Icon = JOB_ICONS[job.key] ?? FileText}
        {@const isTriggering = triggeringJob === job.key}
        {@const running = job.pending > 0}

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
                  {m.admin_jobs_ai_badge()}
                </span>
              {/if}
              {#if running}
                <LoaderCircle
                  class="text-primary animate-spin shrink-0"
                  size={15}
                />
              {/if}
            </div>

            <p class="text-muted-foreground text-sm mt-1 mb-4 ml-[1.75rem]">
              {job.description}
            </p>

            <!-- Status bar -->
            <div
              class="inline-flex items-stretch rounded-lg overflow-hidden border border-border/50"
            >
              <div
                class="flex items-center gap-2 sm:gap-5 px-2.5 sm:px-3.5 py-2"
              >
                <span class="text-xs sm:text-sm text-muted-foreground"
                  >{m.admin_jobs_status_missing()}</span
                >
                <span
                  class="text-xs sm:text-sm font-semibold text-foreground font-sans tabular-nums"
                >
                  {job.missing.toLocaleString()}
                </span>
              </div>
              {#if running}
                <div class="w-px bg-border/50"></div>
                <div
                  class="flex items-center gap-2 sm:gap-5 px-2.5 sm:px-3.5 py-2 bg-primary/5"
                >
                  <span class="text-xs sm:text-sm text-primary"
                    >{m.admin_jobs_status_pending()}</span
                  >
                  <span
                    class="text-xs sm:text-sm font-semibold text-primary font-sans tabular-nums"
                  >
                    {job.pending.toLocaleString()}
                  </span>
                </div>
              {/if}
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
                title={m.admin_jobs_stop()}
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
                  >{m.admin_jobs_stop_label()}</span
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
                  ? m.admin_jobs_ai_not_configured()
                  : m.admin_jobs_run_tooltip()}
              >
                {#if isTriggering}
                  <LoaderCircle class="text-primary animate-spin" size={18} />
                {:else}
                  <ScanSearch size={18} class="text-muted-foreground" />
                {/if}
                <span
                  class="text-xs text-muted-foreground font-sans font-medium"
                  >{m.admin_jobs_run_label()}</span
                >
              </button>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
