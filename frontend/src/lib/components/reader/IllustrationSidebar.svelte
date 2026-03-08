<script lang="ts">
  import { X, Trash2, Loader2, Sparkles, AlertCircle } from "@lucide/svelte";
  import type { IllustrationOut } from "$lib/types";
  import { booksApi } from "$lib/api/books";

  const STYLE_LABELS: Record<string, string> = {
    ink_wash: "Ink Wash",
    watercolor: "Watercolor",
    pencil_sketch: "Pencil Sketch",
    woodcut: "Woodcut",
    anime: "Light Novel",
    oil_painting: "Oil Painting",
  };

  let {
    illustrations = [],
    bookId = "",
    darkMode = false,
    onselect,
    ondelete,
    onclose,
  }: {
    illustrations?: IllustrationOut[];
    bookId?: string;
    darkMode?: boolean;
    onselect?: (illustration: IllustrationOut) => void;
    ondelete?: (illustration: IllustrationOut) => void;
    onclose?: () => void;
  } = $props();

  function truncate(text: string, max = 100): string {
    if (text.length <= max) return text;
    return text.slice(0, max).trimEnd() + "…";
  }

  function formatDate(iso: string): string {
    try {
      return new Date(iso).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    } catch {
      return "";
    }
  }

  function getStyleLabel(ill: IllustrationOut): string {
    if (ill.custom_prompt) return "Custom";
    if (ill.style_prompt)
      return STYLE_LABELS[ill.style_prompt] ?? ill.style_prompt;
    return "Default";
  }
</script>

<!-- Backdrop -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="fixed inset-0 z-40 bg-black/20"
  onclick={() => onclose?.()}
  onkeydown={(e) => {
    if (e.key === "Escape") onclose?.();
  }}
></div>

<!-- Sidebar -->
<div
  class="fixed right-0 top-0 bottom-0 z-50 w-80 max-w-[85vw] shadow-2xl flex flex-col {darkMode
    ? 'bg-gray-900 border-l border-gray-800'
    : 'bg-card border-l border-border'}"
>
  <div
    class="flex items-center justify-between px-4 py-3 border-b {darkMode
      ? 'border-gray-800'
      : 'border-border'}"
  >
    <div class="flex items-center gap-2">
      <Sparkles
        size={14}
        class={darkMode ? "text-purple-400" : "text-purple-500"}
      />
      <p
        class="text-sm font-semibold {darkMode
          ? 'text-gray-200'
          : 'text-foreground'}"
      >
        Illustrations
        {#if illustrations.length > 0}
          <span
            class="ml-1.5 text-xs font-normal {darkMode
              ? 'text-gray-500'
              : 'text-muted-foreground'}">{illustrations.length}</span
          >
        {/if}
      </p>
    </div>
    <button
      class="p-1 rounded-md transition-colors {darkMode
        ? 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
        : 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
      onclick={() => onclose?.()}
    >
      <X size={16} />
    </button>
  </div>
  <div class="flex-1 overflow-y-auto p-2">
    {#if illustrations.length === 0}
      <p
        class="text-sm {darkMode
          ? 'text-gray-500'
          : 'text-muted-foreground'} py-4 text-center"
      >
        No illustrations yet.
      </p>
    {:else}
      <div class="flex flex-col gap-1">
        {#each illustrations as ill (ill.id)}
          <div
            class="w-full text-left px-3 py-2.5 rounded-lg transition-colors group {ill.status ===
            'completed'
              ? 'cursor-pointer'
              : ''} {darkMode ? 'hover:bg-gray-800' : 'hover:bg-accent'}"
            role="button"
            tabindex="0"
            onclick={() => {
              if (ill.status === "completed") onselect?.(ill);
            }}
            onkeydown={(e) => {
              if (e.key === "Enter" && ill.status === "completed")
                onselect?.(ill);
            }}
          >
            <div class="flex gap-2.5 items-start">
              <!-- Thumbnail or status indicator -->
              <div
                class="w-12 h-12 rounded-md flex-shrink-0 overflow-hidden {darkMode
                  ? 'bg-gray-800'
                  : 'bg-muted'} flex items-center justify-center"
              >
                {#if ill.status === "completed"}
                  <img
                    src={booksApi.getIllustrationImageUrl(bookId, ill.id)}
                    alt="Illustration"
                    class="w-full h-full object-cover"
                  />
                {:else if ill.status === "generating"}
                  <Loader2
                    size={16}
                    class="animate-spin {darkMode
                      ? 'text-purple-400'
                      : 'text-purple-500'}"
                  />
                {:else if ill.status === "failed"}
                  <AlertCircle size={16} class="text-red-400" />
                {:else}
                  <Loader2
                    size={16}
                    class="animate-spin {darkMode
                      ? 'text-gray-600'
                      : 'text-muted-foreground'}"
                  />
                {/if}
              </div>

              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-1.5 mb-0.5">
                  <span
                    class="text-[10px] px-1.5 py-0.5 rounded-full font-medium {ill.status ===
                    'completed'
                      ? 'bg-gradient-to-r from-purple-500/20 via-blue-500/20 to-pink-500/20 text-purple-400'
                      : ill.status === 'generating'
                        ? darkMode
                          ? 'bg-purple-500/10 text-purple-400'
                          : 'bg-purple-50 text-purple-600'
                        : ill.status === 'failed'
                          ? darkMode
                            ? 'bg-red-500/10 text-red-400'
                            : 'bg-red-50 text-red-600'
                          : darkMode
                            ? 'bg-gray-800 text-gray-500'
                            : 'bg-muted text-muted-foreground'}"
                  >
                    {getStyleLabel(ill)}
                  </span>
                  {#if ill.status === "generating"}
                    <span
                      class="text-[10px] {darkMode
                        ? 'text-purple-400'
                        : 'text-purple-500'}">generating...</span
                    >
                  {:else if ill.status === "failed"}
                    <span class="text-[10px] text-red-400">failed</span>
                  {/if}
                </div>
                <p
                  class="text-xs leading-snug {darkMode
                    ? 'text-gray-300'
                    : 'text-foreground'}"
                >
                  {truncate(ill.text)}
                </p>
                <p
                  class="text-[10px] mt-1 {darkMode
                    ? 'text-gray-600'
                    : 'text-muted-foreground/60'}"
                >
                  {formatDate(ill.created_at)}
                </p>
              </div>

              {#if ondelete}
                <button
                  class="self-center opacity-0 group-hover:opacity-100 p-1 rounded transition-all flex-shrink-0 {darkMode
                    ? 'text-gray-500 hover:text-red-400'
                    : 'text-muted-foreground hover:text-destructive'}"
                  title="Delete illustration"
                  onclick={(e) => {
                    e.stopPropagation();
                    ondelete?.(ill);
                  }}
                >
                  <Trash2 size={13} />
                </button>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>
