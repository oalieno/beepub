<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import { bookshelvesApi } from '$lib/api/bookshelves';
  import { toastStore } from '$lib/stores/toast';
  import Modal from '$lib/components/Modal.svelte';
  import type { BookshelfOut } from '$lib/types';
  import { Plus, BookMarked, Trash2 } from 'lucide-svelte';

  let shelves: BookshelfOut[] = [];
  let loading = true;
  let showCreateModal = false;
  let createForm = { name: '', description: '', is_public: false };
  let creating = false;

  onMount(async () => {
    if (!$authStore.token) { goto('/login'); return; }
    await loadData();
  });

  async function loadData() {
    loading = true;
    try {
      shelves = await bookshelvesApi.list($authStore.token!);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleCreate() {
    if (!createForm.name || !$authStore.token) return;
    creating = true;
    try {
      const shelf = await bookshelvesApi.create(createForm, $authStore.token);
      shelves = [...shelves, shelf];
      showCreateModal = false;
      createForm = { name: '', description: '', is_public: false };
      toastStore.success('Bookshelf created');
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      creating = false;
    }
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`Delete "${name}"?`) || !$authStore.token) return;
    try {
      await bookshelvesApi.delete(id, $authStore.token);
      shelves = shelves.filter(s => s.id !== id);
      toastStore.success('Bookshelf deleted');
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>My Bookshelves - BeePub</title>
</svelte:head>

<div class="max-w-4xl mx-auto px-4 py-8">
  <div class="flex items-center justify-between mb-8">
    <h1 class="text-3xl font-bold">My Bookshelves</h1>
    <button
      class="flex items-center gap-2 bg-amber-500 hover:bg-amber-600 text-gray-900 font-semibold px-4 py-2 rounded-lg"
      on:click={() => (showCreateModal = true)}
    >
      <Plus size={16} />
      New Shelf
    </button>
  </div>

  {#if loading}
    <div class="flex items-center justify-center h-40">
      <div class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-amber-500"></div>
    </div>
  {:else if shelves.length === 0}
    <div class="text-center py-16 text-gray-500">
      <BookMarked class="mx-auto mb-3" size={40} />
      <p>No bookshelves yet. Create one to organize your reading.</p>
    </div>
  {:else}
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {#each shelves as shelf}
        <div class="bg-gray-800 rounded-xl p-5 flex items-start justify-between group">
          <a href="/bookshelves/{shelf.id}" class="flex-1 min-w-0">
            <h2 class="font-semibold text-lg hover:text-amber-500 transition-colors truncate">{shelf.name}</h2>
            {#if shelf.description}
              <p class="text-gray-400 text-sm mt-1 line-clamp-2">{shelf.description}</p>
            {/if}
            <div class="flex items-center gap-2 mt-2">
              <span class="text-xs px-2 py-0.5 rounded {shelf.is_public ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-400'}">
                {shelf.is_public ? 'Public' : 'Private'}
              </span>
            </div>
          </a>
          <button
            class="ml-3 p-1.5 text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
            on:click={() => handleDelete(shelf.id, shelf.name)}
          >
            <Trash2 size={16} />
          </button>
        </div>
      {/each}
    </div>
  {/if}
</div>

<Modal title="Create Bookshelf" open={showCreateModal} on:close={() => (showCreateModal = false)}>
  <div class="space-y-4">
    <div>
      <label class="block text-sm font-medium text-gray-300 mb-1">Name</label>
      <input
        bind:value={createForm.name}
        placeholder="e.g. To Read, Sci-Fi Favorites"
        class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-500"
      />
    </div>
    <div>
      <label class="block text-sm font-medium text-gray-300 mb-1">Description (optional)</label>
      <input
        bind:value={createForm.description}
        placeholder="A description..."
        class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-500"
      />
    </div>
    <label class="flex items-center gap-2 cursor-pointer">
      <input type="checkbox" bind:checked={createForm.is_public} class="accent-amber-500" />
      <span class="text-sm text-gray-300">Make public</span>
    </label>
    <div class="flex justify-end gap-2 pt-2">
      <button class="px-4 py-2 text-sm text-gray-400 hover:text-white" on:click={() => (showCreateModal = false)}>Cancel</button>
      <button
        disabled={!createForm.name || creating}
        class="px-4 py-2 text-sm bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-gray-900 font-semibold rounded-lg"
        on:click={handleCreate}
      >
        {creating ? 'Creating...' : 'Create'}
      </button>
    </div>
  </div>
</Modal>
