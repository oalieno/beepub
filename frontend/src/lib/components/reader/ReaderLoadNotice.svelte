<script lang="ts">
  /**
   * The reader's one notice for a chapter that could not be shown: the
   * reader is still on the page they were on, and this says why and
   * offers to try again. It stays until they do, move on, or put it away
   * — it is a state, not a passing confirmation, so not a toast.
   *
   * It sits where the app's toasts do, at the bottom: above the phone's
   * bottom bar while that shows (`--reader-chrome-offset`), above the
   * safe area otherwise, and above the sidebars — a tap on a chapter the
   * table of contents marks unavailable is answered without covering
   * the list's head. It publishes its height (`--reader-notice-height`)
   * so that toasts stack above it and the list can scroll clear of it.
   *
   * Trying again shows: the button waits (`retrying`) while the attempt
   * is in flight, and an attempt that comes back empty-handed
   * (`failures` goes up) is felt — a small shake, a dip in opacity for
   * reduced motion — and said again to a screen reader.
   */
  import { LoaderCircle, X } from "@lucide/svelte";
  import { Button } from "$lib/components/ui/button";
  import * as m from "$lib/paraglide/messages.js";

  let {
    offline = false,
    darkMode = false,
    retrying = false,
    failures = 0,
    onretry,
    ondismiss,
  }: {
    /** No connection: the wording says so. */
    offline?: boolean;
    darkMode?: boolean;
    /** A retry is in flight. */
    retrying?: boolean;
    /** How many retries have failed since the page opened. */
    failures?: number;
    onretry?: () => void;
    ondismiss?: () => void;
  } = $props();

  const buttonClass = $derived(
    darkMode ? "text-ink-100 hover:bg-ink-700 hover:text-white" : "",
  );

  let box: HTMLDivElement | undefined = $state();
  let height = $state(0);

  $effect(() => {
    const root = document.documentElement;
    root.style.setProperty("--reader-notice-height", `${height}px`);
    return () => root.style.removeProperty("--reader-notice-height");
  });

  // svelte-ignore state_referenced_locally
  let felt = failures;
  $effect(() => {
    if (failures === felt) return;
    felt = failures;
    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    box?.animate(
      reduced
        ? [{ opacity: 1 }, { opacity: 0.5 }, { opacity: 1 }]
        : [0, -5, 5, -3, 3, 0].map((x) => ({
            transform: `translateX(${x}px)`,
          })),
      { duration: reduced ? 400 : 320, easing: "ease-out" },
    );
  });
</script>

<div
  class="pointer-events-none fixed inset-x-0 z-[60] flex justify-center px-4"
  style="bottom: calc(max(env(safe-area-inset-bottom, 0px), var(--reader-chrome-offset, 0px)) + 0.75rem);"
>
  <div
    bind:this={box}
    bind:offsetHeight={height}
    role="status"
    aria-live="polite"
    data-testid="reader-load-notice"
    data-failures={failures}
    class="pointer-events-auto flex max-w-full items-center gap-1 rounded-xl border py-1 pl-4 pr-1 text-sm shadow-lg {darkMode
      ? 'border-ink-700 bg-ink-800 text-ink-100'
      : 'border-border bg-card text-foreground'}"
  >
    <!-- (A new node per failed retry: the live region reads it again.) -->
    {#key failures}
      <span class="min-w-0 py-1">
        {offline ? m.reader_chapter_offline() : m.reader_chapter_load_failed()}
      </span>
    {/key}
    <Button
      variant="ghost"
      size="sm"
      class="relative text-primary disabled:opacity-100 {buttonClass}"
      disabled={retrying}
      aria-busy={retrying}
      onclick={() => onretry?.()}
    >
      <!-- The label keeps the button's width while the spinner shows. -->
      <span class={retrying ? "opacity-0" : ""}>{m.common_retry()}</span>
      {#if retrying}
        <span class="absolute inset-0 flex items-center justify-center">
          <LoaderCircle class="animate-spin" />
        </span>
      {/if}
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
