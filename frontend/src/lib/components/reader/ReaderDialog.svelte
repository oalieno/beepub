<script lang="ts">
  /**
   * A dialog over the reader's page: the note on a highlight, an
   * illustration and the form that asks for one. The Dialog, with what
   * the reader needs of it (see ReaderPanel, its counterpart for the
   * panels that come in from an edge):
   *
   * - rendered where it stands, so it wears the reader's theme;
   * - mounted while open and gone when closed: Escape and a tap outside
   *   ask the page to close it (`onclose`);
   * - keys pressed inside stay inside. The page under it turns on the
   *   arrow keys and the space bar, and a note being typed must not turn
   *   it.
   */
  import type { Snippet } from "svelte";
  import * as Dialog from "#lib/components/ui/dialog/index.ts";
  import { cn } from "#lib/utils.ts";

  let {
    label,
    focus = "dialog",
    class: className = "",
    overlayClass = "",
    onclose,
    children,
  }: {
    /** What the dialog is, for a screen reader. */
    label: string;
    /** Where the focus goes on opening: the dialog itself, or wherever
     *  the content puts it ("own" — a field it focuses itself). */
    focus?: "dialog" | "own";
    class?: string;
    overlayClass?: string;
    onclose?: () => void;
    children: Snippet;
  } = $props();

  let dialog = $state<HTMLElement | null>(null);
</script>

<Dialog.Root open>
  <Dialog.Content
    bind:ref={dialog}
    showCloseButton={false}
    portalProps={{ disabled: true }}
    overlayClass={cn("backdrop-blur-none animate-none!", overlayClass)}
    aria-label={label}
    onEscapeKeydown={(e) => {
      e.preventDefault();
      onclose?.();
    }}
    onInteractOutside={(e) => {
      e.preventDefault();
      onclose?.();
    }}
    onOpenAutoFocus={(e) => {
      e.preventDefault();
      if (focus === "dialog") dialog?.focus();
    }}
    onkeydown={(e) => {
      // (Escape is answered here: stopped, it never reaches the layer
      // that would have answered it.)
      if (e.key === "Escape") onclose?.();
      e.stopPropagation();
    }}
    class={cn(
      "block gap-0 border-0 p-0 text-base shadow-2xl outline-none animate-none!",
      className,
    )}
  >
    {@render children()}
  </Dialog.Content>
</Dialog.Root>
