<script lang="ts">
  import { X } from "@lucide/svelte";
  import { tick } from "svelte";

  let {
    toc = [],
    darkMode = false,
    currentHref = "",
    onchapter,
    onclose,
  }: {
    toc?: { label: string; href: string; subitems?: any[] }[];
    darkMode?: boolean;
    currentHref?: string;
    onchapter?: (href: string) => void;
    onclose?: () => void;
  } = $props();

  let scrollContainer: HTMLDivElement | undefined = $state(undefined);

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
    ? 'bg-gray-900 border-r border-gray-800'
    : 'bg-card border-r border-border'}"
  style="padding-top: env(safe-area-inset-top, 0px);"
>
  <div
    class="flex items-center justify-between px-4 py-3 border-b {darkMode
      ? 'border-gray-800'
      : 'border-border'}"
  >
    <p
      class="text-sm font-semibold {darkMode
        ? 'text-gray-200'
        : 'text-foreground'}"
    >
      Table of Contents
    </p>
    <button
      class="p-1 rounded-md transition-colors {darkMode
        ? 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
        : 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
      onclick={() => onclose?.()}
    >
      <X size={16} />
    </button>
  </div>
  <div class="flex-1 overflow-y-auto p-2" bind:this={scrollContainer}>
    {#if toc.length === 0}
      <p
        class="text-sm {darkMode
          ? 'text-gray-500'
          : 'text-muted-foreground'} py-4 text-center"
      >
        No table of contents.
      </p>
    {:else}
      <div class="flex flex-col gap-0.5">
        {#each toc as item}
          {@const active = isActive(item.href)}
          <button
            class="w-full text-left px-3 py-2 rounded-lg text-sm transition-colors {active
              ? darkMode
                ? 'bg-gray-800 text-white font-medium'
                : 'bg-accent text-foreground font-medium'
              : darkMode
                ? 'hover:bg-gray-800 text-gray-300'
                : 'hover:bg-accent text-foreground'}"
            data-toc-active={active ? "" : undefined}
            onclick={() => {
              onchapter?.(item.href);
              onclose?.();
            }}
          >
            {item.label}
          </button>
          {#if item.subitems}
            {#each item.subitems as sub}
              {@const subActive = isActive(sub.href)}
              <button
                class="w-full text-left pl-7 pr-3 py-1.5 rounded-lg text-xs transition-colors {subActive
                  ? darkMode
                    ? 'bg-gray-800 text-white font-medium'
                    : 'bg-accent text-foreground font-medium'
                  : darkMode
                    ? 'hover:bg-gray-800 text-gray-400'
                    : 'hover:bg-accent text-muted-foreground'}"
                data-toc-active={subActive ? "" : undefined}
                onclick={() => {
                  onchapter?.(sub.href);
                  onclose?.();
                }}
              >
                {sub.label}
              </button>
            {/each}
          {/if}
        {/each}
      </div>
    {/if}
  </div>
</div>
