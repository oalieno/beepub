<script lang="ts">
  import { Star } from "@lucide/svelte";

  let {
    value = null,
    readonly = false,
    size = 20,
    onchange,
  }: {
    value?: number | null;
    readonly?: boolean;
    size?: number;
    onchange?: (rating: number) => void;
  } = $props();

  let hovered = $state<number | null>(null);

  function setRating(star: number) {
    if (readonly) return;
    onchange?.(star);
  }

  let displayValue = $derived(hovered ?? value ?? 0);
</script>

<div class="flex items-center gap-0.5">
  {#each [1, 2, 3, 4, 5] as star}
    <button
      class="transition-transform {readonly
        ? 'cursor-default'
        : 'cursor-pointer hover:scale-110'}"
      onclick={() => setRating(star)}
      onmouseenter={() => !readonly && (hovered = star)}
      onmouseleave={() => (hovered = null)}
      disabled={readonly}
      aria-label="Rate {star} stars"
    >
      <Star
        {size}
        class="{displayValue >= star
          ? 'text-primary fill-primary'
          : 'text-muted-foreground/30'} transition-colors"
      />
    </button>
  {/each}
  {#if value !== null}
    <span class="text-muted-foreground text-sm ml-1">({value.toFixed(1)})</span>
  {/if}
</div>
