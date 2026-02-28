<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { X } from 'lucide-svelte';

  export let title = '';
  export let open = false;

  const dispatch = createEventDispatcher();

  function close() {
    dispatch('close');
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') close();
  }
</script>

{#if open}
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
    <!-- Backdrop -->
    <button
      class="absolute inset-0 bg-black/60 backdrop-blur-sm"
      aria-label="Close modal"
      on:click={close}
    ></button>

    <!-- Panel -->
    <div
      class="relative bg-gray-800 rounded-xl shadow-2xl w-full max-w-lg border border-gray-700"
      role="document"
    >
      <!-- Header -->
      <div class="flex items-center justify-between px-6 py-4 border-b border-gray-700">
        <h2 class="text-lg font-semibold text-white">{title}</h2>
        <button
          class="text-gray-400 hover:text-white transition-colors"
          on:click={close}
          aria-label="Close"
        >
          <X size={20} />
        </button>
      </div>

      <!-- Content -->
      <div class="px-6 py-4">
        <slot />
      </div>
    </div>
  </div>
{/if}

<svelte:window on:keydown={handleKeydown} />
