<script lang="ts">
  import { goto } from "$app/navigation";
  import { booksApi } from "$lib/api/books";
  import { authStore } from "$lib/stores/auth";
  import type { BookOut } from "$lib/types";
  import { Search, BookOpen, X } from "@lucide/svelte";

  let { open = $bindable(false) }: { open?: boolean } = $props();

  type SearchResult = BookOut & { library_name: string | null };

  let query = $state("");
  let results = $state<SearchResult[]>([]);
  let total = $state(0);
  let loading = $state(false);
  let selectedIndex = $state(-1);
  let inputEl: HTMLInputElement | undefined = $state();
  let debounceTimer: ReturnType<typeof setTimeout> | undefined;

  function doSearch() {
    const q = query.trim();
    if (!q) {
      results = [];
      total = 0;
      return;
    }
    const token = $authStore.token;
    if (!token) return;

    loading = true;
    booksApi
      .search(q, token)
      .then((resp) => {
        results = resp.items;
        total = resp.total;
        selectedIndex = -1;
      })
      .catch(() => {
        results = [];
        total = 0;
      })
      .finally(() => {
        loading = false;
      });
  }

  function handleInput() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(doSearch, 300);
  }

  function selectResult(result: SearchResult) {
    open = false;
    goto(`/books/${result.id}`);
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      selectedIndex = Math.min(selectedIndex + 1, results.length - 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      selectedIndex = Math.max(selectedIndex - 1, -1);
    } else if (e.key === "Enter" && selectedIndex >= 0) {
      e.preventDefault();
      selectResult(results[selectedIndex]);
    } else if (e.key === "Escape") {
      open = false;
    }
  }

  $effect(() => {
    if (open) {
      query = "";
      results = [];
      total = 0;
      selectedIndex = -1;
      // Focus input after mount
      setTimeout(() => inputEl?.focus(), 50);
    }
  });
</script>

{#if open}
  <!-- Backdrop -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 z-[100] bg-black/50 backdrop-blur-sm"
    onclick={() => (open = false)}
    onkeydown={handleKeydown}
  >
    <!-- Modal -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="max-w-xl mt-[12vh] mx-4 sm:mx-auto bg-card rounded-2xl shadow-2xl border border-border/50 overflow-hidden"
      onclick={(e) => e.stopPropagation()}
    >
      <!-- Search input -->
      <div class="flex items-center gap-3 px-4 py-3 border-b border-border/50">
        <Search size={20} class="text-muted-foreground shrink-0" />
        <input
          bind:this={inputEl}
          bind:value={query}
          oninput={handleInput}
          onkeydown={handleKeydown}
          placeholder="Search books across all libraries..."
          class="flex-1 bg-transparent text-foreground placeholder:text-muted-foreground outline-none text-base"
        />
        {#if query}
          <button
            class="text-muted-foreground hover:text-foreground"
            onclick={() => {
              query = "";
              results = [];
              total = 0;
              inputEl?.focus();
            }}
          >
            <X size={16} />
          </button>
        {/if}
        <kbd
          class="hidden sm:inline text-xs text-muted-foreground bg-secondary px-1.5 py-0.5 rounded"
          >esc</kbd
        >
      </div>

      <!-- Results -->
      {#if query.trim()}
        <div class="max-h-[60vh] overflow-y-auto">
          {#if loading && results.length === 0}
            <div class="px-4 py-8 text-center text-muted-foreground text-sm">
              Searching...
            </div>
          {:else if results.length === 0 && !loading}
            <div class="px-4 py-8 text-center text-muted-foreground text-sm">
              No books found
            </div>
          {:else}
            {#each results as result, i (result.id)}
              <button
                class="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-secondary/50 transition-colors
                  {i === selectedIndex ? 'bg-secondary/70' : ''}"
                onclick={() => selectResult(result)}
                onmouseenter={() => (selectedIndex = i)}
              >
                <!-- Thumbnail -->
                <div
                  class="w-10 h-14 shrink-0 rounded-sm overflow-hidden bg-secondary flex items-center justify-center"
                >
                  {#if result.cover_path}
                    <img
                      src="/covers/{result.id}.jpg"
                      alt=""
                      class="w-full h-full object-cover"
                      loading="lazy"
                    />
                  {:else}
                    <BookOpen size={16} class="text-muted-foreground/30" />
                  {/if}
                </div>

                <!-- Info -->
                <div class="flex-1 min-w-0">
                  <p class="text-sm font-medium text-foreground truncate">
                    {result.display_title ?? "Untitled"}
                  </p>
                  <p class="text-xs text-muted-foreground truncate">
                    {(result.display_authors ?? []).join(", ") || "\u00A0"}
                  </p>
                </div>

                <!-- Library badge -->
                {#if result.library_name}
                  <span
                    class="shrink-0 text-xs text-muted-foreground bg-secondary px-2 py-0.5 rounded-full"
                  >
                    {result.library_name}
                  </span>
                {/if}
              </button>
            {/each}
            {#if total > results.length}
              <div
                class="px-4 py-2 text-center text-xs text-muted-foreground border-t border-border/50"
              >
                Showing {results.length} of {total} results
              </div>
            {/if}
          {/if}
        </div>
      {/if}
    </div>
  </div>
{/if}
