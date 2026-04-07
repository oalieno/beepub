<script lang="ts">
  import { X, ChevronDown, ChevronUp } from "@lucide/svelte";
  import type { IllustrationOut } from "$lib/types";
  import { booksApi } from "$lib/api/books";
  import { authedSrc } from "$lib/actions/authedSrc";
  import * as m from "$lib/paraglide/messages.js";

  const STYLE_LABELS: Record<string, string> = $derived({
    ink_wash: m.reader_style_ink_wash(),
    watercolor: m.reader_style_watercolor(),
    pencil_sketch: m.reader_style_pencil_sketch(),
    woodcut: m.reader_style_woodcut(),
    anime: m.illustration_style_light_novel(),
    oil_painting: m.reader_style_oil_painting(),
  });

  let {
    illustration,
    bookId = "",
    darkMode = false,
    onclose,
  }: {
    illustration: IllustrationOut;
    bookId?: string;
    darkMode?: boolean;
    onclose?: () => void;
  } = $props();

  let showText = $state(false);

  function getStyleLabel(ill: IllustrationOut): string {
    if (ill.custom_prompt) return m.reader_style_custom();
    if (ill.style_prompt)
      return STYLE_LABELS[ill.style_prompt] ?? ill.style_prompt;
    return m.reader_style_default();
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="fixed inset-0 z-[70] flex items-center justify-center p-4"
  onclick={() => onclose?.()}
  onkeydown={(e) => {
    if (e.key === "Escape") onclose?.();
  }}
>
  <div class="absolute inset-0 bg-black/70"></div>

  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="relative max-w-2xl w-full max-h-[90vh] overflow-y-auto rounded-xl shadow-2xl {darkMode
      ? 'bg-gray-900'
      : 'bg-card'}"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
  >
    <!-- Close button -->
    <button
      class="absolute top-3 right-3 z-10 p-1.5 rounded-full transition-colors {darkMode
        ? 'bg-gray-800/80 text-gray-400 hover:text-gray-200'
        : 'bg-white/80 text-muted-foreground hover:text-foreground'}"
      onclick={() => onclose?.()}
    >
      <X size={18} />
    </button>

    <!-- Image -->
    <div class="w-full aspect-square bg-black/10 rounded-t-xl overflow-hidden">
      <img
        use:authedSrc={booksApi.getIllustrationImageUrl(
          bookId,
          illustration.id,
        )}
        alt={m.illustration_alt()}
        class="w-full h-full object-contain"
      />
    </div>

    <!-- Info -->
    <div class="px-5 py-4 space-y-2">
      <div class="flex items-center gap-2">
        <span
          class="text-[11px] px-2 py-0.5 rounded-full font-medium bg-gradient-to-r from-purple-500/20 via-blue-500/20 to-pink-500/20 {darkMode
            ? 'text-purple-300'
            : 'text-purple-600'}"
        >
          {getStyleLabel(illustration)}
        </span>
        <div class="flex-1"></div>
        <button
          class="flex items-center gap-1 text-xs transition-colors {darkMode
            ? 'text-gray-500 hover:text-gray-300'
            : 'text-muted-foreground hover:text-foreground'}"
          onclick={() => (showText = !showText)}
        >
          {#if showText}
            <ChevronUp size={14} />
            {m.illustration_hide_source()}
          {:else}
            <ChevronDown size={14} />
            {m.illustration_show_source()}
          {/if}
        </button>
      </div>

      {#if showText}
        <p
          class="text-sm leading-relaxed {darkMode
            ? 'text-gray-300'
            : 'text-foreground'}"
        >
          {illustration.text}
        </p>
        {#if illustration.custom_prompt}
          <p
            class="text-xs italic {darkMode
              ? 'text-gray-500'
              : 'text-muted-foreground'}"
          >
            Prompt: {illustration.custom_prompt}
          </p>
        {/if}
      {/if}
    </div>
  </div>
</div>
