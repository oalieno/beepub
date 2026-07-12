<script lang="ts">
  import {
    ChevronLeft,
    ChevronRight,
    MousePointerClick,
    Keyboard,
    Image as ImageIcon,
    Highlighter,
    MoveHorizontal,
    Pointer,
  } from "@lucide/svelte";
  import * as m from "$lib/paraglide/messages.js";

  let {
    darkMode = false,
    isRtl = false,
    onclose,
  }: {
    darkMode?: boolean;
    isRtl?: boolean;
    onclose?: () => void;
  } = $props();

  let prevLabel = $derived(isRtl ? m.reader_next_page() : m.reader_prev_page());
  let nextLabel = $derived(isRtl ? m.reader_prev_page() : m.reader_next_page());

  // Touch devices have no mouse or arrow keys — don't teach them.
  const coarse =
    typeof window !== "undefined" &&
    window.matchMedia("(pointer: coarse)").matches;

  const tips = [
    { icon: MoveHorizontal, label: m.reader_gesture_swipe },
    ...(coarse ? [] : [{ icon: Keyboard, label: m.reader_gesture_keys }]),
    { icon: ImageIcon, label: m.reader_gesture_longpress_image },
    { icon: Highlighter, label: m.reader_gesture_tap_highlight },
  ];

  // The reader turns pages on document keyup — while the overlay is up a
  // key press must not page-turn invisibly underneath it. Swallow both
  // phases at the window (capture runs before the reader's listener) and
  // treat the release as "got it".
  function swallowKeydown(e: KeyboardEvent) {
    e.stopPropagation();
  }
  function swallowKeyup(e: KeyboardEvent) {
    e.stopPropagation();
    onclose?.();
  }
</script>

<svelte:window
  onkeydowncapture={swallowKeydown}
  onkeyupcapture={swallowKeyup}
/>

<!-- Tapping anywhere dismisses — key handling lives on the window above. -->
<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
<div
  class="absolute inset-0 z-40 flex bg-black/70 text-white select-none"
  role="dialog"
  aria-modal="true"
  aria-label={m.reader_gesture_title()}
  tabindex="-1"
  onclick={() => onclose?.()}
>
  <!-- Left tap zone -->
  <div
    class="flex w-1/5 min-w-16 flex-col items-center justify-center gap-2 border-r border-dashed border-white/25"
  >
    <ChevronLeft size={28} class="opacity-80 md:size-9" />
    <span class="text-xs md:text-base font-medium opacity-80 text-center px-1"
      >{prevLabel}</span
    >
  </div>

  <!-- Center -->
  <div class="flex flex-1 flex-col items-center justify-center gap-6 px-4">
    <div class="flex flex-col items-center gap-2 text-center">
      {#if coarse}
        <Pointer size={28} class="opacity-80 md:size-9" />
      {:else}
        <MousePointerClick size={28} class="opacity-80 md:size-9" />
      {/if}
      <span class="text-sm md:text-lg font-medium"
        >{m.reader_gesture_toggle()}</span
      >
    </div>

    <ul class="space-y-2.5 md:space-y-3">
      {#each tips as tip}
        <li class="flex items-center gap-2.5 text-xs md:text-sm opacity-80">
          <tip.icon size={14} class="shrink-0 md:size-4" />
          <span>{tip.label()}</span>
        </li>
      {/each}
    </ul>

    <button
      class="mt-2 rounded-xl bg-white px-6 py-2.5 md:px-8 md:py-3 text-sm md:text-base font-semibold text-ink-900 transition-colors hover:bg-white/90"
      onclick={() => onclose?.()}
    >
      {m.reader_gesture_got_it()}
    </button>
  </div>

  <!-- Right tap zone -->
  <div
    class="flex w-1/5 min-w-16 flex-col items-center justify-center gap-2 border-l border-dashed border-white/25"
  >
    <ChevronRight size={28} class="opacity-80 md:size-9" />
    <span class="text-xs md:text-base font-medium opacity-80 text-center px-1"
      >{nextLabel}</span
    >
  </div>
</div>
