<script lang="ts">
  import { X } from '@lucide/svelte';
  import type { Snippet } from 'svelte';

  let { title = '', open = false, onclose, children }: {
    title?: string;
    open?: boolean;
    onclose?: () => void;
    children?: Snippet;
  } = $props();

  function close() {
    onclose?.();
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') close();
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
    <button
      class="absolute inset-0 bg-black/40 backdrop-blur-sm"
      aria-label="Close modal"
      onclick={close}
    ></button>

    <div
      class="relative bg-card rounded-2xl shadow-2xl w-full max-w-lg"
      role="document"
    >
      <div class="flex items-center justify-between px-6 py-5">
        <h2 class="text-lg font-bold text-foreground">{title}</h2>
        <button
          class="w-8 h-8 rounded-full bg-secondary flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors"
          onclick={close}
          aria-label="Close"
        >
          <X size={16} />
        </button>
      </div>

      <div class="px-6 pb-6">
        {#if children}{@render children()}{/if}
      </div>
    </div>
  </div>
{/if}
