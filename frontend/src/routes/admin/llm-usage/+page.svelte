<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { adminApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import type { LlmUsageResponse, LlmUsageByFeature } from "$lib/types";
  import { UserRole } from "$lib/types";
  import { ArrowLeft } from "@lucide/svelte";
  import Spinner from "$lib/components/Spinner.svelte";

  let data = $state<LlmUsageResponse | null>(null);
  let loading = $state(true);
  let period = $state("month");

  const FEATURE_LABELS: Record<string, string> = {
    companion: "Companion Chat",
    auto_tag: "Auto Tagging",
    summarize: "Summarization",
    embedding: "Embedding",
    illustration: "Illustration",
    search: "Semantic Search",
  };

  function formatTokens(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return n.toString();
  }

  async function loadUsage() {
    if (!$authStore.token) return;
    loading = true;
    try {
      data = await adminApi.getLlmUsage($authStore.token, period);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  onMount(async () => {
    if (!$authStore.user || $authStore.user.role !== UserRole.Admin) {
      goto("/");
      return;
    }
    await loadUsage();
  });

  function handlePeriodChange(newPeriod: string) {
    period = newPeriod;
    loadUsage();
  }
</script>

<svelte:head>
  <title>LLM Usage - Admin - BeePub</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
  <!-- Header -->
  <div class="mb-8 flex items-center gap-3">
    <a
      href="/admin"
      class="p-2 rounded-xl hover:bg-muted transition-colors"
    >
      <ArrowLeft size={20} class="text-muted-foreground" />
    </a>
    <div>
      <h1 class="text-3xl font-bold text-foreground">LLM Usage</h1>
      <p class="text-muted-foreground mt-1">Token consumption across AI features</p>
    </div>
  </div>

  <!-- Period selector -->
  <div class="flex gap-2 mb-6">
    {#each [["day", "24h"], ["week", "7d"], ["month", "30d"]] as [value, label]}
      <button
        class="px-4 py-1.5 rounded-lg text-sm font-medium transition-colors {period === value ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-foreground'}"
        onclick={() => handlePeriodChange(value)}
      >
        {label}
      </button>
    {/each}
  </div>

  {#if loading}
    <div class="flex items-center justify-center h-40">
      <Spinner size="lg" />
    </div>
  {:else if data}
    <!-- Totals -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
      <div class="bg-card card-soft rounded-2xl p-5 text-center">
        <p class="text-2xl font-bold text-foreground">{formatTokens(data.totals.total_tokens)}</p>
        <p class="text-muted-foreground text-sm mt-0.5">Total Tokens</p>
      </div>
      <div class="bg-card card-soft rounded-2xl p-5 text-center">
        <p class="text-2xl font-bold text-foreground">{formatTokens(data.totals.input_tokens)}</p>
        <p class="text-muted-foreground text-sm mt-0.5">Input Tokens</p>
      </div>
      <div class="bg-card card-soft rounded-2xl p-5 text-center">
        <p class="text-2xl font-bold text-foreground">{formatTokens(data.totals.output_tokens)}</p>
        <p class="text-muted-foreground text-sm mt-0.5">Output Tokens</p>
      </div>
      <div class="bg-card card-soft rounded-2xl p-5 text-center">
        <p class="text-2xl font-bold text-foreground">{data.totals.call_count.toLocaleString()}</p>
        <p class="text-muted-foreground text-sm mt-0.5">API Calls</p>
      </div>
    </div>

    <!-- By User -->
    <div class="mb-8">
      <h2 class="text-lg font-semibold text-foreground mb-4">By User</h2>
      {#if data.by_user.length === 0}
        <div class="bg-card card-soft rounded-2xl p-8 text-center">
          <p class="text-muted-foreground">No per-user usage data yet.</p>
        </div>
      {:else}
        <div class="bg-card card-soft rounded-2xl overflow-hidden">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-border text-left">
                <th class="px-4 py-3 font-medium text-muted-foreground">User</th>
                <th class="px-4 py-3 font-medium text-muted-foreground text-right">Input</th>
                <th class="px-4 py-3 font-medium text-muted-foreground text-right">Output</th>
                <th class="px-4 py-3 font-medium text-muted-foreground text-right">Total</th>
                <th class="px-4 py-3 font-medium text-muted-foreground text-right">Calls</th>
              </tr>
            </thead>
            <tbody>
              {#each data.by_user as row}
                <tr class="border-b border-border/50 last:border-0">
                  <td class="px-4 py-3 font-medium text-foreground">{row.username}</td>
                  <td class="px-4 py-3 text-right tabular-nums text-foreground">{formatTokens(row.input_tokens)}</td>
                  <td class="px-4 py-3 text-right tabular-nums text-foreground">{formatTokens(row.output_tokens)}</td>
                  <td class="px-4 py-3 text-right tabular-nums font-medium text-foreground">{formatTokens(row.total_tokens)}</td>
                  <td class="px-4 py-3 text-right tabular-nums text-muted-foreground">{row.call_count.toLocaleString()}</td>
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
          <p class="text-muted-foreground">No usage data yet. AI features will log usage here when used.</p>
        </div>
      {:else}
        <div class="bg-card card-soft rounded-2xl overflow-hidden">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-border text-left">
                <th class="px-4 py-3 font-medium text-muted-foreground">Feature</th>
                <th class="px-4 py-3 font-medium text-muted-foreground">Model</th>
                <th class="px-4 py-3 font-medium text-muted-foreground text-right">Input</th>
                <th class="px-4 py-3 font-medium text-muted-foreground text-right">Output</th>
                <th class="px-4 py-3 font-medium text-muted-foreground text-right">Total</th>
                <th class="px-4 py-3 font-medium text-muted-foreground text-right">Calls</th>
              </tr>
            </thead>
            <tbody>
              {#each data.by_feature as row}
                <tr class="border-b border-border/50 last:border-0">
                  <td class="px-4 py-3 font-medium text-foreground">{FEATURE_LABELS[row.feature] ?? row.feature}</td>
                  <td class="px-4 py-3 text-muted-foreground">{row.model}</td>
                  <td class="px-4 py-3 text-right tabular-nums text-foreground">{formatTokens(row.input_tokens)}</td>
                  <td class="px-4 py-3 text-right tabular-nums text-foreground">{formatTokens(row.output_tokens)}</td>
                  <td class="px-4 py-3 text-right tabular-nums font-medium text-foreground">{formatTokens(row.total_tokens)}</td>
                  <td class="px-4 py-3 text-right tabular-nums text-muted-foreground">{row.call_count.toLocaleString()}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </div>

    <!-- By Day -->
    {#if data.by_day.length > 0}
      <div>
        <h2 class="text-lg font-semibold text-foreground mb-4">Daily Breakdown</h2>
        <div class="bg-card card-soft rounded-2xl overflow-hidden">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-border text-left">
                <th class="px-4 py-3 font-medium text-muted-foreground">Date</th>
                <th class="px-4 py-3 font-medium text-muted-foreground">Feature</th>
                <th class="px-4 py-3 font-medium text-muted-foreground text-right">Total Tokens</th>
                <th class="px-4 py-3 font-medium text-muted-foreground text-right">Calls</th>
              </tr>
            </thead>
            <tbody>
              {#each data.by_day as row}
                <tr class="border-b border-border/50 last:border-0">
                  <td class="px-4 py-3 text-foreground">{row.day ? new Date(row.day).toLocaleDateString() : "—"}</td>
                  <td class="px-4 py-3 text-muted-foreground">{FEATURE_LABELS[row.feature] ?? row.feature}</td>
                  <td class="px-4 py-3 text-right tabular-nums font-medium text-foreground">{formatTokens(row.total_tokens)}</td>
                  <td class="px-4 py-3 text-right tabular-nums text-muted-foreground">{row.call_count.toLocaleString()}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
    {/if}
  {/if}
</div>
