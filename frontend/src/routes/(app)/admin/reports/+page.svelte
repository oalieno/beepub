<script lang="ts">
  import { onMount } from "svelte";
  import { adminApi } from "$lib/api/admin";
  import { coverUrl } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import { toastStore } from "$lib/stores/toast";
  import type { BookReport } from "$lib/types";
  import { Check, Flag, CircleCheck } from "@lucide/svelte";
  import { TableSkeleton } from "$lib/components/skeletons";
  import * as m from "$lib/paraglide/messages.js";

  let ISSUE_LABELS = $derived<Record<string, string>>({
    corrupt_file: m.admin_reports_corrupt_file(),
    wrong_metadata: m.admin_reports_wrong_metadata(),
    cant_open: m.admin_reports_cant_open(),
    other: m.admin_reports_other(),
  });

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
  <title>{m.admin_reports_title()}</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
  <div class="mb-8">
    <a
      href="/admin"
      class="text-muted-foreground hover:text-foreground text-sm mb-1 inline-block"
      >{m.admin_llm_back()}</a
    >
    <h1 class="text-3xl font-bold text-foreground">
      {m.admin_reports_heading()}
    </h1>
    <p class="text-muted-foreground mt-1">
      {m.admin_reports_subtitle()}
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
      {m.admin_reports_unresolved()}
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
      {m.admin_reports_resolved()}
    </button>
  </div>

  {#if loading}
    <TableSkeleton />
  {:else if reports.length === 0}
    <div class="text-center py-16 text-muted-foreground">
      {#if filter === "unresolved"}
        <CircleCheck size={40} class="mx-auto mb-3 opacity-30" />
        <p>{m.admin_reports_empty_unresolved()}</p>
      {:else}
        <Flag size={40} class="mx-auto mb-3 opacity-30" />
        <p>{m.admin_reports_empty_resolved()}</p>
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
                {report.book_title || m.admin_reports_unknown_book()}
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
                    {m.admin_reports_system()}
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
