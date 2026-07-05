<script lang="ts">
  import {
    ArrowLeft,
    ChevronLeft,
    ChevronRight,
    Sun,
    Moon,
    CircleHelp,
    Settings,
    List,
    Search,
    Highlighter,
    MessageCircle,
  } from "@lucide/svelte";
  import { goto } from "$app/navigation";
  import { getIsOnline } from "$lib/services/network";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";

  let {
    bookId = "",
    title = "",
    percentage = null,
    darkMode = false,
    toc = [],
    isRtl = false,
    isImageBook = false,
    highlightCount = 0,
    illustrationCount = 0,
    offline = false,
    onprev,
    onnext,
    onthemeToggle,
    onchapter,
    onsettings,
    onhelp,
    onhighlights,
    oncompanion,
    onsearch,
    ontoc_toggle,
  }: {
    bookId?: string;
    title?: string;
    percentage?: number | null;
    darkMode?: boolean;
    toc?: { label: string; href: string; subitems?: any[] }[];
    isRtl?: boolean;
    isImageBook?: boolean;
    highlightCount?: number;
    illustrationCount?: number;
    offline?: boolean;
    onprev?: () => void;
    onnext?: () => void;
    onthemeToggle?: () => void;
    onsettings?: () => void;
    onhelp?: () => void;
    onchapter?: (href: string) => void;
    onhighlights?: () => void;
    oncompanion?: () => void;
    onsearch?: () => void;
    ontoc_toggle?: () => void;
  } = $props();

  function btnClass(dark: boolean) {
    return dark
      ? "hover:bg-ink-800 text-ink-400 hover:text-ink-200"
      : "hover:bg-accent text-muted-foreground hover:text-foreground";
  }
</script>

<div
  class="min-h-14 border-b flex flex-wrap items-center px-2 sm:px-4 gap-1 sm:gap-3 py-2 z-10 relative touch-manipulation select-none {darkMode
    ? 'bg-ink-900 border-ink-800 text-ink-200'
    : 'bg-background border-border text-foreground'}"
  style="padding-top: calc(env(safe-area-inset-top, 0px) + 0.5rem);"
>
  <button
    class="p-1.5 rounded-md {btnClass(darkMode)} transition-colors"
    aria-label={m.reader_go_back()}
    onclick={() =>
      goto(getIsOnline() ? `/books/${bookId}` : "/downloads", {
        replaceState: true,
      })}
  >
    <ArrowLeft size={20} />
  </button>

  <!-- TOC button -->
  <button
    class="p-1.5 rounded-md transition-colors {btnClass(darkMode)}"
    title={m.reader_toc()}
    onclick={() => ontoc_toggle?.()}
  >
    <List size={18} />
  </button>

  {#if !isImageBook}
    <!-- Search button -->
    <button
      class="p-1.5 rounded-md transition-colors {btnClass(darkMode)}"
      title={m.reader_search_in_book()}
      onclick={() => onsearch?.()}
    >
      <Search size={18} />
    </button>

    <!-- Highlights button -->
    <button
      class="p-1.5 rounded-md transition-colors relative {btnClass(darkMode)}"
      title={m.reader_highlights()}
      onclick={() => onhighlights?.()}
    >
      <Highlighter size={18} />
      {#if highlightCount > 0}
        <span
          class="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 rounded-full text-[9px] font-bold flex items-center justify-center {darkMode
            ? 'bg-amber-500 text-ink-900'
            : 'bg-primary text-primary-foreground'}"
        >
          {highlightCount > 99 ? "99" : highlightCount}
        </span>
      {/if}
    </button>

    <!-- Companion button -->
    <button
      class="p-1.5 rounded-md transition-colors {offline
        ? 'opacity-40'
        : btnClass(darkMode)}"
      title={offline ? m.reader_ai_offline() : m.reader_ai_companion()}
      aria-disabled={offline || undefined}
      onclick={() => {
        if (offline) {
          toastStore.info(m.reader_ai_offline());
          return;
        }
        oncompanion?.();
      }}
    >
      <MessageCircle size={18} />
    </button>
  {/if}

  <div
    class="flex-1 basis-full sm:basis-auto min-w-0 order-last sm:order-none text-center sm:text-left"
  >
    <p class="text-sm font-medium truncate">{title}</p>
    {#if percentage != null}
      <p
        class="hidden sm:flex text-xs {darkMode
          ? 'text-ink-500'
          : 'text-muted-foreground'} items-center gap-1.5"
      >
        {percentage}%
      </p>
    {/if}
  </div>

  <div class="ml-auto flex items-center gap-1">
    <button
      class="p-1.5 rounded-md transition-colors {btnClass(darkMode)}"
      title={m.reader_theme_toggle()}
      onclick={() => onthemeToggle?.()}
    >
      {#if darkMode}
        <Sun size={16} />
      {:else}
        <Moon size={16} />
      {/if}
    </button>

    <button
      class="p-1.5 rounded-md transition-colors {btnClass(darkMode)}"
      title={m.reader_settings_title()}
      onclick={() => onsettings?.()}
    >
      <Settings size={16} />
    </button>

    <button
      class="p-1.5 rounded-md transition-colors {btnClass(darkMode)}"
      title={m.reader_gesture_help()}
      onclick={() => onhelp?.()}
    >
      <CircleHelp size={16} />
    </button>
  </div>

  <!-- Nav -->
  <div class="flex items-center gap-1">
    <button
      class="p-2 rounded-md transition-colors {btnClass(darkMode)}"
      onclick={() => (isRtl ? onnext?.() : onprev?.())}
    >
      <ChevronLeft size={20} />
    </button>
    <button
      class="p-2 rounded-md transition-colors {btnClass(darkMode)}"
      onclick={() => (isRtl ? onprev?.() : onnext?.())}
    >
      <ChevronRight size={20} />
    </button>
  </div>
</div>
