<script lang="ts">
  /**
   * Home in local mode: the same page as the server's, minus what needs a
   * server — continue reading and the books added most recently, both
   * from the device shelf.
   */
  import { onMount } from "svelte";
  import { HardDrive, Plus } from "@lucide/svelte";
  import ContinueReadingRow from "$lib/components/ContinueReadingRow.svelte";
  import LocalBookCard, {
    type LocalShelfEntry,
  } from "$lib/components/LocalBookCard.svelte";
  import { HomeSkeleton } from "$lib/components/skeletons";
  import { continueItems, loadShelfEntries } from "$lib/services/localShelf";
  import * as m from "$lib/paraglide/messages.js";

  let entries = $state<LocalShelfEntry[]>([]);
  let loading = $state(true);

  let continueReading = $derived(continueItems(entries).slice(0, 12));
  let recent = $derived(
    [...entries]
      .sort((a, b) => b.importedAt.localeCompare(a.importedAt))
      .slice(0, 12),
  );

  onMount(async () => {
    try {
      entries = await loadShelfEntries();
    } finally {
      loading = false;
    }
  });
</script>

<div class="max-w-6xl mx-auto px-6 sm:px-8 py-6">
  {#if loading}
    <HomeSkeleton />
  {:else if entries.length === 0}
    <div class="flex flex-col items-center justify-center py-24 text-center">
      <div class="mb-4 p-3 bg-primary/10 rounded-xl">
        <HardDrive class="text-primary/50" size={28} />
      </div>
      <p class="text-foreground text-lg font-medium mb-2">
        {m.local_empty()}
      </p>
      <p class="text-muted-foreground text-sm max-w-xs mb-6">
        {m.local_empty_subtitle()}
      </p>
      <a
        href="/local"
        class="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
      >
        <Plus size={16} />
        {m.local_add()}
      </a>
    </div>
  {:else}
    {#if continueReading.length > 0}
      <ContinueReadingRow items={continueReading} />
    {/if}

    <section class="mb-12">
      <div class="flex items-end justify-between mb-6">
        <div>
          <h2 class="text-2xl font-bold text-foreground">
            {m.home_recently_added()}
          </h2>
          <p class="text-muted-foreground text-sm mt-1">
            {m.home_recently_added_subtitle()}
          </p>
        </div>
        <a
          href="/local"
          class="text-primary hover:text-primary/80 text-sm font-medium"
          >{m.home_browse_all()}</a
        >
      </div>
      <div
        class="grid gap-4 items-start book-grid"
        style="grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));"
      >
        {#each recent as entry (entry.id)}
          <LocalBookCard {entry} />
        {/each}
      </div>
    </section>
  {/if}
</div>
