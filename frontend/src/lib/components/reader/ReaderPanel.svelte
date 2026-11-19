<script lang="ts">
  /**
   * A panel of the reader that comes in from an edge: the contents, the
   * search, the highlights. One shell for all of them, made of the Sheet
   * (so the keyboard stays inside it while it is open, Escape and a tap
   * outside ask to close it, and it is announced as a dialog) with what the
   * reader needs of a panel:
   *
   * - it is rendered where it stands, not moved to the end of the page:
   *   the reader's own light/dark theme is set on the reader, and a panel
   *   outside it would take the app's;
   * - it does not put the caret in a field on opening (on a phone that
   *   raises the keyboard over the page just uncovered) — the panel
   *   itself takes the focus, and a panel that wants a field focused
   *   does it itself (`focus="own"`);
   * - it is mounted while it is open and gone when it is closed, as the
   *   reader page does it, so there is no closed state to animate from.
   */
  import type { Snippet } from "svelte";
  import * as Sheet from "#lib/components/ui/sheet/index.ts";
  import { cn } from "#lib/utils.ts";

  let {
    side,
    label,
    darkMode = false,
    focus = "panel",
    width = "w-80! max-w-[85vw]!",
    class: className = "",
    overlayClass = "",
    onclose,
    children,
  }: {
    side: "left" | "right";
    /** What the panel is, for a screen reader. */
    label: string;
    darkMode?: boolean;
    focus?: "panel" | "own";
    /** How wide it is (the Sheet's own width is for a narrower panel). */
    width?: string;
    class?: string;
    /** More classes for the scrim (a panel that fades it in itself). */
    overlayClass?: string;
    onclose?: () => void;
    children: Snippet;
  } = $props();

  let panel = $state<HTMLElement | null>(null);
</script>

<!-- Always open: the page mounts a panel to open it and unmounts it to
     close it. So Escape and a tap outside do not close the Sheet — they
     ask the page to (`onclose`), which lets a panel play its own way out
     first. -->
<Sheet.Root open>
  <Sheet.Content
    bind:ref={panel}
    {side}
    showCloseButton={false}
    portalProps={{ disabled: true }}
    overlayClass={cn(
      "z-40 bg-black/20 backdrop-blur-none! animate-none!",
      overlayClass,
    )}
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
      if (focus === "panel") panel?.focus();
    }}
    class={cn(
      "gap-0 text-base shadow-2xl animate-none! outline-none",
      width,
      darkMode
        ? "bg-ink-900 border-ink-800 text-inherit"
        : "bg-card border-border text-inherit",
      className,
    )}
    style="padding-top: env(safe-area-inset-top, 0px);"
  >
    {@render children()}
  </Sheet.Content>
</Sheet.Root>
