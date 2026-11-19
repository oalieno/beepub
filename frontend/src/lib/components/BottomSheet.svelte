<script lang="ts">
  /**
   * A sheet up from the bottom edge, for a short list of actions on a
   * phone. The Sheet, with the handle and the padding these lists share.
   */
  import type { Snippet } from "svelte";
  import * as Sheet from "#lib/components/ui/sheet/index.ts";
  import * as m from "#lib/paraglide/messages.js";

  let {
    open = $bindable(false),
    label = m.book_more_actions(),
    children,
  }: {
    open?: boolean;
    /** What the sheet is, for a screen reader. */
    label?: string;
    children?: Snippet;
  } = $props();

  let sheetEl = $state<HTMLElement | null>(null);
</script>

<Sheet.Root bind:open>
  <Sheet.Content
    bind:ref={sheetEl}
    side="bottom"
    showCloseButton={false}
    overlayClass="bg-black/40"
    aria-label={label}
    onOpenAutoFocus={(e) => {
      // The sheet, not its first row: a focus ring on an action nobody
      // chose reads as a selection.
      e.preventDefault();
      sheetEl?.focus();
    }}
    class="gap-0 text-base border-0! bg-card rounded-t-2xl shadow-2xl outline-none"
    style="padding-bottom: max(0.5rem, env(safe-area-inset-bottom, 0px));"
  >
    <div class="flex justify-center pt-3 pb-1">
      <div class="w-9 h-1 rounded-full bg-muted-foreground/20"></div>
    </div>
    <div class="px-4">
      {#if children}{@render children()}{/if}
    </div>
  </Sheet.Content>
</Sheet.Root>
