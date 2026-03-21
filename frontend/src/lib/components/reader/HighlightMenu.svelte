<script lang="ts">
  import {
    Trash2,
    X,
    Sparkles,
    Copy,
    Share2,
    Highlighter,
    MessageCircle,
  } from "@lucide/svelte";

  let {
    hasExisting = false,
    onhighlight,
    onremove,
    onillustrate,
    oncompanion,
    oncopy,
    onshare,
    onclose,
  }: {
    hasExisting?: boolean;
    onhighlight?: () => void;
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
    <button
      class="p-0.5 transition-colors hover:scale-110 transform text-muted-foreground hover:text-foreground"
      title="Highlight"
      onclick={() => onhighlight?.()}
    >
      <Highlighter size={14} />
    </button>
    <div class="w-px h-4 bg-border"></div>
  {/if}

  <button
    class="p-0.5 transition-colors hover:scale-110 transform text-muted-foreground hover:text-foreground"
    title="Copy"
    onclick={() => oncopy?.()}
  >
    <Copy size={14} />
  </button>

  {#if hasExisting}
    <div class="w-px h-4 bg-border"></div>
    <button
      class="p-0.5 transition-colors hover:scale-110 transform text-muted-foreground hover:text-foreground"
      title="Share as card"
      onclick={() => onshare?.()}
    >
      <Share2 size={14} />
    </button>
  {/if}

  <div class="w-px h-4 bg-border"></div>
  <button
    class="p-0.5 transition-colors hover:scale-110 transform text-muted-foreground hover:text-foreground"
    title="AI Illustration"
    onclick={() => onillustrate?.()}
  >
    <Sparkles size={14} />
  </button>

  <div class="w-px h-4 bg-border"></div>
  <button
    class="p-0.5 transition-colors hover:scale-110 transform text-muted-foreground hover:text-foreground"
    title="Ask Companion"
    onclick={() => oncompanion?.()}
  >
    <MessageCircle size={14} />
  </button>

  {#if hasExisting}
    <div class="w-px h-4 bg-border"></div>
    <button
      class="text-destructive hover:text-destructive/80 transition-colors p-0.5"
      title="Remove highlight"
      onclick={() => onremove?.()}
    >
      <Trash2 size={14} />
    </button>
  {/if}

  <div class="w-px h-4 bg-border"></div>
  <button
    class="text-muted-foreground hover:text-foreground transition-colors p-0.5"
    onclick={() => onclose?.()}
  >
    <X size={14} />
  </button>
</div>
