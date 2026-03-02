<script lang="ts">
  import { Trash2, X } from '@lucide/svelte';

  let { hasExisting = false, oncolor, onremove, onclose }: {
    hasExisting?: boolean;
    oncolor?: (detail: { color: string }) => void;
    onremove?: () => void;
    onclose?: () => void;
  } = $props();

  const colors = [
    { name: 'yellow', hex: '#fef08a' },
    { name: 'green', hex: '#bbf7d0' },
    { name: 'blue', hex: '#bfdbfe' },
    { name: 'pink', hex: '#fbcfe8' },
    { name: 'orange', hex: '#fed7aa' },
  ];
</script>

<div class="bg-card border border-border rounded-lg shadow-xl px-3 py-2 flex items-center gap-2">
  {#each colors as color}
    <button
      class="w-6 h-6 rounded-full border-2 border-border hover:border-foreground transition-colors hover:scale-110 transform"
      style="background-color: {color.hex}"
      title="Highlight {color.name}"
      onclick={() => oncolor?.({ color: color.name })}
    ></button>
  {/each}

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
