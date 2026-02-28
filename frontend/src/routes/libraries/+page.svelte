<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import { librariesApi } from '$lib/api/libraries';
  import { toastStore } from '$lib/stores/toast';
  import type { LibraryOut } from '$lib/types';
  import { LibraryVisibility } from '$lib/types';
  import { Library, Lock, Globe, ChevronRight } from 'lucide-svelte';

  let libraries: LibraryOut[] = [];
  let loading = true;

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

<div class="max-w-4xl mx-auto px-4 py-8">
  <h1 class="text-3xl font-bold mb-8">Libraries</h1>

  {#if loading}
    <div class="flex items-center justify-center h-40">
      <div class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-amber-500"></div>
    </div>
  {:else if libraries.length === 0}
    <div class="text-center py-16 text-gray-500">
      <Library class="mx-auto mb-3" size={40} />
      <p>No libraries available.</p>
    </div>
  {:else}
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {#each libraries as lib}
        <a
          href="/libraries/{lib.id}"
          class="bg-gray-800 rounded-xl p-5 flex items-start justify-between hover:bg-gray-750 hover:ring-2 hover:ring-amber-500 transition-all group"
        >
          <div class="flex items-start gap-3 min-w-0">
            {#if lib.visibility === LibraryVisibility.Private}
              <Lock class="text-red-400 flex-shrink-0 mt-0.5" size={18} />
            {:else}
              <Globe class="text-green-400 flex-shrink-0 mt-0.5" size={18} />
            {/if}
            <div class="min-w-0">
              <h2 class="font-semibold text-lg truncate">{lib.name}</h2>
              {#if lib.description}
                <p class="text-gray-400 text-sm mt-1 line-clamp-2">{lib.description}</p>
              {/if}
            </div>
          </div>
          <ChevronRight class="text-gray-500 group-hover:text-amber-500 flex-shrink-0 ml-2 mt-1 transition-colors" size={18} />
        </a>
      {/each}
    </div>
  {/if}
</div>
