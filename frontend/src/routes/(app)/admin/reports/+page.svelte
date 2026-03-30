<script lang="ts">
  import { onMount } from "svelte";
  import { adminApi } from "$lib/api/bookshelves";
  import { coverUrl } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import { toastStore } from "$lib/stores/toast";
  import type { BookReport } from "$lib/types";
  import { Check, Flag, CircleCheck } from "@lucide/svelte";
  import { TableSkeleton } from "$lib/components/skeletons";

  const ISSUE_LABELS: Record<string, string> = {
    corrupt_file: "Corrupt file",
    wrong_metadata: "Wrong metadata",
    cant_open: "Can't open",
    other: "Other",
  };

  let reports = $state<BookReport[]>([]);
  let loading = $state(true);
  let filter = $state<"unresolved" | "resolved">("unresolved");

  onMount(async () => {
    await loadReports();
  });

  async function loadReports() {
    loading = true;
    try {
      reports = await adminApi.getReports(filter === "resolved");
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleResolve(reportId: string) {
    try {
      await adminApi.resolveReport(reportId);
      reports = reports.filter((r) => r.id !== reportId);
      toastStore.success("Report resolved");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>Book Reports - Admin - BeePub</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6 mx-auto" style="max-width: 1000px;">
  <div class="mb-8">
    <a
      href="/admin"
      class="text-muted-foreground hover:text-foreground text-sm mb-1 inline-block"
      >&larr; Admin</a
    >
    <h1 class="text-3xl font-bold text-foreground">Book Reports</h1>
    <p class="text-muted-foreground mt-1">
      User-reported and system-detected book issues
    </p>
  </div>

  <!-- Filter tabs -->
  <div class="flex gap-1 mb-6 bg-secondary/50 rounded-xl p-1 w-fit">
    <button
      class="px-4 py-2 text-sm font-medium rounded-lg transition-colors {filter ===
      'unresolved'
        ? 'bg-card text-foreground shadow-sm'
        : 'text-muted-foreground hover:text-foreground'}"
      onclick={() => {
        filter = "unresolved";
        loadReports();
      }}
    >
      Unresolved
    </button>
    <button
      class="px-4 py-2 text-sm font-medium rounded-lg transition-colors {filter ===
      'resolved'
        ? 'bg-card text-foreground shadow-sm'
        : 'text-muted-foreground hover:text-foreground'}"
      onclick={() => {
        filter = "resolved";
        loadReports();
      }}
    >
      Resolved
    </button>
  </div>

  {#if loading}
    <TableSkeleton />
  {:else if reports.length === 0}
    <div class="text-center py-16 text-muted-foreground">
      {#if filter === "unresolved"}
        <CircleCheck size={40} class="mx-auto mb-3 opacity-30" />
        <p>No unresolved reports</p>
      {:else}
        <Flag size={40} class="mx-auto mb-3 opacity-30" />
        <p>No resolved reports</p>
      {/if}
    </div>
  {:else}
    <div class="space-y-3">
      {#each reports as report (report.id)}
        <div
          class="bg-card card-soft rounded-2xl overflow-hidden flex border border-border/50"
        >
          <div
            class="flex-1 px-5 py-4 sm:px-6 sm:py-5 min-w-0 flex items-start gap-4"
          >
            <!-- Book cover -->
            {#if report.book_cover}
              <a href="/books/{report.book_id}" class="shrink-0">
                <img
                  use:authedSrc={coverUrl(report.book_id)}
                  alt=""
                  class="w-12 h-[4.25rem] object-cover rounded-lg shadow-sm"
                />
              </a>
            {:else}
              <div class="w-12 h-[4.25rem] bg-muted rounded-lg shrink-0"></div>
            {/if}

            <!-- Report info -->
            <div class="flex-1 min-w-0">
              <a
                href="/books/{report.book_id}"
                class="font-semibold text-foreground hover:text-primary transition-colors line-clamp-1 text-base"
              >
                {report.book_title || "Unknown book"}
              </a>
              <div class="flex flex-wrap items-center gap-2 mt-1.5">
                <span
                  class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[11px] font-semibold uppercase tracking-wide leading-none
                    {report.issue_type === 'corrupt_file'
                    ? 'bg-destructive/15 text-destructive'
                    : 'bg-secondary text-secondary-foreground'}"
                >
                  {ISSUE_LABELS[report.issue_type] || report.issue_type}
                </span>
                <span class="text-xs text-muted-foreground">
                  {#if report.reporter_name}
                    {report.reporter_name}
                  {:else}
                    system
                  {/if}
                  &middot;
                  {new Date(report.created_at).toLocaleDateString()}
                </span>
              </div>
              {#if report.description}
                <p class="text-sm text-muted-foreground mt-2 line-clamp-2">
                  {report.description}
                </p>
              {/if}
            </div>
          </div>

          <!-- Resolve action -->
          {#if !report.resolved}
            <button
              class="shrink-0 px-4 flex items-center justify-center border-l border-border/50 text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors"
              title="Resolve"
              onclick={() => handleResolve(report.id)}
            >
              <Check size={18} />
            </button>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>
