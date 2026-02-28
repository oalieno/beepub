<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { Star } from 'lucide-svelte';

  export let value: number | null = null;
  export let readonly = false;
  export let size = 20;

  const dispatch = createEventDispatcher<{ change: number }>();

  let hovered: number | null = null;

  function setRating(star: number) {
    if (readonly) return;
    dispatch('change', star);
  }

  $: displayValue = hovered ?? value ?? 0;
</script>

<div class="flex items-center gap-0.5">
  {#each [1, 2, 3, 4, 5] as star}
    <button
      class="transition-transform {readonly ? 'cursor-default' : 'cursor-pointer hover:scale-110'}"
      on:click={() => setRating(star)}
      on:mouseenter={() => !readonly && (hovered = star)}
      on:mouseleave={() => (hovered = null)}
      disabled={readonly}
      aria-label="Rate {star} stars"
    >
      <Star
        {size}
        class="{displayValue >= star ? 'text-amber-500 fill-amber-500' : 'text-gray-600'} transition-colors"
      />
    </button>
  {/each}
  {#if value !== null}
    <span class="text-gray-400 text-sm ml-1">({value.toFixed(1)})</span>
  {/if}
</div>
