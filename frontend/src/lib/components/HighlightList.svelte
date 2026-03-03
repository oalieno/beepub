<script lang="ts">
  import { Trash2 } from '@lucide/svelte';
  import type { HighlightOut } from '$lib/types';

  const HIGHLIGHT_COLORS: Record<string, string> = {
    yellow: '#fef08a',
    green: '#bbf7d0',
    blue: '#bfdbfe',
    pink: '#fbcfe8',
    orange: '#fed7aa',
  };

  let {
    highlights = [],
    showBookTitle = false,
    bookTitles = {},
    darkMode = false,
    onselect,
    ondelete,
  }: {
    highlights?: HighlightOut[];
    showBookTitle?: boolean;
    bookTitles?: Record<string, string>;
    darkMode?: boolean;
    onselect?: (highlight: HighlightOut) => void;
    ondelete?: (highlight: HighlightOut) => void;
  } = $props();

  function formatDate(iso: string): string {
    try {
      return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    } catch {
      return '';
    }
  }

  function truncate(text: string, max = 120): string {
    if (text.length <= max) return text;
    return text.slice(0, max).trimEnd() + '…';
  }
</script>

{#if highlights.length === 0}
  <p class="text-sm {darkMode ? 'text-gray-500' : 'text-muted-foreground'} py-4 text-center">No highlights yet.</p>
{:else}
  <div class="flex flex-col gap-1">
    {#each highlights as hl (hl.id)}
      <button
        class="w-full text-left px-3 py-2.5 rounded-lg transition-colors group flex gap-2.5 items-start {darkMode ? 'hover:bg-gray-800' : 'hover:bg-accent'}"
        onclick={() => onselect?.(hl)}
      >
        <span
          class="mt-1 w-2.5 h-2.5 rounded-full flex-shrink-0 ring-1 ring-black/10"
          style="background-color: {HIGHLIGHT_COLORS[hl.color] ?? HIGHLIGHT_COLORS.yellow}"
        ></span>
        <div class="flex-1 min-w-0">
          {#if showBookTitle && bookTitles[hl.book_id]}
            <p class="text-xs font-medium mb-0.5 {darkMode ? 'text-gray-400' : 'text-muted-foreground'}">{bookTitles[hl.book_id]}</p>
          {/if}
          <p class="text-sm leading-snug {darkMode ? 'text-gray-200' : 'text-foreground'}">
            {truncate(hl.text)}
          </p>
          {#if hl.note}
            <p class="text-xs mt-1 italic {darkMode ? 'text-gray-500' : 'text-muted-foreground'}">{truncate(hl.note, 80)}</p>
          {/if}
          <p class="text-[10px] mt-1 {darkMode ? 'text-gray-600' : 'text-muted-foreground/60'}">{formatDate(hl.created_at)}</p>
        </div>
        {#if ondelete}
          <button
            class="self-center opacity-0 group-hover:opacity-100 p-1 rounded transition-all flex-shrink-0 {darkMode ? 'text-gray-500 hover:text-red-400' : 'text-muted-foreground hover:text-destructive'}"
            title="Delete highlight"
            onclick={(e) => { e.stopPropagation(); ondelete?.(hl); }}
          >
            <Trash2 size={13} />
          </button>
        {/if}
      </button>
    {/each}
  </div>
{/if}
