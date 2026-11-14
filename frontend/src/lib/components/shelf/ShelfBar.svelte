<script lang="ts">
  /**
   * What lies over the bookshelf: the way out, the bee's switch, and the
   * list's search.
   */
  import ArrowLeft from "@lucide/svelte/icons/arrow-left";
  import Search from "@lucide/svelte/icons/search";
  import X from "@lucide/svelte/icons/x";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import * as m from "$lib/paraglide/messages.js";
  import Bee from "./Bee.svelte";

  let {
    query = "",
    onquery,
    placeholder = "",
    bee,
    onbee,
    onback,
  }: {
    query?: string;
    onquery?: (q: string) => void;
    placeholder?: string;
    /** The bee is about. */
    bee: boolean;
    onbee: () => void;
    onback: () => void;
  } = $props();

  // Round, and dark enough to be read over the lit wood.
  const pill =
    "pointer-events-auto rounded-full dark:bg-card/80 dark:hover:bg-card backdrop-blur-sm";
</script>

<div
  class="pointer-events-none absolute top-[calc(0.875rem+env(safe-area-inset-top,0px))] right-[calc(0.875rem+env(safe-area-inset-right,0px))] left-[calc(0.875rem+env(safe-area-inset-left,0px))] flex items-center gap-2.5"
>
  <Button
    variant="outline"
    size="icon-lg"
    class={pill}
    onclick={onback}
    aria-label={m.common_back()}
    title={m.common_back()}
    data-testid="bookshelf-exit"
  >
    <ArrowLeft class="size-[18px]" />
  </Button>

  <Button
    variant="outline"
    size="icon-lg"
    class="{pill} relative ml-auto"
    onclick={onbee}
    aria-pressed={bee}
    aria-label={m.shelf_bee_toggle()}
    title={m.shelf_bee_toggle()}
    data-testid="bookshelf-bee-toggle"
  >
    <span
      class="w-6 transition-[opacity,filter] {bee
        ? ''
        : 'opacity-40 grayscale'}"
    >
      <Bee beat="still" />
    </span>
    {#if !bee}
      <!-- Off: struck through. -->
      <span
        class="absolute h-0.5 w-6 -rotate-45 rounded-full bg-foreground"
        aria-hidden="true"
      ></span>
    {/if}
  </Button>

  <div class="pointer-events-auto relative w-70 max-w-full min-w-0 shrink">
    <Search
      class="pointer-events-none absolute top-1/2 left-3.5 size-[15px] -translate-y-1/2 text-muted-foreground"
    />
    <Input
      type="text"
      value={query}
      oninput={(e) => onquery?.(e.currentTarget.value)}
      {placeholder}
      aria-label={placeholder}
      class="h-10 rounded-full px-9 backdrop-blur-sm dark:bg-card/80"
    />
    {#if query}
      <button
        type="button"
        class="absolute top-1/2 right-3.5 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        aria-label={m.common_clear()}
        onclick={() => onquery?.("")}
      >
        <X class="size-3.5" />
      </button>
    {/if}
  </div>
</div>
