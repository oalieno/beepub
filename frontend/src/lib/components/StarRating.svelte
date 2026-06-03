<script lang="ts">
  import { Star, X } from "@lucide/svelte";

  let {
    value = null,
    readonly = false,
    size = 20,
    onchange,
  }: {
    value?: number | null;
    readonly?: boolean;
    size?: number;
    onchange?: (rating: number | null) => void;
  } = $props();

  let hovered = $state<number | null>(null);

  let displayValue = $derived(hovered ?? value ?? 0);

  // How much of a given star (1-5) is filled: 0, 0.5, or 1.
  function fillFraction(star: number): number {
    const diff = displayValue - (star - 1);
    if (diff >= 1) return 1;
    if (diff >= 0.5) return 0.5;
    return 0;
  }

  function rate(amount: number) {
    if (readonly) return;
    // Clicking the current value again clears the rating (sets it to null).
    onchange?.(value === amount ? null : amount);
  }
</script>

<div class="flex items-center gap-0.5">
  {#each [1, 2, 3, 4, 5] as star}
    {@const fill = fillFraction(star)}
    <div
      class="relative {readonly ? '' : 'transition-transform hover:scale-110'}"
      style="width: {size}px; height: {size}px;"
    >
      <Star {size} class="text-muted-foreground/30 absolute inset-0" />
      {#if fill > 0}
        <div
          class="absolute inset-0 overflow-hidden"
          style="width: {fill * 100}%;"
        >
          <Star {size} class="text-primary fill-primary" />
        </div>
      {/if}
      {#if !readonly}
        <button
          type="button"
          class="absolute inset-y-0 left-0 w-1/2 cursor-pointer"
          aria-label="Rate {star - 0.5} stars"
          onclick={() => rate(star - 0.5)}
          onmouseenter={() => (hovered = star - 0.5)}
          onmouseleave={() => (hovered = null)}
        ></button>
        <button
          type="button"
          class="absolute inset-y-0 right-0 w-1/2 cursor-pointer"
          aria-label="Rate {star} stars"
          onclick={() => rate(star)}
          onmouseenter={() => (hovered = star)}
          onmouseleave={() => (hovered = null)}
        ></button>
      {/if}
    </div>
  {/each}
  {#if value !== null}
    <span class="text-muted-foreground text-sm ml-1">({value.toFixed(1)})</span>
    {#if !readonly}
      <button
        type="button"
        class="text-muted-foreground/60 hover:text-foreground ml-0.5 cursor-pointer transition-colors"
        aria-label="Clear rating"
        title="Clear rating"
        onclick={() => onchange?.(null)}
      >
        <X size={14} />
      </button>
    {/if}
  {/if}
</div>
