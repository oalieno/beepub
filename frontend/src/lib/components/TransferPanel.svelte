<script lang="ts">
  /**
   * The transfer panel: downloads, catalog imports and uploads, each with
   * its outcome, until the reader closes it. Desktop: a card in the
   * bottom-right corner that folds to its summary. Phone: a bar above the
   * bottom bar that opens the list as a sheet.
   */
  import { goto } from "$app/navigation";
  import {
    BookCheck,
    Check,
    ChevronDown,
    ChevronUp,
    CircleAlert,
    Clock,
    Loader2,
    RotateCw,
    X,
  } from "@lucide/svelte";
  import BottomSheet from "$lib/components/BottomSheet.svelte";
  import { keyboardVisible } from "$lib/stores/keyboard";
  import {
    clearSettledTransfers,
    transferSummary,
    transfers,
    transfersCollapsed,
    type Transfer,
    type TransferKind,
  } from "$lib/stores/transfers";
  import * as m from "$lib/paraglide/messages.js";

  let {
    /** Height of the phone's bottom chrome the bar sits above. */
    bottomChrome = 56,
  }: { bottomChrome?: number } = $props();

  let sheetOpen = $state(false);
  let cardHeight = $state(0);
  let barHeight = $state(0);

  let visible = $derived($transfers.length > 0);
  let settled = $derived($transferSummary.active === 0);

  const activeLabel: Record<
    TransferKind,
    (n: { done: string; total: string }) => string
  > = {
    download: m.transfers_active_download,
    import: m.transfers_active_import,
    upload: m.transfers_active_upload,
  };
  const doneLabel: Record<TransferKind, () => string> = {
    download: m.transfers_row_downloaded,
    import: m.transfers_row_imported,
    upload: m.transfers_row_uploaded,
  };

  let summary = $derived.by(() => {
    const s = $transferSummary;
    if (s.active > 0) {
      const kinds = new Set($transfers.map((t) => t.kind));
      const counts = { done: String(s.settled), total: String(s.total) };
      return kinds.size === 1
        ? activeLabel[[...kinds][0]](counts)
        : m.transfers_active_mixed(counts);
    }
    return s.failed > 0
      ? m.transfers_settled_failed({
          done: String(s.total - s.failed),
          failed: String(s.failed),
        })
      : m.transfers_settled({ count: String(s.total) });
  });

  // Overall progress for the phone bar: finished items plus the fraction
  // of the one in flight.
  let overall = $derived.by(() => {
    const s = $transferSummary;
    if (s.total === 0) return 0;
    const partial = (s.running?.progress ?? 0) / 100;
    return Math.min(1, (s.settled + partial) / s.total);
  });

  // Toasts rise above whatever of the panel is showing.
  $effect(() => {
    const lift = visible ? Math.max(cardHeight, barHeight) + 8 : 0;
    document.documentElement.style.setProperty(
      "--transfer-offset",
      `${lift}px`,
    );
  });

  function close() {
    clearSettledTransfers();
    sheetOpen = false;
  }

  function open(item: Transfer) {
    if (!item.href) return;
    sheetOpen = false;
    goto(item.href);
  }
</script>

