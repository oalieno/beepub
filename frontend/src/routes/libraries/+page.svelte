<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import { librariesApi } from '$lib/api/libraries';
  import { toastStore } from '$lib/stores/toast';
  import type { LibraryOut } from '$lib/types';
  import { LibraryVisibility } from '$lib/types';
  import { Library, ChevronRight } from '@lucide/svelte';

  let libraries = $state<LibraryOut[]>([]);
  let loading = $state(true);

  onMount(async () => {
    if (!$authStore.token) { goto('/login'); return; }
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
    <p class="text-muted-foreground mt-1">Browse your available book collections</p>
  </div>

  {#if loading}
    <div class="flex items-center justify-center h-40">
      <div class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-primary"></div>
    </div>
  {:else if libraries.length === 0}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      <Library class="mx-auto mb-4 text-muted-foreground/30" size={48} />
      <p class="text-muted-foreground text-lg">No libraries available</p>
    </div>
  {:else}
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {#each libraries as lib}
        <a
          href="/libraries/{lib.id}"
          class="bg-card card-soft rounded-2xl p-5 hover:shadow-md transition-all duration-200 group flex flex-col"
        >
          <div class="flex items-center justify-between mb-3">
            <span class="text-xs px-2.5 py-1 rounded-full font-medium {lib.visibility === LibraryVisibility.Private ? 'bg-orange-100 text-orange-600' : 'bg-emerald-100 text-emerald-600'}">
              {lib.visibility === LibraryVisibility.Private ? 'Private' : 'Public'}
            </span>
            <ChevronRight class="text-muted-foreground/30 group-hover:text-primary transition-colors" size={16} />
          </div>
          <h2 class="font-bold text-lg text-foreground group-hover:text-primary transition-colors leading-tight">{lib.name}</h2>
          {#if lib.description}
            <p class="text-muted-foreground text-sm mt-1.5 line-clamp-2">{lib.description}</p>
          {/if}
        </a>
      {/each}
    </div>
  {/if}
</div>
