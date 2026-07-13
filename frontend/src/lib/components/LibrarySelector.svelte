<script lang="ts">
  import { goto } from "$app/navigation";
  import { Cloud, HardDrive } from "@lucide/svelte";
  import type { LibraryOut } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";

  // "all" is the special pseudo-library spanning every accessible library.
  // Text-only segmented control: libraries are user-named, so no icons.
  // On native the device tab sits beside it, so the pair reads as
  // cloud vs. device — 雲端書籍 with a cloud icon there; the web has no
  // device tab and keeps plain 所有書籍.
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
    class="shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors inline-flex items-center gap-1.5 {segClass(
      selected === 'all',
    )}"
  >
    {#if showDevice}
      <Cloud size={14} />
      {m.libraries_cloud_books()}
    {:else}
      {m.allbooks_heading()}
    {/if}
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
