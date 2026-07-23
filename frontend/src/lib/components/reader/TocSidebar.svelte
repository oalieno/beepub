<script lang="ts" module>
  type TocItem = { label: string; href: string; subitems?: TocItem[] };
</script>

<script lang="ts">
  import { X } from "@lucide/svelte";
  import { tick } from "svelte";
  import * as m from "$lib/paraglide/messages.js";
  import type { RecapOut } from "$lib/types";

  let {
    toc = [],
    darkMode = false,
    currentHref = "",
    loadRecap = null,
    onchapter,
    onspine,
    onclose,
  }: {
    toc?: TocItem[];
    darkMode?: boolean;
    currentHref?: string;
    // Server books only — null hides the recap tab entirely.
    loadRecap?: (() => Promise<RecapOut>) | null;
    onchapter?: (href: string) => void;
    onspine?: (spineIndex: number) => void;
    onclose?: () => void;
  } = $props();

  let scrollContainer: HTMLDivElement | undefined = $state(undefined);
  let activeTab = $state<"toc" | "recap">("toc");
  let recap = $state<RecapOut | null>(null);
  let recapError = $state(false);

  function showRecap() {
    activeTab = "recap";
    if (recap || !loadRecap) return;
    recapError = false;
    loadRecap()
      .then((r) => (recap = r))
      .catch(() => (recapError = true));
  }

  function isActive(itemHref: string): boolean {
    if (!currentHref) return false;
    return itemHref === currentHref;
  }

  $effect(() => {
    // Auto-scroll to the active entry when sidebar opens
    if (scrollContainer && currentHref) {
      tick().then(() => {
        const active = scrollContainer?.querySelector("[data-toc-active]");
        active?.scrollIntoView({ block: "center" });
      });
    }
  });
</script>

{#snippet tocLevel(items: TocItem[], depth: number)}
  {#each items as item}
    {@const active = isActive(item.href)}
    <button
      class="w-full text-left pr-3 rounded-lg transition-colors {depth === 0
        ? 'py-2 text-sm'
        : 'py-1.5 text-xs'} {active
        ? darkMode
          ? 'bg-ink-800 text-white font-medium'
          : 'bg-accent text-foreground font-medium'
        : darkMode
          ? depth === 0
            ? 'hover:bg-ink-800 text-ink-300'
            : 'hover:bg-ink-800 text-ink-400'
          : depth === 0
            ? 'hover:bg-accent text-foreground'
            : 'hover:bg-accent text-muted-foreground'}"
      style="padding-left: {12 + depth * 16}px"
      data-toc-active={active ? "" : undefined}
      onclick={() => {
        onchapter?.(item.href);
        onclose?.();
      }}
    >
      {item.label}
    </button>
    {#if item.subitems?.length}
      {@render tocLevel(item.subitems, depth + 1)}
    {/if}
  {/each}
{/snippet}

<!-- Backdrop -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="fixed inset-0 z-40 bg-black/20"
  onclick={() => onclose?.()}
  onkeydown={(e) => {
    if (e.key === "Escape") onclose?.();
  }}
></div>

<!-- Sidebar (left) -->
<div
  class="fixed left-0 top-0 bottom-0 z-50 w-80 max-w-[85vw] shadow-2xl flex flex-col {darkMode
    ? 'bg-ink-900 border-r border-ink-800'
    : 'bg-card border-r border-border'}"
  style="padding-top: env(safe-area-inset-top, 0px);"
  role="dialog"
  aria-modal="true"
  aria-label={m.reader_toc()}
>
  <div
    class="flex items-center justify-between px-4 py-3 border-b {darkMode
      ? 'border-ink-800'
      : 'border-border'}"
  >
    {#if loadRecap}
      <div class="flex items-center gap-1 -ml-2">
        {#each [{ key: "toc", label: m.reader_toc() }, { key: "recap", label: m.reader_recap() }] as tab}
          {@const selected = activeTab === tab.key}
          <button
            class="px-2 py-1 rounded-md text-sm transition-colors {selected
              ? darkMode
                ? 'text-white font-semibold'
                : 'text-foreground font-semibold'
              : darkMode
                ? 'text-ink-500 hover:text-ink-300'
                : 'text-muted-foreground hover:text-foreground'}"
            aria-pressed={selected}
            onclick={() =>
              tab.key === "recap" ? showRecap() : (activeTab = "toc")}
          >
            {tab.label}
          </button>
        {/each}
      </div>
    {:else}
      <p
        class="text-sm font-semibold {darkMode
          ? 'text-ink-200'
          : 'text-foreground'}"
      >
        {m.reader_toc()}
      </p>
    {/if}
    <button
      aria-label={m.common_close()}
      class="p-1 rounded-md transition-colors {darkMode
        ? 'text-ink-400 hover:bg-ink-800 hover:text-ink-200'
        : 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
      onclick={() => onclose?.()}
    >
      <X size={16} />
    </button>
  </div>
  <div class="flex-1 overflow-y-auto p-2" bind:this={scrollContainer}>
    {#if activeTab === "recap"}
      {#if recapError || (recap && recap.sections.length === 0)}
        <p
          class="text-sm {darkMode
            ? 'text-ink-500'
            : 'text-muted-foreground'} py-4 px-3 text-center"
        >
          {#if recapError}
            {m.reader_recap_load_failed()}
          {:else if recap?.has_any}
            {m.reader_recap_empty_start()}
          {:else}
            {m.reader_recap_empty_none()}
          {/if}
        </p>
      {:else if !recap}
        <p
          class="text-sm {darkMode
            ? 'text-ink-500'
            : 'text-muted-foreground'} py-4 text-center"
        >
          {m.common_loading()}
        </p>
      {:else}
        <div class="flex flex-col gap-4 p-2">
          {#each recap.sections as section}
            <div>
              <button
                class="text-sm font-medium mb-1 text-left {darkMode
                  ? 'text-ink-200 hover:text-white'
                  : 'text-foreground hover:text-primary'} transition-colors"
                onclick={() => {
                  onspine?.(section.spine_index);
                  onclose?.();
                }}
              >
                {section.title ?? `#${section.spine_index + 1}`}
              </button>
              <p
                class="text-sm leading-relaxed whitespace-pre-line {darkMode
                  ? 'text-ink-400'
                  : 'text-muted-foreground'}"
              >
                {section.summary}
              </p>
            </div>
          {/each}
        </div>
      {/if}
    {:else if toc.length === 0}
      <p
        class="text-sm {darkMode
          ? 'text-ink-500'
          : 'text-muted-foreground'} py-4 text-center"
      >
        {m.reader_toc_empty()}
      </p>
    {:else}
      <div class="flex flex-col gap-0.5">
        {@render tocLevel(toc, 0)}
      </div>
    {/if}
  </div>
</div>
