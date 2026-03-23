<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { adminApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import type { JobStatus } from "$lib/types";
  import { UserRole } from "$lib/types";
  import {
    FileText,
    Search,
    BookOpen,
    Tags,
    Hash,
    Infinity,
    ScanSearch,
    LoaderCircle,
    Square,
    Clock,
  } from "@lucide/svelte";
  import { FormSkeleton } from "$lib/components/skeletons";

  let jobs = $state<JobStatus[]>([]);
  let loading = $state(true);
  let triggeringJob = $state<string | null>(null);
  let stoppingJob = $state<string | null>(null);
  let pollInterval: ReturnType<typeof setInterval> | null = null;

  const JOB_ICONS: Record<string, typeof FileText> = {
    text_extraction: FileText,
    embedding: Search,
    summarize: BookOpen,
    summary_embedding: ScanSearch,
    auto_tag: Tags,
    word_count: Hash,
  };

  async function fetchJobs() {
    if (!$authStore.token) return;
    try {
      const res = await adminApi.getJobs($authStore.token);
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
    if (!$authStore.token) return;
    stoppingJob = jobType;
    try {
      await adminApi.stopJob(jobType, $authStore.token);
      toastStore.success(`Job stopped: ${jobType}`);
      await fetchJobs();
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      stoppingJob = null;
    }
  }

  async function triggerJob(jobType: string, mode: string) {
    if (!$authStore.token) return;
    triggeringJob = `${jobType}:${mode}`;
    try {
      await adminApi.triggerJob(jobType, mode, $authStore.token);
      toastStore.success(`Job started: ${jobType} (${mode})`);
      await fetchJobs();
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      triggeringJob = null;
    }
  }

  onMount(async () => {
    if (!$authStore.user || $authStore.user.role !== UserRole.Admin) {
      goto("/");
      return;
    }
    await fetchJobs();
    pollInterval = setInterval(fetchJobs, 3000);
  });

  onDestroy(() => {
    if (pollInterval) clearInterval(pollInterval);
  });
</script>

<svelte:head>
  <title>Jobs - Admin - BeePub</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
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
        {@const isTriggering =
          triggeringJob === `${job.key}:all` ||
          triggeringJob === `${job.key}:missing`}
        {@const progressPct =
          job.progress && job.progress.total > 0
            ? Math.round((job.progress.processed / job.progress.total) * 100)
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
              {#if job.progress?.status === "pending"}
                <Clock class="text-primary shrink-0" size={15} />
              {:else if job.active}
                <LoaderCircle
                  class="text-primary animate-spin shrink-0"
                  size={15}
                />
              {:else if job.progress?.status === "failed"}
                <span class="text-xs text-destructive font-medium">Failed</span>
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
                class="flex items-center gap-2 sm:gap-5 px-2.5 sm:px-3.5 py-2 bg-muted/50"
              >
                <span class="text-xs sm:text-sm text-muted-foreground"
                  >Active</span
                >
                <span
                  class="text-xs sm:text-sm font-semibold text-foreground font-sans tabular-nums"
                >
                  {#if job.active && job.progress}
                    {job.progress.processed.toLocaleString()}/{job.progress.total.toLocaleString()}
                  {:else}
                    0
                  {/if}
                </span>
              </div>
              <div class="w-px bg-border/50"></div>
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
            </div>

            {#if job.active && job.progress && job.progress.failed > 0}
              <p class="text-xs text-muted-foreground mt-3">
                {job.progress.failed} failed
              </p>
            {/if}
          </div>

          <!-- Action buttons -->
          <div
            class="flex flex-col border-l border-border/50 shrink-0 w-[4.5rem] sm:w-20"
          >
            {#if job.active}
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
                disabled={isTriggering}
                onclick={() => triggerJob(job.key, "all")}
                title="Process all books"
              >
                <Infinity size={18} class="text-muted-foreground" />
                <span
                  class="text-xs text-muted-foreground font-sans font-medium"
                  >All</span
                >
              </button>
              <div class="h-px bg-border/50"></div>
              <button
                class="flex-1 flex flex-col items-center justify-center gap-1.5 hover:bg-muted/60 active:bg-muted transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                disabled={isTriggering || job.missing === 0}
                onclick={() => triggerJob(job.key, "missing")}
                title="Process only unprocessed books"
              >
                <ScanSearch size={18} class="text-muted-foreground" />
                <span
                  class="text-xs text-muted-foreground font-sans font-medium"
                  >Missing</span
                >
              </button>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
