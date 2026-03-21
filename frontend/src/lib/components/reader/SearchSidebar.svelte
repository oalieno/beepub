<script lang="ts">
  import { Search, X, Loader2 } from "@lucide/svelte";
  import type { SearchResult } from "./EpubReader.svelte";

  let {
    darkMode = false,
    onselect,
    onclose,
    onsearch,
  }: {
    darkMode?: boolean;
    onselect?: (cfi: string) => void;
    onclose?: () => void;
    onsearch?: (
      query: string,
      onResults: (results: SearchResult[]) => void,
      signal: AbortSignal,
    ) => Promise<void>;
  } = $props();

  let query = $state("");
  let results = $state<SearchResult[]>([]);
  let searching = $state(false);
  let searched = $state(false);
  let abortController: AbortController | null = null;
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  let inputEl: HTMLInputElement | undefined = $state(undefined);

  $effect(() => {
    // Auto-focus input on mount
    inputEl?.focus();
  });

  function handleInput() {
    if (debounceTimer) clearTimeout(debounceTimer);
    if (abortController) {
      abortController.abort();
      abortController = null;
    }

    const q = query.trim();
    if (q.length < 2) {
      results = [];
      searching = false;
      searched = false;
      return;
    }

    debounceTimer = setTimeout(() => doSearch(q), 300);
  }

  async function doSearch(q: string) {
    if (abortController) abortController.abort();
    abortController = new AbortController();
    searching = true;
    searched = false;
    results = [];

    try {
      await onsearch?.(
        q,
        (r) => {
          results = r;
        },
        abortController.signal,
      );
    } catch {
      // aborted or error
    } finally {
      searching = false;
      searched = true;
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      onclose?.();
    }
  }

  function trimExcerpt(excerpt: string, q: string): string {
    // Re-center excerpt around the match so line-clamp doesn't hide it
    const maxLen = 80;
    const idx = excerpt.toLowerCase().indexOf(q.toLowerCase());
    if (idx === -1 || excerpt.length <= maxLen) return excerpt;
    const half = Math.floor((maxLen - q.length) / 2);
    let start = Math.max(0, idx - half);
    let end = Math.min(excerpt.length, start + maxLen);
    // Adjust start if end hit the boundary
    if (end - start < maxLen) start = Math.max(0, end - maxLen);
    let trimmed = excerpt.substring(start, end);
    if (start > 0) trimmed = "..." + trimmed;
    if (end < excerpt.length) trimmed = trimmed + "...";
    return trimmed;
  }

  function highlightExcerpt(excerpt: string, q: string): string {
    if (!q) return escape(excerpt);
    const trimmed = trimExcerpt(excerpt, q);
    const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`(${escaped})`, "gi");
    return escape(trimmed).replace(
      re,
      '<mark class="bg-yellow-300/60 dark:bg-yellow-500/40 rounded-sm px-0.5">$1</mark>',
    );
  }

  function escape(s: string): string {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
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
      Search in Book
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

  <!-- Search input -->
  <div
    class="px-3 py-2 border-b {darkMode ? 'border-gray-800' : 'border-border'}"
  >
    <div class="relative">
      <Search
        size={14}
        class="absolute left-2.5 top-1/2 -translate-y-1/2 {darkMode
          ? 'text-gray-500'
          : 'text-muted-foreground'}"
      />
      <input
        bind:this={inputEl}
        bind:value={query}
        oninput={handleInput}
        onkeydown={handleKeydown}
        type="text"
        placeholder="Search..."
        class="w-full pl-8 pr-3 py-1.5 text-sm rounded-md outline-none {darkMode
          ? 'bg-gray-800 text-gray-200 placeholder-gray-500 border border-gray-700 focus:border-gray-600'
          : 'bg-muted text-foreground placeholder-muted-foreground border border-border focus:border-ring'}"
      />
    </div>
  </div>

  <!-- Results -->
  <div class="flex-1 overflow-y-auto">
    {#if searching}
      <div class="flex items-center justify-center gap-2 py-8">
        <Loader2
          size={16}
          class="animate-spin {darkMode
            ? 'text-gray-400'
            : 'text-muted-foreground'}"
        />
        <span
          class="text-sm {darkMode ? 'text-gray-400' : 'text-muted-foreground'}"
        >
          Searching... ({results.length} found)
        </span>
      </div>
    {:else if searched && results.length === 0}
      <p
        class="text-sm py-8 text-center {darkMode
          ? 'text-gray-500'
          : 'text-muted-foreground'}"
      >
        No results found.
      </p>
    {:else if results.length > 0}
      <div class="p-2">
        <p
          class="text-xs px-2 py-1 {darkMode
            ? 'text-gray-500'
            : 'text-muted-foreground'}"
        >
          {results.length} result{results.length !== 1 ? "s" : ""}
        </p>
        <div class="flex flex-col gap-0.5 mt-1">
          {#each results as result}
            <button
              class="w-full text-left px-3 py-2 rounded-lg text-sm transition-colors {darkMode
                ? 'hover:bg-gray-800 text-gray-300'
                : 'hover:bg-accent text-foreground'}"
              onclick={() => {
                onselect?.(result.cfi);
              }}
            >
              <p
                class="text-xs font-medium mb-0.5 {darkMode
                  ? 'text-gray-400'
                  : 'text-muted-foreground'}"
              >
                {result.sectionLabel}
              </p>
              <p class="text-xs leading-relaxed line-clamp-3">
                {@html highlightExcerpt(result.excerpt, query.trim())}
              </p>
            </button>
          {/each}
        </div>
      </div>
    {:else}
      <p
        class="text-sm py-8 text-center {darkMode
          ? 'text-gray-500'
          : 'text-muted-foreground'}"
      >
        Type to search in this book.
      </p>
    {/if}
  </div>
</div>
