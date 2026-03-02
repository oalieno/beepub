<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import { bookshelvesApi } from '$lib/api/bookshelves';
  import { toastStore } from '$lib/stores/toast';
  import Modal from '$lib/components/Modal.svelte';
  import type { BookshelfOut } from '$lib/types';
  import { Plus, BookMarked, Trash2 } from '@lucide/svelte';

  let bookshelves = $state<BookshelfOut[]>([]);
  let loading = $state(true);
  let showCreateModal = $state(false);
  let createName = $state('');
  let createDesc = $state('');
  let creating = $state(false);
  let isPublic = $state(false);

  onMount(async () => {
    if (!$authStore.token) { goto('/login'); return; }
    await loadData();
  });

  async function loadData() {
    loading = true;
    try {
      bookshelves = await bookshelvesApi.list($authStore.token!);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleCreate() {
    if (!createName || !$authStore.token) return;
    creating = true;
    try {
      const shelf = await bookshelvesApi.create({ name: createName, description: createDesc, is_public: isPublic }, $authStore.token);
      bookshelves = [...bookshelves, shelf];
      showCreateModal = false;
      createName = '';
      createDesc = '';
      isPublic = false;
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
      bookshelves = bookshelves.filter(s => s.id !== id);
      toastStore.success('Bookshelf deleted');
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>My Bookshelves - BeePub</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
  <div class="flex items-end justify-between mb-8">
    <div>
      <h1 class="text-3xl font-bold text-foreground">My Shelves</h1>
      <p class="text-muted-foreground mt-1">Organize your reading collections</p>
    </div>
    <button
      class="flex items-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-medium px-5 py-2.5 rounded-xl transition-colors"
      onclick={() => (showCreateModal = true)}
    >
      <Plus size={16} />
      New Shelf
    </button>
  </div>

  {#if loading}
    <div class="flex items-center justify-center h-40">
      <div class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-primary"></div>
    </div>
  {:else if bookshelves.length === 0}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      <BookMarked class="mx-auto mb-4 text-muted-foreground/30" size={48} />
      <p class="text-muted-foreground text-lg">No shelves yet</p>
      <p class="text-muted-foreground/70 text-sm mt-1">Create one to organize your reading.</p>
    </div>
  {:else}
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {#each bookshelves as shelf}
        <div class="bg-card card-soft rounded-2xl p-5 flex items-start justify-between group hover:shadow-md transition-all duration-200">
          <a href="/bookshelves/{shelf.id}" class="flex-1 min-w-0">
            <h2 class="font-semibold text-lg text-foreground group-hover:text-primary transition-colors truncate">{shelf.name}</h2>
            {#if shelf.description}
              <p class="text-muted-foreground text-sm mt-1 line-clamp-2">{shelf.description}</p>
            {/if}
            <div class="flex items-center gap-2 mt-2.5">
              <span class="text-xs px-2.5 py-1 rounded-full font-medium {shelf.is_public ? 'bg-emerald-100 text-emerald-700' : 'bg-secondary text-muted-foreground'}">
                {shelf.is_public ? 'Public' : 'Private'}
              </span>
            </div>
          </a>
          <button
            class="ml-3 w-7 h-7 rounded-full bg-secondary/50 flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 opacity-0 group-hover:opacity-100 transition-all"
            onclick={() => handleDelete(shelf.id, shelf.name)}
          >
            <Trash2 size={13} />
          </button>
        </div>
      {/each}
    </div>
  {/if}
</div>

<Modal title="Create Bookshelf" open={showCreateModal} onclose={() => (showCreateModal = false)}>
  <div class="space-y-4">
    <div class="space-y-1">
      <label class="block text-sm font-medium text-foreground" for="shelf-name">Name</label>
      <input
        id="shelf-name"
        bind:value={createName}
        placeholder="e.g. To Read, Sci-Fi Favorites"
        class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
    </div>
    <div class="space-y-1">
      <label class="block text-sm font-medium text-foreground" for="shelf-desc">Description (optional)</label>
      <input
        id="shelf-desc"
        bind:value={createDesc}
        placeholder="A description..."
        class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
    </div>
    <label class="flex items-center gap-2 cursor-pointer">
      <input type="checkbox" bind:checked={isPublic} class="accent-primary" />
      <span class="text-sm text-foreground">Make public</span>
    </label>
    <div class="flex justify-end gap-2 pt-2">
      <button class="px-4 py-2 text-sm text-muted-foreground hover:text-foreground" onclick={() => (showCreateModal = false)}>Cancel</button>
      <button
        disabled={!createName || creating}
        class="px-5 py-2.5 text-sm bg-primary hover:bg-primary/90 disabled:opacity-50 text-primary-foreground font-semibold rounded-xl"
        onclick={handleCreate}
      >
        {creating ? 'Creating...' : 'Create'}
      </button>
    </div>
  </div>
</Modal>
