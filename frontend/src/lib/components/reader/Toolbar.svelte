<script lang="ts">
  import { ArrowLeft, ChevronLeft, ChevronRight, Minus, Plus, Sun, Moon, List, Highlighter } from '@lucide/svelte';

  let {
    bookId = '', title = '', fontFamily = 'serif', fontSize = 16, percentage = 0,
    darkMode = false, toc = [], isRtl = false, highlightCount = 0,
    onprev, onnext, onfontToggle, onfontIncrease, onfontDecrease, onthemeToggle, onchapter, onhighlights, ontoc_toggle,
  }: {
    bookId?: string;
    title?: string;
    fontFamily?: string;
    fontSize?: number;
    percentage?: number;
    darkMode?: boolean;
    toc?: { label: string; href: string; subitems?: any[] }[];
    isRtl?: boolean;
    highlightCount?: number;
    onprev?: () => void;
    onnext?: () => void;
    onfontToggle?: () => void;
    onfontIncrease?: () => void;
    onfontDecrease?: () => void;
    onthemeToggle?: () => void;
    onchapter?: (href: string) => void;
    onhighlights?: () => void;
    ontoc_toggle?: () => void;
  } = $props();

  function btnClass(dark: boolean) {
    return dark
      ? 'hover:bg-gray-800 text-gray-400 hover:text-gray-200'
      : 'hover:bg-accent text-muted-foreground hover:text-foreground';
  }
</script>

<div class="min-h-14 border-b flex flex-wrap items-center px-2 sm:px-4 gap-2 sm:gap-3 py-2 z-10 relative {darkMode ? 'bg-gray-900 border-gray-800 text-gray-200' : 'bg-background border-border text-foreground'}">
  <a
    href="/books/{bookId}"
    class="p-1.5 rounded-md {btnClass(darkMode)} transition-colors"
    aria-label="Go back"
  >
    <ArrowLeft size={20} />
  </a>

  <!-- TOC button -->
  <button
    class="p-1.5 rounded-md transition-colors {btnClass(darkMode)}"
    title="Table of contents"
    onclick={() => ontoc_toggle?.()}
  >
    <List size={18} />
  </button>

  <!-- Highlights button -->
  <button
    class="p-1.5 rounded-md transition-colors relative {btnClass(darkMode)}"
    title="Highlights"
    onclick={() => onhighlights?.()}
  >
    <Highlighter size={18} />
    {#if highlightCount > 0}
      <span class="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 rounded-full text-[9px] font-bold flex items-center justify-center {darkMode ? 'bg-amber-500 text-gray-900' : 'bg-primary text-primary-foreground'}">
        {highlightCount > 99 ? '99' : highlightCount}
      </span>
    {/if}
  </button>

  <div class="flex-1 basis-full sm:basis-auto min-w-0 order-last sm:order-none text-center sm:text-left">
    <p class="text-sm font-medium truncate">{title}</p>
    <p class="hidden sm:flex text-xs {darkMode ? 'text-gray-500' : 'text-muted-foreground'} items-center gap-1.5">
      {percentage}%
    </p>
  </div>

  <div class="ml-auto flex items-center gap-1">
    <button
      class="hidden sm:inline-flex px-2.5 py-1.5 text-xs font-medium rounded-lg transition-colors {btnClass(darkMode)}"
      title="Toggle font family"
      onclick={() => onfontToggle?.()}
    >
      {fontFamily === 'serif' ? 'Serif' : 'Sans'}
    </button>

    <div class="hidden sm:block w-px h-5 {darkMode ? 'bg-gray-700' : 'bg-border'}"></div>

    <button
      class="p-1.5 rounded-md transition-colors {btnClass(darkMode)}"
      onclick={() => onfontDecrease?.()}
      disabled={fontSize <= 10}
    >
      <Minus size={14} />
    </button>
    <span class="text-[11px] w-8 text-center {darkMode ? 'text-gray-500' : 'text-muted-foreground'}">{fontSize}px</span>
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

