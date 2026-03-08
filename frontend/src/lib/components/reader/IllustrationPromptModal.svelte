<script lang="ts">
  import { X, Sparkles, Loader2 } from "@lucide/svelte";
  import type { StylePromptOut } from "$lib/types";

  let {
    text = "",
    styles = [],
    darkMode = false,
    oncreate,
    onclose,
  }: {
    text?: string;
    styles?: StylePromptOut[];
    darkMode?: boolean;
    oncreate?: (detail: {
      style_prompt?: string;
      custom_prompt?: string;
    }) => void;
    onclose?: () => void;
  } = $props();

  let selectedStyle = $state<string | null>(null);
  let customPrompt = $state("");
  let useCustom = $state(false);

  function handleGenerate() {
    if (useCustom && customPrompt.trim()) {
      oncreate?.({ custom_prompt: customPrompt.trim() });
    } else if (selectedStyle) {
      oncreate?.({ style_prompt: selectedStyle });
    }
  }

  function selectStyle(key: string) {
    selectedStyle = key;
    useCustom = false;
  }

  function toggleCustom() {
    useCustom = !useCustom;
    if (useCustom) selectedStyle = null;
  }

  let canGenerate = $derived(
    (useCustom && customPrompt.trim().length > 0) ||
      (!useCustom && selectedStyle !== null),
  );
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="fixed inset-0 z-[60] flex items-center justify-center p-4"
  onclick={() => onclose?.()}
  onkeydown={(e) => {
    if (e.key === "Escape") onclose?.();
  }}
>
  <!-- Backdrop -->
  <div class="absolute inset-0 bg-black/50"></div>

  <!-- Modal -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="relative w-full max-w-lg max-h-[85vh] overflow-y-auto rounded-xl shadow-2xl {darkMode
      ? 'bg-gray-900 border border-gray-700'
      : 'bg-card border border-border'}"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
  >
    <!-- Header -->
    <div
      class="flex items-center justify-between px-5 py-4 border-b {darkMode
        ? 'border-gray-800'
        : 'border-border'}"
    >
      <div class="flex items-center gap-2">
        <Sparkles
          size={18}
          class={darkMode ? "text-purple-400" : "text-purple-500"}
        />
        <h2
          class="text-sm font-semibold {darkMode
            ? 'text-gray-200'
            : 'text-foreground'}"
        >
          AI Illustration
        </h2>
      </div>
      <button
        class="p-1 rounded-md transition-colors {darkMode
          ? 'text-gray-400 hover:bg-gray-800'
          : 'text-muted-foreground hover:bg-accent'}"
        onclick={() => onclose?.()}
      >
        <X size={16} />
      </button>
    </div>

    <div class="px-5 py-4 space-y-4">
      <!-- Selected text preview -->
      <div class="rounded-lg p-3 {darkMode ? 'bg-gray-800' : 'bg-muted'}">
        <p
          class="text-[10px] uppercase tracking-wider mb-1 {darkMode
            ? 'text-gray-500'
            : 'text-muted-foreground'}"
        >
          Selected text
        </p>
        <p
          class="text-sm leading-relaxed {darkMode
            ? 'text-gray-300'
            : 'text-foreground'} line-clamp-4"
        >
          {text}
        </p>
      </div>

      <!-- Style presets -->
      <div>
        <p
          class="text-xs font-medium mb-2 {darkMode
            ? 'text-gray-400'
            : 'text-muted-foreground'}"
        >
          Choose a style
        </p>
        <div class="grid grid-cols-2 gap-2">
          {#each styles as style}
            <button
              class="text-left px-3 py-2.5 rounded-lg border transition-all text-sm {selectedStyle ===
                style.key && !useCustom
                ? darkMode
                  ? 'border-purple-500 bg-purple-500/10 text-purple-300'
                  : 'border-purple-500 bg-purple-50 text-purple-700'
                : darkMode
                  ? 'border-gray-700 hover:border-gray-600 text-gray-300'
                  : 'border-border hover:border-foreground/20 text-foreground'}"
              onclick={() => selectStyle(style.key)}
            >
              <span class="font-medium">{style.label}</span>
              <span class="block text-[11px] mt-0.5 opacity-60"
                >{style.description}</span
              >
            </button>
          {/each}
        </div>
      </div>

      <!-- Custom prompt -->
      <div>
        <button
          class="text-xs font-medium mb-2 transition-colors {useCustom
            ? darkMode
              ? 'text-purple-400'
              : 'text-purple-600'
            : darkMode
              ? 'text-gray-500 hover:text-gray-400'
              : 'text-muted-foreground hover:text-foreground'}"
          onclick={toggleCustom}
        >
          {useCustom ? "- Custom prompt" : "+ Custom prompt"}
        </button>
        {#if useCustom}
          <textarea
            bind:value={customPrompt}
            placeholder="Describe the illustration style you want..."
            rows={3}
            class="w-full rounded-lg border px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-purple-500/50 {darkMode
              ? 'bg-gray-800 border-gray-700 text-gray-200 placeholder-gray-600'
              : 'bg-background border-border text-foreground placeholder-muted-foreground'}"
          ></textarea>
        {/if}
      </div>
    </div>

    <!-- Footer -->
    <div
      class="px-5 py-4 border-t flex justify-end gap-2 {darkMode
        ? 'border-gray-800'
        : 'border-border'}"
    >
      <button
        class="px-4 py-2 text-sm rounded-lg transition-colors {darkMode
          ? 'text-gray-400 hover:bg-gray-800'
          : 'text-muted-foreground hover:bg-accent'}"
        onclick={() => onclose?.()}
      >
        Cancel
      </button>
      <button
        class="px-4 py-2 text-sm rounded-lg font-medium transition-all flex items-center gap-1.5 {canGenerate
          ? 'bg-gradient-to-r from-purple-500 via-blue-500 to-pink-500 text-white hover:opacity-90 shadow-md'
          : darkMode
            ? 'bg-gray-800 text-gray-600 cursor-not-allowed'
            : 'bg-muted text-muted-foreground cursor-not-allowed'}"
        disabled={!canGenerate}
        onclick={handleGenerate}
      >
        <Sparkles size={14} />
        Generate
      </button>
    </div>
  </div>
</div>
