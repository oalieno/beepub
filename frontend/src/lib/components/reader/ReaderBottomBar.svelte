<script lang="ts">
  import {
    ChevronLeft,
    ChevronRight,
    List,
    Search,
    Highlighter,
    MessageCircle,
    Settings,
  } from "@lucide/svelte";
  import { toastStore } from "$lib/stores/toast";

  let {
    percentage = 0,
    darkMode = false,
    isRtl = false,
    isImageBook = false,
    highlightCount = 0,
    offline = false,
    onprev,
    onnext,
    ontoc,
    onsearch,
    onhighlights,
    oncompanion,
    onsettings,
  }: {
    percentage?: number;
    darkMode?: boolean;
    isRtl?: boolean;
    isImageBook?: boolean;
    highlightCount?: number;
    offline?: boolean;
    onprev?: () => void;
    onnext?: () => void;
    ontoc?: () => void;
    onsearch?: () => void;
    onhighlights?: () => void;
    oncompanion?: () => void;
    onsettings?: () => void;
  } = $props();

  const btnClass = $derived(
    darkMode
      ? "text-gray-400 hover:bg-gray-800 hover:text-gray-200"
      : "text-muted-foreground hover:bg-secondary hover:text-foreground",
  );

  const actionBtnClass = $derived(
    darkMode
      ? "text-gray-400 hover:text-gray-200"
      : "text-muted-foreground hover:text-foreground",
  );
</script>

<div
  class="md:hidden fixed bottom-0 left-0 right-0 z-30 {darkMode
    ? 'bg-gray-900 border-t border-gray-800'
    : 'bg-background border-t border-border/50'}"
  style="padding-bottom: max(0.5rem, env(safe-area-inset-bottom, 0px));"
  role="toolbar"
  aria-label="Reading controls"
>
  <!-- Progress row -->
  <div class="flex items-center gap-2 px-3 py-2">
    <button
      class="p-1 rounded-md transition-colors {btnClass}"
      onclick={() => (isRtl ? onnext?.() : onprev?.())}
      aria-label="Previous page"
    >
      <ChevronLeft size={20} />
    </button>
    <div
      class="flex-1 h-1 rounded-full overflow-hidden {darkMode
        ? 'bg-gray-800'
        : 'bg-secondary'}"
    >
      <div
        class="h-full rounded-full transition-all duration-300 {darkMode
          ? 'bg-gray-500'
          : 'bg-primary'}"
        style="width: {percentage}%;"
      ></div>
    </div>
    <button
      class="p-1 rounded-md transition-colors {btnClass}"
      onclick={() => (isRtl ? onprev?.() : onnext?.())}
      aria-label="Next page"
    >
      <ChevronRight size={20} />
    </button>
  </div>

  <!-- Action row -->
  <div class="flex items-center justify-around px-4">
    <button
      class="flex flex-col items-center gap-0.5 py-1 px-3 rounded-lg transition-colors {actionBtnClass}"
      onclick={() => ontoc?.()}
      aria-label="Table of Contents"
    >
      <List size={20} />
      <span class="text-[10px]">TOC</span>
    </button>

    {#if !isImageBook}
      <button
        class="flex flex-col items-center gap-0.5 py-1 px-3 rounded-lg transition-colors {actionBtnClass}"
        onclick={() => onsearch?.()}
        aria-label="Search"
      >
        <Search size={20} />
        <span class="text-[10px]">Search</span>
      </button>

      <button
        class="flex flex-col items-center gap-0.5 py-1 px-3 rounded-lg transition-colors relative {actionBtnClass}"
        onclick={() => onhighlights?.()}
        aria-label="Highlights{highlightCount > 0
          ? ` (${highlightCount})`
          : ''}"
      >
        <Highlighter size={20} />
        <span class="text-[10px]">Highlights</span>
        {#if highlightCount > 0}
          <span
            class="absolute -top-0.5 right-0.5 min-w-[16px] h-4 rounded-full text-[9px] font-bold flex items-center justify-center px-1 {darkMode
              ? 'bg-amber-500/30 text-amber-400'
              : 'bg-primary text-primary-foreground'}"
          >
            {highlightCount > 99 ? "99+" : highlightCount}
          </span>
        {/if}
      </button>

      <button
        class="flex flex-col items-center gap-0.5 py-1 px-3 rounded-lg transition-colors {offline
          ? 'opacity-25'
          : actionBtnClass}"
        onclick={() => {
          if (offline) {
            toastStore.info("AI features require an internet connection");
            return;
          }
          oncompanion?.();
        }}
        aria-label="AI Companion"
        aria-disabled={offline || undefined}
      >
        <MessageCircle size={20} />
        <span class="text-[10px]">AI</span>
      </button>
    {/if}

    <button
      class="flex flex-col items-center gap-0.5 py-1 px-3 rounded-lg transition-colors {actionBtnClass}"
      onclick={() => onsettings?.()}
      aria-label="Reader settings"
    >
      <Settings size={20} />
      <span class="text-[10px]">Settings</span>
    </button>
  </div>
</div>
