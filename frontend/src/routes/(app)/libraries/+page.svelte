<script lang="ts">
  import { onMount } from "svelte";
  import { librariesApi } from "$lib/api/libraries";
  import { toastStore } from "$lib/stores/toast";
  import type { LibraryOut } from "$lib/types";
  import { Library, HardDrive } from "@lucide/svelte";
  import CollectionCard from "$lib/components/CollectionCard.svelte";
  import { CardListSkeleton } from "$lib/components/skeletons";

  let libraries = $state<LibraryOut[]>([]);
  let loading = $state(true);

  onMount(async () => {
    try {
      libraries = await librariesApi.list();
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  });
</script>

<svelte:head>
  <title>Libraries - BeePub</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6">
  {#if loading}
    <CardListSkeleton count={4} />
  {:else if libraries.length === 0}
    <div class="flex flex-col items-center justify-center py-24 text-center">
      <div class="mb-4 p-3 bg-primary/10 rounded-xl">
        <Library class="text-primary/50" size={28} />
      </div>
      <p class="text-foreground text-lg font-medium mb-2">
        No libraries available
      </p>
      <p class="text-muted-foreground text-sm max-w-xs">
        Libraries will appear here once they are created by an admin.
      </p>
    </div>
  {:else}
    <div class="grid grid-cols-1 gap-5 collection-grid">
      {#each libraries as lib}
        <CollectionCard
          href="/libraries/{lib.id}"
          name={lib.name}
          previewBookIds={lib.preview_book_ids}
          bookCount={lib.book_count}
          badgeLabel={lib.calibre_path ? "Calibre" : ""}
          badgeClass="bg-primary/15 text-primary"
        >
          {#snippet icon()}
            {#if lib.calibre_path}
              <HardDrive class="text-amber-500/70 shrink-0" size={16} />
            {:else}
              <Library class="text-muted-foreground/50 shrink-0" size={16} />
            {/if}
          {/snippet}
        </CollectionCard>
      {/each}
    </div>
  {/if}
</div>

<style>
  @media (min-width: 640px) {
    .collection-grid {
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    }
  }
</style>
