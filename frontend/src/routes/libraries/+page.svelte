<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { librariesApi } from "$lib/api/libraries";
  import { toastStore } from "$lib/stores/toast";
  import type { LibraryOut } from "$lib/types";
  import { LibraryVisibility } from "$lib/types";
  import { Library, HardDrive } from "@lucide/svelte";
  import CollectionCard from "$lib/components/CollectionCard.svelte";
  import Spinner from "$lib/components/Spinner.svelte";

  let libraries = $state<LibraryOut[]>([]);
  let loading = $state(true);

  onMount(async () => {
    if (!$authStore.token) {
      goto("/login");
      return;
    }
    try {
      libraries = await librariesApi.list($authStore.token);
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

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
  <div class="mb-8">
    <h1 class="text-3xl font-bold text-foreground">Libraries</h1>
    <p class="text-muted-foreground mt-1">
      Browse your available book collections
    </p>
  </div>

  {#if loading}
    <div class="flex items-center justify-center h-40">
      <Spinner size="lg" />
    </div>
  {:else if libraries.length === 0}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      <Library class="mx-auto mb-4 text-muted-foreground/30" size={48} />
      <p class="text-muted-foreground text-lg">No libraries available</p>
    </div>
  {:else}
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-5">
      {#each libraries as lib}
        <CollectionCard
          href="/libraries/{lib.id}"
          name={lib.name}
          previewBookIds={lib.preview_book_ids}
          bookCount={lib.book_count}
          badgeLabel={lib.visibility === LibraryVisibility.Private
            ? "Private"
            : "Public"}
          badgeClass={lib.visibility === LibraryVisibility.Private
            ? "bg-secondary text-muted-foreground"
            : "bg-primary/15 text-primary"}
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
