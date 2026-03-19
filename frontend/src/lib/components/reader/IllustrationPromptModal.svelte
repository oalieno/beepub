<script lang="ts">
  import { X, Sparkles, Check, ImageIcon, Loader2 } from "@lucide/svelte";
  import type {
    StylePromptOut,
    IllustrationOut,
    EpubImageInfo,
    ReferenceImageInput,
  } from "$lib/types";
  import { booksApi } from "$lib/api/books";

  const MAX_REFS = 4;

  let {
    text = "",
    styles = [],
    darkMode = false,
    bookId = "",
    token = "",
    completedIllustrations = [],
    oncreate,
    onclose,
  }: {
    text?: string;
    styles?: StylePromptOut[];
    darkMode?: boolean;
    bookId?: string;
    token?: string;
    completedIllustrations?: IllustrationOut[];
    oncreate?: (detail: {
      style_prompt?: string;
      custom_prompt?: string;
      reference_images?: ReferenceImageInput[];
    }) => void;
    onclose?: () => void;
  } = $props();

  let selectedStyle = $state<string | null>(null);
  let customPrompt = $state("");
  let useCustom = $state(false);

  // Reference images state
  let showRefs = $state(false);
  let selectedRefs = $state<ReferenceImageInput[]>([]);
  let epubImages = $state<EpubImageInfo[]>([]);
  let loadingEpubImages = $state(false);
  let epubImagesLoaded = $state(false);

  function handleGenerate() {
    const detail: {
      style_prompt?: string;
      custom_prompt?: string;
      reference_images?: ReferenceImageInput[];
    } = {};
    if (useCustom && customPrompt.trim()) {
      detail.custom_prompt = customPrompt.trim();
    } else if (selectedStyle) {
      detail.style_prompt = selectedStyle;
    }
    if (selectedRefs.length > 0) {
      detail.reference_images = selectedRefs;
    }
    oncreate?.(detail);
  }

  function selectStyle(key: string) {
    selectedStyle = key;
    useCustom = false;
  }

  function toggleCustom() {
    useCustom = !useCustom;
    if (useCustom) selectedStyle = null;
  }

  async function toggleRefs() {
    showRefs = !showRefs;
    if (showRefs && !epubImagesLoaded && token && bookId) {
      loadingEpubImages = true;
      try {
        epubImages = await booksApi.getEpubImages(bookId, token);
      } catch {
        epubImages = [];
      } finally {
        loadingEpubImages = false;
        epubImagesLoaded = true;
      }
    }
  }

  function toggleRef(ref: ReferenceImageInput) {
    const idx = selectedRefs.findIndex(
      (r) => r.source === ref.source && r.path === ref.path,
    );
    if (idx >= 0) {
      selectedRefs = selectedRefs.filter((_, i) => i !== idx);
    } else if (selectedRefs.length < MAX_REFS) {
      selectedRefs = [...selectedRefs, ref];
    }
  }

  function isSelected(source: string, path: string): boolean {
    return selectedRefs.some((r) => r.source === source && r.path === path);
  }

  let canGenerate = $derived(
    (useCustom && customPrompt.trim().length > 0) ||
      (!useCustom && selectedStyle !== null) ||
      selectedRefs.length > 0,
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

      <!-- Reference images -->
      <div>
        <button
          class="text-xs font-medium mb-2 transition-colors flex items-center gap-1 {showRefs
            ? darkMode
              ? 'text-purple-400'
              : 'text-purple-600'
            : darkMode
              ? 'text-gray-500 hover:text-gray-400'
              : 'text-muted-foreground hover:text-foreground'}"
          onclick={toggleRefs}
        >
          <ImageIcon size={12} />
          {showRefs ? "- Reference images" : "+ Reference images"}
          {#if selectedRefs.length > 0}
            <span
              class="ml-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold {darkMode
                ? 'bg-purple-500/20 text-purple-300'
                : 'bg-purple-100 text-purple-700'}"
            >
              {selectedRefs.length}/{MAX_REFS}
            </span>
          {/if}
        </button>

        {#if showRefs}
          <div
            class="space-y-3 rounded-lg border p-3 {darkMode
              ? 'border-gray-700 bg-gray-800/50'
              : 'border-border bg-muted/50'}"
          >
            <!-- Book images -->
            <div>
              <p
                class="text-[10px] uppercase tracking-wider mb-2 {darkMode
                  ? 'text-gray-500'
                  : 'text-muted-foreground'}"
              >
                Book images
              </p>
              {#if loadingEpubImages}
                <div
                  class="flex items-center gap-2 py-4 justify-center {darkMode
                    ? 'text-gray-500'
                    : 'text-muted-foreground'}"
                >
                  <Loader2 size={14} class="animate-spin" />
                  <span class="text-xs">Loading...</span>
                </div>
              {:else if epubImages.length === 0}
                <p
                  class="text-xs py-2 {darkMode
                    ? 'text-gray-600'
                    : 'text-muted-foreground'}"
                >
                  No images found in this book
                </p>
              {:else}
                <div
                  class="grid grid-cols-4 gap-2 max-h-36 overflow-y-auto"
                >
                  {#each epubImages as img}
                    {@const selected = isSelected("epub", img.path)}
                    <button
                      class="relative aspect-square rounded-lg overflow-hidden border-2 transition-all {selected
                        ? 'border-purple-500 ring-2 ring-purple-500/30'
                        : selectedRefs.length >= MAX_REFS
                          ? darkMode
                            ? 'border-gray-700 opacity-40 cursor-not-allowed'
                            : 'border-border opacity-40 cursor-not-allowed'
                          : darkMode
                            ? 'border-gray-700 hover:border-gray-500'
                            : 'border-border hover:border-foreground/30'}"
                      onclick={() =>
                        toggleRef({ source: "epub", path: img.path })}
                      disabled={!selected && selectedRefs.length >= MAX_REFS}
                      title={img.name}
                    >
                      <img
                        src="/api/books/{bookId}/content/{img.path}"
                        alt={img.name}
                        class="w-full h-full object-cover"
                        loading="lazy"
                      />
                      {#if selected}
                        <div
                          class="absolute inset-0 bg-purple-500/20 flex items-center justify-center"
                        >
                          <div
                            class="bg-purple-500 rounded-full p-0.5"
                          >
                            <Check size={10} class="text-white" />
                          </div>
                        </div>
                      {/if}
                    </button>
                  {/each}
                </div>
              {/if}
            </div>

            <!-- Generated illustrations -->
            {#if completedIllustrations.length > 0}
              <div>
                <p
                  class="text-[10px] uppercase tracking-wider mb-2 {darkMode
                    ? 'text-gray-500'
                    : 'text-muted-foreground'}"
                >
                  Generated illustrations
                </p>
                <div
                  class="grid grid-cols-4 gap-2 max-h-36 overflow-y-auto"
                >
                  {#each completedIllustrations as ill}
                    {@const selected = isSelected("illustration", ill.id)}
                    <button
                      class="relative aspect-square rounded-lg overflow-hidden border-2 transition-all {selected
                        ? 'border-purple-500 ring-2 ring-purple-500/30'
                        : selectedRefs.length >= MAX_REFS
                          ? darkMode
                            ? 'border-gray-700 opacity-40 cursor-not-allowed'
                            : 'border-border opacity-40 cursor-not-allowed'
                          : darkMode
                            ? 'border-gray-700 hover:border-gray-500'
                            : 'border-border hover:border-foreground/30'}"
                      onclick={() =>
                        toggleRef({
                          source: "illustration",
                          path: ill.id,
                        })}
                      disabled={!selected && selectedRefs.length >= MAX_REFS}
                      title={ill.text.slice(0, 60)}
                    >
                      <img
                        src={booksApi.getIllustrationImageUrl(bookId, ill.id)}
                        alt="illustration"
                        class="w-full h-full object-cover"
                        loading="lazy"
                      />
                      {#if selected}
                        <div
                          class="absolute inset-0 bg-purple-500/20 flex items-center justify-center"
                        >
                          <div
                            class="bg-purple-500 rounded-full p-0.5"
                          >
                            <Check size={10} class="text-white" />
                          </div>
                        </div>
                      {/if}
                    </button>
                  {/each}
                </div>
              </div>
            {/if}
          </div>
        {/if}
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
