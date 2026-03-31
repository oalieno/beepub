<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    open = $bindable(false),
    children,
  }: {
    open?: boolean;
    children?: Snippet;
  } = $props();

  function close() {
    open = false;
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") close();
  }
</script>

<svelte:window onkeydown={open ? handleKeydown : undefined} />

{#if open}
  <div class="fixed inset-0 z-50" role="dialog" aria-modal="true">
    <button
      class="absolute inset-0 bg-black/40 backdrop-blur-sm"
      aria-label="Close"
      onclick={close}
    ></button>

    <div
      class="absolute bottom-0 left-0 right-0 bg-card rounded-t-2xl shadow-2xl animate-slide-up"
      style="padding-bottom: max(0.5rem, env(safe-area-inset-bottom, 0px));"
    >
      <div class="flex justify-center pt-3 pb-1">
        <div class="w-9 h-1 rounded-full bg-muted-foreground/20"></div>
      </div>
      <div class="px-4">
        {#if children}{@render children()}{/if}
      </div>
    </div>
  </div>
{/if}

<style>
  @keyframes slide-up {
    from {
      transform: translateY(100%);
    }
    to {
      transform: translateY(0);
    }
  }
  .animate-slide-up {
    animation: slide-up 0.25s ease-out;
  }
</style>
