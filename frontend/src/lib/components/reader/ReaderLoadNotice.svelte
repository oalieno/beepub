<script lang="ts">
  /**
   * The reader's one notice for a chapter that could not be shown: the
   * reader is still on the page they were on, and this says why and
   * offers to try again. It stays until they do, move on, or put it away
   * — it is a state, not a passing confirmation, so not a toast. Fixed
   * under the top bar and above the sidebars: a tap on a chapter the
   * table of contents marks unavailable is answered right there.
   */
  import { X } from "@lucide/svelte";
  import { Button } from "$lib/components/ui/button";
  import * as m from "$lib/paraglide/messages.js";

  let {
    offline = false,
    darkMode = false,
    onretry,
    ondismiss,
  }: {
    /** No connection: the wording says so. */
    offline?: boolean;
    darkMode?: boolean;
    onretry?: () => void;
    ondismiss?: () => void;
  } = $props();

  const buttonClass = $derived(
    darkMode ? "text-ink-100 hover:bg-ink-700 hover:text-white" : "",
  );
</script>

<div
  class="pointer-events-none fixed inset-x-0 z-[60] flex justify-center px-4"
  style="top: calc(env(safe-area-inset-top, 0px) + 3.75rem);"
>
  <div
    role="status"
    aria-live="polite"
    data-testid="reader-load-notice"
    class="pointer-events-auto flex max-w-full items-center gap-1 rounded-xl border py-1 pl-4 pr-1 text-sm shadow-lg {darkMode
      ? 'border-ink-700 bg-ink-800 text-ink-100'
      : 'border-border bg-card text-foreground'}"
  >
    <span class="min-w-0 py-1">
      {offline ? m.reader_chapter_offline() : m.reader_chapter_load_failed()}
    </span>
    <Button
      variant="ghost"
      size="sm"
      class="text-primary {buttonClass}"
      onclick={() => onretry?.()}
    >
      {m.common_retry()}
    </Button>
    <Button
      variant="ghost"
      size="icon-sm"
      class={buttonClass}
      aria-label={m.common_close()}
      onclick={() => ondismiss?.()}
    >
      <X />
    </Button>
  </div>
</div>
