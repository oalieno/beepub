<script lang="ts">
  import { X } from '@lucide/svelte';
  import HighlightList from '$lib/components/HighlightList.svelte';
  import type { HighlightOut } from '$lib/types';

  let {
    highlights = [],
    darkMode = false,
    onselect,
    ondelete,
    onclose,
  }: {
    highlights?: HighlightOut[];
    darkMode?: boolean;
    onselect?: (highlight: HighlightOut) => void;
    ondelete?: (highlight: HighlightOut) => void;
    onclose?: () => void;
  } = $props();
</script>

<!-- Backdrop -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="fixed inset-0 z-40 bg-black/20"
  onclick={() => onclose?.()}
  onkeydown={(e) => { if (e.key === 'Escape') onclose?.(); }}
></div>

<!-- Sidebar -->
<div class="fixed right-0 top-0 bottom-0 z-50 w-80 max-w-[85vw] shadow-2xl flex flex-col {darkMode ? 'bg-gray-900 border-l border-gray-800' : 'bg-card border-l border-border'}">
  <div class="flex items-center justify-between px-4 py-3 border-b {darkMode ? 'border-gray-800' : 'border-border'}">
    <p class="text-sm font-semibold {darkMode ? 'text-gray-200' : 'text-foreground'}">
      Highlights
      {#if highlights.length > 0}
        <span class="ml-1.5 text-xs font-normal {darkMode ? 'text-gray-500' : 'text-muted-foreground'}">{highlights.length}</span>
      {/if}
    </p>
    <button
      class="p-1 rounded-md transition-colors {darkMode ? 'text-gray-400 hover:bg-gray-800 hover:text-gray-200' : 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
      onclick={() => onclose?.()}
    >
      <X size={16} />
    </button>
  </div>
  <div class="flex-1 overflow-y-auto p-2">
    <HighlightList {highlights} {darkMode} {onselect} {ondelete} />
  </div>
</div>
