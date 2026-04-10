<script lang="ts">
  import { onMount } from "svelte";
  import { adminApi } from "$lib/api/admin";
  import { toastStore } from "$lib/stores/toast";
  import type { LlmUsageResponse, LlmUsageByFeature } from "$lib/types";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import { TableSkeleton } from "$lib/components/skeletons";
  import BackButton from "$lib/components/BackButton.svelte";
  import * as m from "$lib/paraglide/messages.js";

  let data = $state<LlmUsageResponse | null>(null);
  let loading = $state(true);
  let period = $state("month");

  const FEATURE_LABELS = $derived<Record<string, string>>({
    companion: m.admin_llm_feat_companion(),
    auto_tag: m.admin_llm_feat_tagging(),
    summarize: m.admin_llm_feat_summarization(),
    embedding: m.admin_llm_feat_embedding(),
    illustration: m.admin_llm_feat_illustration(),
    search: m.admin_llm_feat_search(),
  });

  function formatTokens(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return n.toString();
  }

  function formatCost(n: number): string {
    if (n === 0) return "$0.00";
    if (n < 0.01) return `$${n.toFixed(4)}`;
    return `$${n.toFixed(2)}`;
  }

  async function loadUsage() {
    loading = true;
    try {
      data = await adminApi.getLlmUsage(period);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  onMount(async () => {
    await loadUsage();
  });

  function handlePeriodChange(newPeriod: string) {
    period = newPeriod;
    loadUsage();
  }
</script>

<svelte:head>
  <title>{m.admin_llm_title()}</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
  <!-- Header -->
  <div class="mb-8">
    <div class="mb-1">
      <BackButton href="/admin" label={m.nav_admin()} />
    </div>
    <h1 class="text-3xl font-bold text-foreground">{m.admin_llm_heading()}</h1>
    <p class="text-muted-foreground mt-1">
      {m.admin_llm_subtitle()}
    </p>
  </div>

  <!-- Period selector -->
  <div class="flex gap-2 mb-6">
    {#each [["day", "24h"], ["week", "7d"], ["month", "30d"]] as [value, label]}
      <button
        class="px-4 py-1.5 rounded-lg text-sm font-medium transition-colors {period ===
        value
          ? 'bg-primary text-primary-foreground'
          : 'bg-muted text-muted-foreground hover:text-foreground'}"
        onclick={() => handlePeriodChange(value)}
      >
        {label}
      </button>
    {/each}
  </div>

  {#if loading}
    <div role="status" aria-label="Loading">
      <!-- 5 stat cards -->
      <div class="grid grid-cols-2 sm:grid-cols-5 gap-4 mb-8">
        {#each Array(5) as _}
          <div
            class="bg-card card-soft rounded-2xl p-5 flex flex-col items-center"
          >
            <Skeleton class="h-7 w-20 mb-1.5" />
            <Skeleton class="h-4 w-16" />
          </div>
        {/each}
      </div>
      <!-- By User table -->
      <div class="mb-8">
        <Skeleton class="h-6 w-20 mb-4" />
        <TableSkeleton rows={3} columns={5} />
      </div>
      <!-- By Feature table -->
      <div class="mb-8">
        <Skeleton class="h-6 w-24 mb-4" />
        <TableSkeleton rows={6} columns={7} />
      </div>
    </div>
  {:else if data}
    <!-- Totals -->
    <div class="grid grid-cols-2 sm:grid-cols-5 gap-4 mb-8">
      <div class="bg-card card-soft rounded-2xl p-5 text-center">
        <p class="text-2xl font-bold text-foreground">
          {formatCost(data.totals.estimated_cost)}
        </p>
        <p class="text-muted-foreground text-sm mt-0.5">
          {m.admin_llm_est_cost()}
        </p>
      </div>
      <div class="bg-card card-soft rounded-2xl p-5 text-center">
        <p class="text-2xl font-bold text-foreground">
          {formatTokens(data.totals.total_tokens)}
        </p>
        <p class="text-muted-foreground text-sm mt-0.5">
          {m.admin_llm_total_tokens()}
        </p>
      </div>
      <div class="bg-card card-soft rounded-2xl p-5 text-center">
        <p class="text-2xl font-bold text-foreground">
          {formatTokens(data.totals.input_tokens)}
        </p>
        <p class="text-muted-foreground text-sm mt-0.5">
          {m.admin_llm_input_tokens()}
        </p>
      </div>
      <div class="bg-card card-soft rounded-2xl p-5 text-center">
        <p class="text-2xl font-bold text-foreground">
          {formatTokens(data.totals.output_tokens)}
        </p>
        <p class="text-muted-foreground text-sm mt-0.5">
          {m.admin_llm_output_tokens()}
        </p>
      </div>
      <div class="bg-card card-soft rounded-2xl p-5 text-center">
        <p class="text-2xl font-bold text-foreground">
          {data.totals.call_count.toLocaleString()}
        </p>
        <p class="text-muted-foreground text-sm mt-0.5">
          {m.admin_llm_api_calls()}
        </p>
      </div>
    </div>

    <!-- By User -->
    <div class="mb-8">
      <h2 class="text-lg font-semibold text-foreground mb-4">
        {m.admin_llm_by_user()}
      </h2>
      {#if data.by_user.length === 0}
        <div class="bg-card card-soft rounded-2xl p-8 text-center">
          <p class="text-muted-foreground">{m.admin_llm_by_user_empty()}</p>
        </div>
      {:else}
        <div class="bg-card card-soft rounded-2xl overflow-x-auto">
          <table class="w-full text-sm whitespace-nowrap">
            <thead>
              <tr class="border-b border-border text-left">
                <th class="px-4 py-3 font-medium text-muted-foreground"
                  >{m.admin_llm_col_user()}</th
                >
                <th
                  class="px-4 py-3 font-medium text-muted-foreground text-right"
                  >{m.admin_llm_col_input()}</th
                >
                <th
                  class="px-4 py-3 font-medium text-muted-foreground text-right"
                  >{m.admin_llm_col_output()}</th
                >
                <th
                  class="px-4 py-3 font-medium text-muted-foreground text-right"
                  >{m.admin_llm_col_total()}</th
                >
                <th
                  class="px-4 py-3 font-medium text-muted-foreground text-right"
                  >{m.admin_llm_col_calls()}</th
                >
              </tr>
            </thead>
            <tbody>
              {#each data.by_user as row}
                <tr class="border-b border-border/50 last:border-0">
                  <td class="px-4 py-3 font-medium text-foreground"
                    >{row.username}</td
                  >
                  <td class="px-4 py-3 text-right tabular-nums text-foreground"
                    >{formatTokens(row.input_tokens)}</td
                  >
                  <td class="px-4 py-3 text-right tabular-nums text-foreground"
                    >{formatTokens(row.output_tokens)}</td
                  >
                  <td
                    class="px-4 py-3 text-right tabular-nums font-medium text-foreground"
                    >{formatTokens(row.total_tokens)}</td
                  >
                  <td
                    class="px-4 py-3 text-right tabular-nums text-muted-foreground"
                    >{row.call_count.toLocaleString()}</td
                  >
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </div>

    <!-- By Feature -->
    <div class="mb-8">
      <h2 class="text-lg font-semibold text-foreground mb-4">By Feature</h2>
      {#if data.by_feature.length === 0}
        <div class="bg-card card-soft rounded-2xl p-8 text-center">
          <p class="text-muted-foreground">
            No usage data yet. AI features will log usage here when used.
          </p>
        </div>
      {:else}
        <div class="bg-card card-soft rounded-2xl overflow-x-auto">
          <table class="w-full text-sm whitespace-nowrap">
            <thead>
              <tr class="border-b border-border text-left">
                <th class="px-4 py-3 font-medium text-muted-foreground"
                  >Feature</th
                >
                <th class="px-4 py-3 font-medium text-muted-foreground"
                  >Model</th
                >
                <th
                  class="px-4 py-3 font-medium text-muted-foreground text-right"
                  >Input</th
                >
                <th
                  class="px-4 py-3 font-medium text-muted-foreground text-right"
                  >Output</th
                >
                <th
                  class="px-4 py-3 font-medium text-muted-foreground text-right"
                  >Total</th
                >
                <th
                  class="px-4 py-3 font-medium text-muted-foreground text-right"
                  >Calls</th
                >
                <th
                  class="px-4 py-3 font-medium text-muted-foreground text-right"
                  >Est. Cost</th
                >
              </tr>
            </thead>
            <tbody>
              {#each data.by_feature as row}
                <tr class="border-b border-border/50 last:border-0">
                  <td class="px-4 py-3 font-medium text-foreground"
                    >{FEATURE_LABELS[row.feature] ?? row.feature}</td
                  >
                  <td class="px-4 py-3 text-muted-foreground">{row.model}</td>
                  <td class="px-4 py-3 text-right tabular-nums text-foreground"
                    >{formatTokens(row.input_tokens)}</td
                  >
                  <td class="px-4 py-3 text-right tabular-nums text-foreground"
                    >{formatTokens(row.output_tokens)}</td
                  >
                  <td
                    class="px-4 py-3 text-right tabular-nums font-medium text-foreground"
                    >{formatTokens(row.total_tokens)}</td
                  >
                  <td
                    class="px-4 py-3 text-right tabular-nums text-muted-foreground"
                    >{row.call_count.toLocaleString()}</td
                  >
                  <td
                    class="px-4 py-3 text-right tabular-nums font-medium text-foreground"
                    >{formatCost(row.estimated_cost)}</td
                  >
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </div>
  {/if}
</div>
