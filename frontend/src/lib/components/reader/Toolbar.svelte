<script lang="ts">
  import { ArrowLeft, ChevronLeft, ChevronRight, Minus, Plus, Sun, Moon, List } from '@lucide/svelte';

  let {
    bookId = '', title = '', fontFamily = 'serif', fontSize = 16, percentage = 0,
    currentPage = 0, totalPages = 0, pageMapReady = false, calculatingPages = false, darkMode = false,
    toc = [], isRtl = false,
    onprev, onnext, onfontToggle, onfontIncrease, onfontDecrease, onthemeToggle, onchapter,
  }: {
    bookId?: string;
    title?: string;
    fontFamily?: string;
    fontSize?: number;
    percentage?: number;
    currentPage?: number;
    totalPages?: number;
    pageMapReady?: boolean;
    calculatingPages?: boolean;
    darkMode?: boolean;
    toc?: { label: string; href: string; subitems?: any[] }[];
    isRtl?: boolean;
    onprev?: () => void;
    onnext?: () => void;
    onfontToggle?: () => void;
    onfontIncrease?: () => void;
    onfontDecrease?: () => void;
    onthemeToggle?: () => void;
    onchapter?: (href: string) => void;
  } = $props();

  let showToc = $state(false);

  function btnClass(dark: boolean) {
    return dark
      ? 'hover:bg-gray-800 text-gray-400 hover:text-gray-200'
      : 'hover:bg-accent text-muted-foreground hover:text-foreground';
  }
</script>

<div class="h-14 border-b flex items-center px-4 gap-3 z-10 relative {darkMode ? 'bg-gray-900 border-gray-800 text-gray-200' : 'bg-background border-border text-foreground'}">
  <a
    href="/books/{bookId}"
    class="{btnClass(darkMode)} transition-colors"
    aria-label="Go back"
  >
    <ArrowLeft size={20} />
  </a>

  <!-- TOC button -->
  <button
    class="p-1.5 rounded-md transition-colors {btnClass(darkMode)}"
    title="Table of contents"
    onclick={() => (showToc = !showToc)}
  >
    <List size={18} />
  </button>

  <div class="flex-1 min-w-0">
    <p class="text-sm font-medium truncate">{title}</p>
    <p class="text-xs {darkMode ? 'text-gray-500' : 'text-muted-foreground'} flex items-center gap-1.5">
      {#if pageMapReady}
        {percentage}%
        {#if totalPages > 0}
          &middot; {currentPage} / {totalPages}
        {/if}
        {#if calculatingPages}
          <span class="inline-block w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin opacity-50"></span>
        {/if}
      {:else}
        <span class="inline-block w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin opacity-50"></span>
      {/if}
    </p>
  </div>

  <div class="flex items-center gap-1">
    <button
      class="px-2.5 py-1.5 text-xs font-medium rounded-lg transition-colors {btnClass(darkMode)}"
      title="Toggle font family"
      onclick={() => onfontToggle?.()}
    >
      {fontFamily === 'serif' ? 'Serif' : 'Sans'}
    </button>

    <div class="w-px h-5 {darkMode ? 'bg-gray-700' : 'bg-border'}"></div>

    <button
      class="p-1.5 rounded-md transition-colors {btnClass(darkMode)}"
      onclick={() => onfontDecrease?.()}
      disabled={fontSize <= 10}
    >
      <Minus size={14} />
    </button>
    <span class="text-xs w-8 text-center {darkMode ? 'text-gray-500' : 'text-muted-foreground'}">{fontSize}px</span>
    <button
      class="p-1.5 rounded-md transition-colors {btnClass(darkMode)}"
      onclick={() => onfontIncrease?.()}
      disabled={fontSize >= 32}
    >
      <Plus size={14} />
    </button>

    <div class="w-px h-5 {darkMode ? 'bg-gray-700' : 'bg-border'}"></div>

    <button
      class="p-1.5 rounded-md transition-colors {btnClass(darkMode)}"
      title="Toggle dark/light mode"
      onclick={() => onthemeToggle?.()}
    >
      {#if darkMode}
        <Sun size={16} />
      {:else}
        <Moon size={16} />
      {/if}
    </button>
  </div>

  <!-- Nav -->
  <div class="flex items-center gap-1">
    <button
      class="p-2 rounded-md transition-colors {btnClass(darkMode)}"
      onclick={() => isRtl ? onnext?.() : onprev?.()}
    >
      <ChevronLeft size={20} />
    </button>
    <button
      class="p-2 rounded-md transition-colors {btnClass(darkMode)}"
      onclick={() => isRtl ? onprev?.() : onnext?.()}
    >
      <ChevronRight size={20} />
    </button>
  </div>
</div>

<!-- TOC dropdown -->
{#if showToc && toc.length > 0}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 z-40"
    onclick={() => (showToc = false)}
    onkeydown={(e) => { if (e.key === 'Escape') showToc = false; }}
  ></div>
  <div class="absolute left-12 top-14 z-50 w-72 max-h-[70vh] overflow-y-auto rounded-xl shadow-xl border {darkMode ? 'bg-gray-900 border-gray-700' : 'bg-card border-border'}">
    <div class="p-3">
      <p class="text-xs font-semibold uppercase tracking-wider mb-2 {darkMode ? 'text-gray-500' : 'text-muted-foreground'}">Chapters</p>
      {#each toc as item}
        <button
          class="w-full text-left px-3 py-2 rounded-lg text-sm transition-colors {darkMode ? 'hover:bg-gray-800 text-gray-300' : 'hover:bg-accent text-foreground'}"
          onclick={() => { onchapter?.(item.href); showToc = false; }}
        >
          {item.label}
        </button>
        {#if item.subitems}
          {#each item.subitems as sub}
            <button
              class="w-full text-left pl-7 pr-3 py-1.5 rounded-lg text-xs transition-colors {darkMode ? 'hover:bg-gray-800 text-gray-400' : 'hover:bg-accent text-muted-foreground'}"
              onclick={() => { onchapter?.(sub.href); showToc = false; }}
            >
              {sub.label}
            </button>
          {/each}
        {/if}
      {/each}
    </div>
  </div>
{/if}
