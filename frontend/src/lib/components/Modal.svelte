<script lang="ts">
  import { X } from "@lucide/svelte";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as m from "$lib/paraglide/messages.js";
  import type { Snippet } from "svelte";

  let {
    title = "",
    open = false,
    onclose,
    children,
  }: {
    title?: string;
    open?: boolean;
    onclose?: () => void;
    children?: Snippet;
  } = $props();
</script>

<!-- Thin wrapper over the shared ui/dialog primitives so every modal gets
     the same focus trap, Escape handling, scroll lock, and portal. -->
<Dialog.Root
  {open}
  onOpenChange={(o) => {
    if (!o) onclose?.();
  }}
>
  <Dialog.Content
    class="bg-card rounded-2xl p-0 gap-0 flex flex-col sm:max-w-lg max-h-[calc(100dvh-2rem)]"
    showCloseButton={false}
  >
    <div class="flex items-center justify-between px-6 py-5 shrink-0">
      <Dialog.Title class="text-lg font-bold text-foreground"
        >{title}</Dialog.Title
      >
      <button
        class="w-8 h-8 rounded-full bg-secondary flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors"
        onclick={() => onclose?.()}
        aria-label={m.common_close()}
      >
        <X size={16} />
      </button>
    </div>

    <div class="px-6 pb-6 overflow-y-auto">
      {#if children}{@render children()}{/if}
    </div>
  </Dialog.Content>
</Dialog.Root>