{#snippet row(item: Transfer)}
  <li class="flex items-center gap-3 px-4 py-2.5">
    <div class="flex-1 min-w-0">
      {#if item.href && (item.status === "done" || item.status === "duplicate")}
        <button
          class="block w-full text-left text-sm truncate text-foreground hover:underline"
          onclick={() => open(item)}>{item.title}</button
        >
      {:else}
        <p class="text-sm truncate text-foreground">{item.title}</p>
      {/if}
      {#if item.status === "running" && item.progress != null}
        <div class="mt-1.5 h-1 rounded-full bg-secondary overflow-hidden">
          <div
            class="h-full bg-primary transition-[width] duration-300"
            style="width: {item.progress}%"
          ></div>
        </div>
      {:else if item.status === "failed" && item.error}
        <p class="text-xs text-muted-foreground truncate" title={item.error}>
          {item.error}
        </p>
      {/if}
    </div>
    <div class="shrink-0 flex items-center gap-1.5 text-xs">
      {#if item.status === "queued"}
        <span class="inline-flex items-center gap-1 text-muted-foreground">
          <Clock size={14} />{m.transfers_row_queued()}
        </span>
      {:else if item.status === "running"}
        <span class="inline-flex items-center gap-1 text-primary tabular-nums">
          <Loader2 size={14} class="animate-spin" />
          {#if item.progress != null}{item.progress}%{/if}
        </span>
      {:else if item.status === "done"}
        <span class="inline-flex items-center gap-1 text-primary font-medium">
          <Check size={14} strokeWidth={3} />{doneLabel[item.kind]()}
        </span>
      {:else if item.status === "duplicate"}
        <span class="inline-flex items-center gap-1 text-foreground">
          <BookCheck size={14} />{m.transfers_row_duplicate()}
        </span>
      {:else}
        <span class="inline-flex items-center gap-1 text-destructive">
          <CircleAlert size={14} />{m.transfers_row_failed()}
        </span>
        {#if item.retry}
          <button
            class="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary"
            title={m.common_retry()}
            aria-label={m.common_retry()}
            onclick={() => item.retry?.()}
          >
            <RotateCw size={14} />
          </button>
        {/if}
      {/if}
    </div>
  </li>
{/snippet}

{#snippet closeButton()}
  <!-- Nothing running: the panel can go. Running work only folds away. -->
  {#if settled}
    <button
      class="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary"
      aria-label={m.common_close()}
      title={m.common_close()}
      onclick={(e) => {
        e.stopPropagation();
        close();
      }}
    >
      <X size={16} />
    </button>
  {/if}
{/snippet}

{#if visible}
  <!-- Desktop card -->
  <section
    class="hidden md:block fixed right-6 bottom-0 z-40 w-96 bg-card border border-b-0 border-border rounded-t-2xl shadow-[0_-4px_24px_rgb(0_0_0/0.12)] overflow-hidden"
    style="padding-bottom: env(safe-area-inset-bottom, 0px);"
    aria-label={m.transfers_panel()}
    bind:offsetHeight={cardHeight}
  >
    <!-- Drive-style: anchored to the bottom edge, a tinted header. -->
    <header
      class="flex items-center gap-2 pl-4 pr-3 py-3 bg-[color-mix(in_srgb,var(--primary)_12%,var(--card))]"
    >
      <p
        class="flex-1 min-w-0 text-[15px] font-semibold truncate"
        role="status"
      >
        {summary}
      </p>
      <button
        class="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary"
        aria-label={$transfersCollapsed
          ? m.transfers_expand()
          : m.transfers_collapse()}
        title={$transfersCollapsed
          ? m.transfers_expand()
          : m.transfers_collapse()}
        onclick={() => transfersCollapsed.update((v) => !v)}
      >
        {#if $transfersCollapsed}<ChevronUp size={16} />{:else}<ChevronDown
            size={16}
          />{/if}
      </button>
      {@render closeButton()}
    </header>
    {#if !$transfersCollapsed}
      <ul class="max-h-72 overflow-y-auto py-1">
        {#each $transfers as item (item.id)}
          {@render row(item)}
        {/each}
      </ul>
    {/if}
  </section>

  <!-- Phone bar -->
  {#if !$keyboardVisible}
    <div
      class="md:hidden fixed left-4 right-4 z-40"
      style="bottom: calc({bottomChrome}px + env(safe-area-inset-bottom, 0px) + 8px);"
      bind:offsetHeight={barHeight}
    >
      <div
        role="button"
        tabindex="0"
        class="flex items-center gap-3 pl-4 pr-2 h-11 bg-card border border-border rounded-2xl shadow-lg overflow-hidden relative cursor-pointer"
        aria-label={m.transfers_panel()}
        onclick={() => (sheetOpen = true)}
        onkeydown={(e) => e.key === "Enter" && (sheetOpen = true)}
      >
        {#if !settled}
          <Loader2 size={16} class="animate-spin text-primary shrink-0" />
        {:else if $transferSummary.failed > 0}
          <CircleAlert size={16} class="text-destructive shrink-0" />
        {:else}
          <Check size={16} strokeWidth={3} class="text-primary shrink-0" />
        {/if}
        <p class="flex-1 min-w-0 text-sm font-medium truncate" role="status">
          {summary}
        </p>
        <ChevronUp size={16} class="text-muted-foreground shrink-0" />
        {@render closeButton()}
        {#if !settled}
          <div class="absolute left-0 right-0 bottom-0 h-0.5 bg-secondary">
            <div
              class="h-full bg-primary transition-[width] duration-300"
              style="width: {overall * 100}%"
            ></div>
          </div>
        {/if}
      </div>
    </div>
  {/if}
{/if}

<BottomSheet bind:open={sheetOpen}>
  <div class="flex items-center gap-2 pb-2">
    <p class="flex-1 min-w-0 text-base font-semibold truncate">{summary}</p>
    {@render closeButton()}
  </div>
  <ul class="-mx-4 max-h-[60dvh] overflow-y-auto pb-2">
    {#each $transfers as item (item.id)}
      {@render row(item)}
    {/each}
  </ul>
</BottomSheet>
