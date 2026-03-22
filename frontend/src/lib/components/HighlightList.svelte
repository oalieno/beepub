<script lang="ts">
  import { Trash2, Share2 } from "@lucide/svelte";
  import type { HighlightOut } from "$lib/types";

  let {
    highlights = [],
    showBookTitle = false,
    bookTitles = {},
    darkMode = false,
    onselect,
    ondelete,
    onshare,
  }: {
    highlights?: HighlightOut[];
    showBookTitle?: boolean;
    bookTitles?: Record<string, string>;
    darkMode?: boolean;
    onselect?: (highlight: HighlightOut) => void;
    ondelete?: (highlight: HighlightOut) => void;
    onshare?: (highlight: HighlightOut) => void;
  } = $props();

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

  function truncate(text: string, max = 120): string {
    if (text.length <= max) return text;
    return text.slice(0, max).trimEnd() + "…";
  }
</script>

{#if highlights.length === 0}
  <p
    class="text-sm {darkMode
      ? 'text-gray-500'
      : 'text-muted-foreground'} py-4 text-center"
  >
    No highlights yet.
  </p>
{:else}
  <div class="flex flex-col gap-1">
    {#each highlights as hl (hl.id)}
      <div
        class="w-full text-left px-3 py-2.5 rounded-lg transition-colors flex gap-2.5 items-start cursor-pointer {darkMode
          ? 'hover:bg-gray-800'
          : 'hover:bg-accent'}"
        role="button"
        tabindex="0"
        onclick={() => onselect?.(hl)}
        onkeydown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onselect?.(hl);
          }
        }}
      >
        <div class="flex-1 min-w-0">
          {#if showBookTitle && bookTitles[hl.book_id]}
            <p
              class="text-xs font-medium mb-0.5 {darkMode
                ? 'text-gray-400'
                : 'text-muted-foreground'}"
            >
              {bookTitles[hl.book_id]}
            </p>
          {/if}
          <p
            class="text-sm leading-snug {darkMode
              ? 'text-gray-200'
              : 'text-foreground'}"
          >
            {truncate(hl.text)}
          </p>
          {#if hl.note}
            <p
              class="text-xs mt-1 italic {darkMode
                ? 'text-gray-500'
                : 'text-muted-foreground'}"
            >
              {truncate(hl.note, 80)}
            </p>
          {/if}
          <p
            class="text-[10px] mt-1 {darkMode
              ? 'text-gray-600'
              : 'text-muted-foreground/60'}"
          >
            {formatDate(hl.created_at)}
          </p>
        </div>
        <div class="self-center flex items-center gap-1 flex-shrink-0">
          {#if onshare}
            <button
              class="p-2 rounded-md transition-all cursor-pointer {darkMode
                ? 'text-gray-500 hover:text-gray-300 hover:bg-gray-800 active:bg-gray-700'
                : 'text-muted-foreground hover:text-foreground hover:bg-accent active:bg-accent/80'}"
              title="Share as card"
              onclick={(e) => {
                e.stopPropagation();
                onshare?.(hl);
              }}
            >
              <Share2 size={16} />
            </button>
          {/if}
          {#if ondelete}
            <button
              class="p-2 rounded-md transition-all cursor-pointer {darkMode
                ? 'text-gray-500 hover:text-red-400 hover:bg-gray-800 active:bg-red-900/30'
                : 'text-muted-foreground hover:text-destructive hover:bg-accent active:bg-destructive/10'}"
              title="Delete highlight"
              onclick={(e) => {
                e.stopPropagation();
                ondelete?.(hl);
              }}
            >
              <Trash2 size={16} />
            </button>
          {/if}
        </div>
      </div>
    {/each}
  </div>
{/if}
