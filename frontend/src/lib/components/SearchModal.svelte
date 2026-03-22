<script lang="ts">
  import { goto } from "$app/navigation";
  import { booksApi } from "$lib/api/books";
  import { searchApi, type SemanticSearchResult } from "$lib/api/search";
  import { authStore } from "$lib/stores/auth";
  import type { BookOut } from "$lib/types";
  import { Search, BookOpen, FileText, X } from "@lucide/svelte";

  let { open = $bindable(false) }: { open?: boolean } = $props();

  type Tab = "books" | "content";
  type BookSearchResult = BookOut & { library_name: string | null };

  let activeTab = $state<Tab>("books");
  let query = $state("");
  let inputEl: HTMLInputElement | undefined = $state();
  let debounceTimer: ReturnType<typeof setTimeout> | undefined;

  // Books tab state
  let bookResults = $state<BookSearchResult[]>([]);
  let bookTotal = $state(0);
  let bookLoading = $state(false);

  // Content tab state
  let contentResults = $state<SemanticSearchResult[]>([]);
  let contentLoading = $state(false);
  let contentError = $state("");

  let selectedIndex = $state(-1);

  function doBookSearch() {
    const q = query.trim();
    if (!q) {
      bookResults = [];
      bookTotal = 0;
      return;
    }
    const token = $authStore.token;
    if (!token) return;

    bookLoading = true;
    booksApi
      .search(q, token)
      .then((resp) => {
        bookResults = resp.items;
        bookTotal = resp.total;
        selectedIndex = -1;
      })
      .catch(() => {
        bookResults = [];
        bookTotal = 0;
      })
      .finally(() => {
        bookLoading = false;
      });
  }

  function doContentSearch() {
    const q = query.trim();
    if (!q) {
      contentResults = [];
      contentError = "";
      return;
    }
    const token = $authStore.token;
    if (!token) return;

    contentLoading = true;
    contentError = "";
    searchApi
      .semantic(q, token)
      .then((resp) => {
        contentResults = resp.results;
        selectedIndex = -1;
      })
      .catch((err) => {
        contentResults = [];
        contentError =
          err.message === "Semantic search is not configured"
            ? "Semantic search is not configured. Set up embedding in Admin settings."
            : "Search unavailable — please try again";
      })
      .finally(() => {
        contentLoading = false;
      });
  }

  function handleInput() {
    clearTimeout(debounceTimer);
    if (activeTab === "books") {
      debounceTimer = setTimeout(doBookSearch, 300);
    }
    // Content tab: search on Enter only (embedding is expensive)
  }

  function handleSearchSubmit() {
    if (activeTab === "content") {
      doContentSearch();
    }
  }

  function selectBookResult(result: BookSearchResult) {
    open = false;
    goto(`/books/${result.id}`);
  }

  function selectContentResult(result: SemanticSearchResult) {
    open = false;
    goto(`/books/${result.book_id}`);
  }

  function switchTab(tab: Tab) {
    activeTab = tab;
    selectedIndex = -1;
    // Re-run search if there's a query
    if (query.trim()) {
      if (tab === "books") doBookSearch();
      else doContentSearch();
    }
    setTimeout(() => inputEl?.focus(), 10);
  }

  function currentResults(): number {
    return activeTab === "books" ? bookResults.length : contentResults.length;
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      selectedIndex = Math.min(selectedIndex + 1, currentResults() - 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      selectedIndex = Math.max(selectedIndex - 1, -1);
    } else if (e.key === "Enter" && selectedIndex >= 0) {
      e.preventDefault();
      if (activeTab === "books" && bookResults[selectedIndex]) {
        selectBookResult(bookResults[selectedIndex]);
      } else if (activeTab === "content" && contentResults[selectedIndex]) {
        selectContentResult(contentResults[selectedIndex]);
      }
    } else if (e.key === "Enter" && selectedIndex < 0) {
      handleSearchSubmit();
    } else if (e.key === "Escape") {
      open = false;
    }
  }

  $effect(() => {
    if (open) {
      query = "";
      bookResults = [];
      bookTotal = 0;
      contentResults = [];
      contentError = "";
      selectedIndex = -1;
      activeTab = "books";
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
    <div
      role="presentation"
      class="max-w-xl mt-[12vh] mx-4 sm:mx-auto bg-card rounded-2xl shadow-2xl border border-border/50 overflow-hidden"
      onclick={(e) => e.stopPropagation()}
    >
      <!-- Tab toggle -->
      <div
        class="flex border-b border-border/50"
        role="tablist"
        aria-label="Search type"
      >
        <button
          role="tab"
          aria-selected={activeTab === "books"}
          class="flex-1 flex items-center justify-center gap-1.5 px-4 py-2 text-sm transition-colors
            {activeTab === 'books'
            ? 'text-foreground border-b-2 border-primary font-medium'
            : 'text-muted-foreground hover:text-foreground'}"
          onclick={() => switchTab("books")}
        >
          <BookOpen size={14} />
          Books
        </button>
        <button
          role="tab"
          aria-selected={activeTab === "content"}
          class="flex-1 flex items-center justify-center gap-1.5 px-4 py-2 text-sm transition-colors
            {activeTab === 'content'
            ? 'text-foreground border-b-2 border-primary font-medium'
            : 'text-muted-foreground hover:text-foreground'}"
          onclick={() => switchTab("content")}
        >
          <FileText size={14} />
          Content
        </button>
      </div>

      <!-- Search input -->
      <div class="flex items-center gap-3 px-4 py-3 border-b border-border/50">
        <Search size={20} class="text-muted-foreground shrink-0" />
        <input
          bind:this={inputEl}
          bind:value={query}
          oninput={handleInput}
          onkeydown={handleKeydown}
          placeholder={activeTab === "books"
            ? "Search books across all libraries..."
            : "Search book content by meaning..."}
          class="flex-1 bg-transparent text-foreground placeholder:text-muted-foreground outline-none text-base"
        />
        {#if query}
          <button
            class="text-muted-foreground hover:text-foreground"
            onclick={() => {
              query = "";
              bookResults = [];
              bookTotal = 0;
              contentResults = [];
              contentError = "";
              inputEl?.focus();
            }}
          >
            <X size={16} />
          </button>
        {/if}
        <kbd
          class="hidden sm:inline text-xs text-muted-foreground bg-secondary px-1.5 py-0.5 rounded"
          >{activeTab === "content" ? "↵" : "esc"}</kbd
        >
      </div>

      <!-- Results -->
      {#if activeTab === "books"}
        <!-- Books tab results -->
        {#if query.trim()}
          <div class="max-h-[60vh] overflow-y-auto">
            {#if bookLoading && bookResults.length === 0}
              <div class="px-4 py-8 text-center text-muted-foreground text-sm">
                Searching...
              </div>
            {:else if bookResults.length === 0 && !bookLoading}
              <div class="px-4 py-8 text-center text-muted-foreground text-sm">
                No books found
              </div>
            {:else}
              {#each bookResults as result, i (result.id)}
                <button
                  class="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-secondary/50 transition-colors
                    {i === selectedIndex ? 'bg-secondary/70' : ''}"
                  onclick={() => selectBookResult(result)}
                  onmouseenter={() => (selectedIndex = i)}
                >
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
                  <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-foreground truncate">
                      {result.display_title ?? "Untitled"}
                    </p>
                    <p class="text-xs text-muted-foreground truncate">
                      {(result.display_authors ?? []).join(", ") || "\u00A0"}
                    </p>
                  </div>
                  {#if result.library_name}
                    <span
                      class="shrink-0 text-xs text-muted-foreground bg-secondary px-2 py-0.5 rounded-full"
                    >
                      {result.library_name}
                    </span>
                  {/if}
                </button>
              {/each}
              {#if bookTotal > bookResults.length}
                <div
                  class="px-4 py-2 text-center text-xs text-muted-foreground border-t border-border/50"
                >
                  Showing {bookResults.length} of {bookTotal} results
                </div>
              {/if}
            {/if}
          </div>
        {/if}
      {:else}
        <!-- Content tab results -->
        {#if !query.trim()}
          <div
            class="px-4 py-8 text-center text-muted-foreground text-sm space-y-1"
          >
            <p>Type a concept or question and press Enter</p>
            <p class="text-xs">
              Searches across all your books by meaning, not just keywords
            </p>
          </div>
        {:else if contentLoading}
          <!-- Skeleton loading -->
          <div class="max-h-[60vh] overflow-y-auto">
            {#each [1, 2, 3] as _}
              <div class="flex items-start gap-3 px-4 py-3 animate-pulse">
                <div class="w-10 h-14 shrink-0 rounded-sm bg-secondary"></div>
                <div class="flex-1 space-y-2">
                  <div class="h-3.5 bg-secondary rounded w-1/3"></div>
                  <div class="h-3 bg-secondary rounded w-full"></div>
                  <div class="h-3 bg-secondary rounded w-2/3"></div>
                </div>
              </div>
            {/each}
          </div>
        {:else if contentError}
          <div class="px-4 py-8 text-center text-muted-foreground text-sm">
            {contentError}
          </div>
        {:else if contentResults.length === 0}
          <div class="px-4 py-8 text-center text-muted-foreground text-sm">
            <BookOpen size={24} class="mx-auto mb-2 opacity-30" />
            No matching passages found. Try different keywords or check that your
            books have been indexed.
          </div>
        {:else}
          <div class="max-h-[60vh] overflow-y-auto" role="tabpanel">
            {#each contentResults as result, i (result.book_id + "-" + result.spine_index + "-" + result.char_offset_start)}
              <button
                class="w-full flex items-start gap-3 px-4 py-3 text-left hover:bg-secondary/50 transition-colors
                  {i === selectedIndex ? 'bg-secondary/70' : ''}"
                onclick={() => selectContentResult(result)}
                onmouseenter={() => (selectedIndex = i)}
              >
                <!-- Book cover placeholder -->
                <div
                  class="w-10 h-14 shrink-0 rounded-sm overflow-hidden bg-secondary flex items-center justify-center"
                >
                  <img
                    src="/covers/{result.book_id}.jpg"
                    alt=""
                    class="w-full h-full object-cover"
                    loading="lazy"
                    onerror={(e) => {
                      const target = e.currentTarget as HTMLImageElement;
                      target.style.display = "none";
                    }}
                  />
                </div>

                <div class="flex-1 min-w-0">
                  <!-- Book title + author -->
                  <p class="text-sm font-medium text-foreground truncate">
                    {result.book_title}
                  </p>
                  {#if result.book_author}
                    <p class="text-xs text-muted-foreground truncate">
                      {result.book_author}
                    </p>
                  {/if}
                  <!-- Passage snippet -->
                  <p
                    class="text-xs text-muted-foreground/80 mt-1 line-clamp-2 leading-relaxed"
                  >
                    {result.passage.slice(0, 200)}{result.passage.length > 200
                      ? "..."
                      : ""}
                  </p>
                </div>

                <!-- Similarity score -->
                <span
                  class="shrink-0 text-xs text-muted-foreground bg-secondary px-1.5 py-0.5 rounded tabular-nums"
                >
                  {Math.round(result.similarity * 100)}%
                </span>
              </button>
            {/each}
          </div>
        {/if}
      {/if}
    </div>
  </div>
{/if}
