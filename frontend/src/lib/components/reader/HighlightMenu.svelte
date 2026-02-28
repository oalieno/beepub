<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { Trash2, X } from 'lucide-svelte';

  export let hasExisting = false;

  const dispatch = createEventDispatcher<{
    color: { color: string };
    remove: void;
    close: void;
  }>();

  const colors = [
    { name: 'yellow', hex: '#fef08a' },
    { name: 'green', hex: '#bbf7d0' },
    { name: 'blue', hex: '#bfdbfe' },
    { name: 'pink', hex: '#fbcfe8' },
    { name: 'orange', hex: '#fed7aa' },
  ];
</script>

<div class="bg-gray-800 border border-gray-700 rounded-lg shadow-xl px-3 py-2 flex items-center gap-2">
  {#each colors as color}
    <button
      class="w-6 h-6 rounded-full border-2 border-gray-600 hover:border-white transition-colors hover:scale-110 transform"
      style="background-color: {color.hex}"
      title="Highlight {color.name}"
      on:click={() => dispatch('color', { color: color.name })}
    ></button>
  {/each}

  {#if hasExisting}
    <div class="w-px h-4 bg-gray-600"></div>
    <button
      class="text-red-400 hover:text-red-300 transition-colors p-0.5"
      title="Remove highlight"
      on:click={() => dispatch('remove')}
    >
      <Trash2 size={14} />
    </button>
  {/if}

  <div class="w-px h-4 bg-gray-600"></div>
  <button
    class="text-gray-400 hover:text-white transition-colors p-0.5"
    on:click={() => dispatch('close')}
  >
    <X size={14} />
  </button>
</div>
