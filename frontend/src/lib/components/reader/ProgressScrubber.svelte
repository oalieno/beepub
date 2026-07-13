<script lang="ts">
  let {
    percentage = 0,
    darkMode = false,
    isRtl = false,
    ariaLabel = "",
    onseek,
    getlabel,
  }: {
    percentage?: number;
    darkMode?: boolean;
    isRtl?: boolean;
    ariaLabel?: string;
    onseek?: (percentage: number) => void;
    /** Chapter (or other context) for the drag bubble at a target position. */
    getlabel?: (percentage: number) => string | null;
  } = $props();

  // Local preview while dragging so the thumb tracks the pointer instead of
  // snapping back to the (async-updating) real progress.
  let preview = $state<number | null>(null);
  let value = $derived(preview ?? Math.round(percentage));

  let fill = $derived(darkMode ? "#9a8f7e" : "var(--color-primary)");
  let track = $derived(darkMode ? "#2c2620" : "var(--color-secondary)");
  let gradientDir = $derived(isRtl ? "to left" : "to right");

  let bubbleLabel = $derived(preview != null ? getlabel?.(preview) : null);
  // Center of the bubble follows the thumb; clamped so it never bleeds past
  // the slider ends. An RTL slider fills right-to-left, so mirror the offset.
  let bubblePos = $derived(isRtl ? 100 - (preview ?? 0) : (preview ?? 0));
</script>

<div class="relative">
  {#if preview != null}
    <div
      class="absolute bottom-full mb-2 flex flex-col items-center pointer-events-none -translate-x-1/2 max-w-[70%]"
      style="left: clamp(2.5rem, {bubblePos}%, calc(100% - 2.5rem));"
    >
      <div
        class="px-2.5 py-1 rounded-lg text-xs shadow-lg border flex items-center gap-1.5 whitespace-nowrap max-w-full {darkMode
          ? 'bg-ink-800 border-ink-700 text-ink-100'
          : 'bg-card border-border text-foreground'}"
      >
        <span class="font-semibold tabular-nums">{preview}%</span>
        {#if bubbleLabel}
          <span
            class="truncate {darkMode
              ? 'text-ink-400'
              : 'text-muted-foreground'}">{bubbleLabel}</span
          >
        {/if}
      </div>
    </div>
  {/if}
  <input
    type="range"
    min="0"
    max="100"
    step="1"
    {value}
    dir={isRtl ? "rtl" : "ltr"}
    aria-label={ariaLabel}
    class="reader-scrubber w-full"
    style="--scrub-track: linear-gradient({gradientDir}, {fill} {value}%, {track} {value}%); --scrub-thumb: {fill};"
    oninput={(e) => (preview = +e.currentTarget.value)}
    onchange={(e) => {
      onseek?.(+e.currentTarget.value);
      preview = null;
    }}
  />
</div>

<style>
  .reader-scrubber {
    -webkit-appearance: none;
    appearance: none;
    /* An input is inline by default and sits on the text baseline, which
       adds phantom space below and knocks the bar off vertical center. */
    display: block;
    height: 20px;
    background: transparent;
    cursor: pointer;
  }
  .reader-scrubber::-webkit-slider-runnable-track {
    height: 4px;
    border-radius: 9999px;
    background: var(--scrub-track);
  }
  .reader-scrubber::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 14px;
    height: 14px;
    margin-top: -5px;
    border-radius: 50%;
    background: var(--scrub-thumb);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
  }
  .reader-scrubber::-moz-range-track {
    height: 4px;
    border-radius: 9999px;
    background: var(--scrub-track);
  }
  .reader-scrubber::-moz-range-thumb {
    width: 14px;
    height: 14px;
    border: none;
    border-radius: 50%;
    background: var(--scrub-thumb);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
  }

  /* Touch devices get a bigger thumb and a taller hit area — a 14px dot
     under a fingertip is a miss half the time. */
  @media (pointer: coarse) {
    .reader-scrubber {
      height: 28px;
    }
    .reader-scrubber::-webkit-slider-thumb {
      width: 20px;
      height: 20px;
      margin-top: -8px;
    }
    .reader-scrubber::-moz-range-thumb {
      width: 20px;
      height: 20px;
    }
  }
</style>
