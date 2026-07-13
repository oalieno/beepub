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
    Underline,
  } from "@lucide/svelte";
  import { toastStore } from "$lib/stores/toast";
  import {
    HIGHLIGHT_COLORS,
    HIGHLIGHT_LINE_COLORS,
    HIGHLIGHT_STYLES,
    encodeHighlightColor,
    parseHighlightColor,
    type HighlightStyle,
  } from "./highlight-style";
  import * as m from "$lib/paraglide/messages.js";

  let {
    hasExisting = false,
    activeRaw = "yellow",
    offline = false,
    showAi = true,
    onhighlight,
    onrestyle,
    onnote,
    onremove,
    onillustrate,
    oncompanion,
    oncopy,
    onshare,
    onclose,
  }: {
    hasExisting?: boolean;
    /** Current color+style: the existing highlight's, or the last used. */
    activeRaw?: string;
    offline?: boolean;
    /** AI actions are BeePub-server features; hidden for other backends. */
    showAi?: boolean;
    onhighlight?: (raw?: string) => void;
    onrestyle?: (raw: string) => void;
    onnote?: () => void;
    onremove?: () => void;
    onillustrate?: () => void;
    oncompanion?: () => void;
    oncopy?: () => void;
    onshare?: () => void;
    onclose?: () => void;
  } = $props();

  let active = $derived(parseHighlightColor(activeRaw));

  // Creation applies immediately (one tap, Apple Books-style); on an
  // existing highlight the same controls restyle it in place.
  function pick(color: string, style: HighlightStyle) {
    const raw = encodeHighlightColor(color, style);
    if (hasExisting) onrestyle?.(raw);
    else onhighlight?.(raw);
  }

  const STYLE_TITLES: Record<HighlightStyle, () => string> = {
    highlight: m.highlight_style_fill,
    underline: m.highlight_style_underline,
    squiggly: m.highlight_style_squiggly,
  };
</script>

<div
  class="bg-card border border-border rounded-lg shadow-xl px-3 py-2 flex flex-col gap-2"
>
  <!-- Color + style picker -->
  <div class="flex items-center gap-2">
    {#each Object.keys(HIGHLIGHT_COLORS) as color}
      <button
        class="w-5 h-5 rounded-full transition-transform hover:scale-110 {active.color ===
        color
          ? 'ring-2 ring-offset-1 ring-foreground/50 ring-offset-card'
          : ''}"
        style="background: {HIGHLIGHT_COLORS[
          color
        ]}; border: 1px solid {HIGHLIGHT_LINE_COLORS[color]};"
        title={m.highlight_action_highlight()}
        aria-label={color}
        onclick={() => pick(color, active.style)}
      ></button>
    {/each}

    <div class="w-px h-4 bg-border"></div>

    {#each HIGHLIGHT_STYLES as style}
      <button
        class="p-1 rounded transition-colors {active.style === style
          ? 'bg-secondary text-foreground'
          : 'text-muted-foreground hover:text-foreground'}"
        title={STYLE_TITLES[style]()}
        onclick={() => pick(active.color, style)}
      >
        {#if style === "highlight"}
          <Highlighter size={14} />
        {:else if style === "underline"}
          <Underline size={14} />
        {:else}
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
          >
            <path d="M2 12 q 2.5 -5 5 0 t 5 0 t 5 0 t 5 0" />
          </svg>
        {/if}
      </button>
    {/each}
  </div>

  <!-- Actions -->
  <div class="flex items-center gap-2">
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
        title={offline
          ? m.reader_ai_offline()
          : m.highlight_action_illustrate()}
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

    <div class="ml-auto"></div>
    <div class="w-px h-4 bg-border"></div>
    <button
      aria-label={m.common_close()}
      class="text-muted-foreground hover:text-foreground transition-colors p-0.5"
      onclick={() => onclose?.()}
    >
      <X size={14} />
    </button>
  </div>
</div>
