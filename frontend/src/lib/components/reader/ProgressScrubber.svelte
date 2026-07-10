<script lang="ts">
  let {
    percentage = 0,
    darkMode = false,
    isRtl = false,
    ariaLabel = "",
    onseek,
  }: {
    percentage?: number;
    darkMode?: boolean;
    isRtl?: boolean;
    ariaLabel?: string;
    onseek?: (percentage: number) => void;
  } = $props();

  // Local preview while dragging so the thumb tracks the pointer instead of
  // snapping back to the (async-updating) real progress.
  let preview = $state<number | null>(null);
  let value = $derived(preview ?? Math.round(percentage));

  let fill = $derived(darkMode ? "#9a8f7e" : "var(--color-primary)");
  let track = $derived(darkMode ? "#2c2620" : "var(--color-secondary)");
  let gradientDir = $derived(isRtl ? "to left" : "to right");
</script>

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
</style>
