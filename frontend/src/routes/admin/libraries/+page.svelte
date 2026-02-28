<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import { librariesApi } from '$lib/api/libraries';
  import { toastStore } from '$lib/stores/toast';
  import Modal from '$lib/components/Modal.svelte';
  import type { LibraryOut } from '$lib/types';
  import { UserRole, LibraryVisibility } from '$lib/types';
  import { Plus, Trash2, Lock, Globe, Settings } from 'lucide-svelte';

  let libraries: LibraryOut[] = [];
  let loading = true;
  let showCreateModal = false;
  let createForm = { name: '', description: '', visibility: LibraryVisibility.Public };
  let creating = false;

  onMount(async () => {
    if (!$authStore.user || $authStore.user.role !== UserRole.Admin) {
      goto('/');
      return;
    }
    await loadData();
  });

  async function loadData() {
    loading = true;
    try {
      libraries = await librariesApi.list($authStore.token!);
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
      const lib = await librariesApi.create(createForm, $authStore.token);
      libraries = [...libraries, lib];
      showCreateModal = false;
      createForm = { name: '', description: '', visibility: LibraryVisibility.Public };
      toastStore.success('Library created');
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      creating = false;
    }
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`Delete library "${name}"?`) || !$authStore.token) return;
    try {
      await librariesApi.delete(id, $authStore.token);
      libraries = libraries.filter(l => l.id !== id);
      toastStore.success('Library deleted');
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>Libraries - Admin - BeePub</title>
</svelte:head>

<div class="max-w-4xl mx-auto px-4 py-8">
  <div class="flex items-center justify-between mb-8">
    <div class="flex items-center gap-3">
      <a href="/admin" class="text-gray-400 hover:text-white text-sm">← Admin</a>
      <h1 class="text-3xl font-bold">Libraries</h1>
    </div>
    <button
      class="flex items-center gap-2 bg-amber-500 hover:bg-amber-600 text-gray-900 font-semibold px-4 py-2 rounded-lg"
      on:click={() => (showCreateModal = true)}
    >
      <Plus size={16} />
      New Library
    </button>
  </div>

  {#if loading}
    <div class="flex items-center justify-center h-40">
      <div class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-amber-500"></div>
    </div>
  {:else if libraries.length === 0}
    <div class="text-center py-16 text-gray-500">
      <p>No libraries yet. Create one to get started.</p>
    </div>
  {:else}
    <div class="space-y-3">
      {#each libraries as lib}
        <div class="bg-gray-800 rounded-xl p-4 flex items-center justify-between">
          <div class="flex items-center gap-3">
            {#if lib.visibility === LibraryVisibility.Private}
              <Lock class="text-red-400 flex-shrink-0" size={18} />
            {:else}
              <Globe class="text-green-400 flex-shrink-0" size={18} />
            {/if}
            <div>
              <p class="font-semibold">{lib.name}</p>
              {#if lib.description}
                <p class="text-gray-400 text-sm">{lib.description}</p>
              {/if}
            </div>
          </div>
          <div class="flex items-center gap-2">
            <a
              href="/admin/libraries/{lib.id}"
              class="p-2 text-gray-400 hover:text-white"
              title="Manage"
            >
              <Settings size={16} />
            </a>
            <button
              class="p-2 text-gray-400 hover:text-red-400"
              on:click={() => handleDelete(lib.id, lib.name)}
              title="Delete"
            >
              <Trash2 size={16} />
            </button>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

<Modal title="Create Library" open={showCreateModal} on:close={() => (showCreateModal = false)}>
  <div class="space-y-4">
    <div>
      <label class="block text-sm font-medium text-gray-300 mb-1">Name</label>
      <input bind:value={createForm.name} class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-500" />
    </div>
    <div>
      <label class="block text-sm font-medium text-gray-300 mb-1">Description</label>
      <input bind:value={createForm.description} class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-500" />
    </div>
    <div>
      <label class="block text-sm font-medium text-gray-300 mb-1">Visibility</label>
      <select bind:value={createForm.visibility} class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-500">
        <option value={LibraryVisibility.Public}>Public</option>
        <option value={LibraryVisibility.Private}>Private (whitelist)</option>
      </select>
    </div>
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
