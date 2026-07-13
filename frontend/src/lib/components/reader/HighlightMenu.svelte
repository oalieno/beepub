<script lang="ts">
  import {
    Trash2,
    X,
    Sparkles,
    Copy,
    Share2,
    Highlighter,
    MessageCircle,
    NotebookPen,
  } from "@lucide/svelte";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";

  let {
    hasExisting = false,
    offline = false,
    showAi = true,
    onhighlight,
    onnote,
    onremove,
    onillustrate,
    oncompanion,
    oncopy,
    onshare,
    onclose,
  }: {
    hasExisting?: boolean;
    offline?: boolean;
    /** AI actions are BeePub-server features; hidden for other backends. */
    showAi?: boolean;
    onhighlight?: () => void;
    onnote?: () => void;
    onremove?: () => void;
    onillustrate?: () => void;
    oncompanion?: () => void;
    oncopy?: () => void;
    onshare?: () => void;
    onclose?: () => void;
  } = $props();
</script>

<div
  class="bg-card border border-border rounded-lg shadow-xl px-3 py-2 flex items-center gap-2"
>
  {#if !hasExisting}
    <!-- The one action people came for gets a labeled primary pill — as a
         same-weight icon it was mistaken for the Highlights panel. -->
    <button
      class="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-md px-2.5 py-1 text-xs font-medium hover:bg-primary/90 transition-colors whitespace-nowrap"
      onclick={() => onhighlight?.()}
    >
      <Highlighter size={13} />
      {m.highlight_action_highlight()}
    </button>
    <div class="w-px h-4 bg-border"></div>
  {/if}

  <button
    class="p-0.5 transition-colors hover:scale-110 transform text-muted-foreground hover:text-foreground"
    title={m.highlight_action_copy()}
    onclick={() => oncopy?.()}
  >
    <Copy size={14} />
  </button>

  <div class="w-px h-4 bg-border"></div>
  <button
    class="p-0.5 transition-colors hover:scale-110 transform text-muted-foreground hover:text-foreground"
    title={m.highlight_action_note()}
    onclick={() => onnote?.()}
  >
    <NotebookPen size={14} />
  </button>

  {#if hasExisting}
    <div class="w-px h-4 bg-border"></div>
    <button
      class="p-0.5 transition-colors hover:scale-110 transform text-muted-foreground hover:text-foreground"
      title={m.highlight_action_share()}
      onclick={() => onshare?.()}
    >
      <Share2 size={14} />
    </button>
  {/if}

  {#if showAi}
    <div class="w-px h-4 bg-border"></div>
    <button
      class="p-0.5 transition-colors transform {offline
        ? 'text-muted-foreground/40 cursor-not-allowed'
        : 'text-muted-foreground hover:text-foreground hover:scale-110'}"
      title={offline ? m.reader_ai_offline() : m.highlight_action_illustrate()}
      aria-disabled={offline || undefined}
      onclick={() => {
        if (offline) {
          toastStore.info(m.reader_ai_offline());
          return;
        }
        onillustrate?.();
      }}
    >
      <Sparkles size={14} />
    </button>

    <div class="w-px h-4 bg-border"></div>
    <button
      class="p-0.5 transition-colors transform {offline
        ? 'text-muted-foreground/40 cursor-not-allowed'
        : 'text-muted-foreground hover:text-foreground hover:scale-110'}"
      title={offline ? m.reader_ai_offline() : m.highlight_action_companion()}
      aria-disabled={offline || undefined}
      onclick={() => {
        if (offline) {
          toastStore.info(m.reader_ai_offline());
          return;
        }
        oncompanion?.();
      }}
    >
      <MessageCircle size={14} />
    </button>
  {/if}

  {#if hasExisting}
    <div class="w-px h-4 bg-border"></div>
    <button
      class="text-destructive hover:text-destructive/80 transition-colors p-0.5"
      title={m.highlight_action_remove()}
      onclick={() => onremove?.()}
    >
      <Trash2 size={14} />
    </button>
  {/if}

  <div class="w-px h-4 bg-border"></div>
  <button
    aria-label={m.common_close()}
    class="text-muted-foreground hover:text-foreground transition-colors p-0.5"
    onclick={() => onclose?.()}
  >
    <X size={14} />
  </button>
</div>
