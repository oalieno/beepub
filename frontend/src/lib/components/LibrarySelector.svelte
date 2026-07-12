<script lang="ts">
  import { goto } from "$app/navigation";
  import { HardDrive } from "@lucide/svelte";
  import type { LibraryOut } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";

  // "all" is the special pseudo-library spanning every accessible library.
  // Text-only segmented control: libraries are user-named, so no icons —
  // except the device tab, whose icon marks it as the odd one out (it
  // navigates to the local library instead of filtering this page).
  let {
    libraries,
    selected,
    onSelect,
    showDevice = false,
  }: {
    libraries: LibraryOut[];
    selected: string;
    onSelect: (lib: string) => void;
    showDevice?: boolean;
  } = $props();

  // Matches the reading-status tabs on /my-books: flat pills, active filled.
  function segClass(active: boolean) {
    return active
      ? "bg-primary text-primary-foreground"
      : "text-muted-foreground hover:text-foreground hover:bg-muted";
  }
</script>

<div class="flex gap-1 overflow-x-auto scrollbar-thin pb-1">
  <!-- All books pseudo-library -->
  <button
    type="button"
    onclick={() => onSelect("all")}
    aria-pressed={selected === "all"}
    class="shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors {segClass(
      selected === 'all',
    )}"
  >
    {m.allbooks_heading()}
  </button>

  <!-- The local library, kept beside "all books" so it never scrolls out
       of sight behind a long library list -->
  {#if showDevice}
    <button
      type="button"
      onclick={() => goto("/local")}
      class="shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors inline-flex items-center gap-1.5 {segClass(
        false,
      )}"
    >
      <HardDrive size={14} />
      {m.libraries_this_device()}
    </button>
  {/if}

  {#if libraries.length > 0}
    <span class="mx-1 h-6 w-px shrink-0 self-center bg-border"></span>
  {/if}

  {#each libraries as lib (lib.id)}
    {@const active = selected === lib.id}
    <button
      type="button"
      onclick={() => onSelect(lib.id)}
      aria-pressed={active}
      class="shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors {segClass(
        active,
      )}"
    >
      {lib.name}
    </button>
  {/each}
</div>
