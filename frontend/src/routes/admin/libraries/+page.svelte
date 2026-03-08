<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import { librariesApi } from '$lib/api/libraries';
  import { toastStore } from '$lib/stores/toast';
  import Modal from '$lib/components/Modal.svelte';
  import type { LibraryOut } from '$lib/types';
  import { UserRole, LibraryVisibility } from '$lib/types';
  import { Plus, Trash2, Lock, Globe, Settings } from '@lucide/svelte';

  let libraries = $state<LibraryOut[]>([]);
  let loading = $state(true);
  let showCreateModal = $state(false);
  let createForm = $state({ name: '', description: '', visibility: LibraryVisibility.Public as string });
  let creating = $state(false);

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

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
  <div class="flex items-end justify-between mb-8">
    <div>
      <a href="/admin" class="text-muted-foreground hover:text-foreground text-sm mb-1 inline-block">← Admin</a>
      <h1 class="text-3xl font-bold text-foreground">Libraries</h1>
      <p class="text-muted-foreground mt-1">Manage libraries, visibility, and access</p>
    </div>
    <button
      class="flex items-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-medium px-5 py-2.5 rounded-xl transition-colors"
      onclick={() => (showCreateModal = true)}
    >
      <Plus size={16} />
      New Library
    </button>
  </div>

  {#if loading}
    <div class="flex items-center justify-center h-40">
      <div class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-primary"></div>
    </div>
  {:else if libraries.length === 0}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      <p class="text-muted-foreground text-lg">No libraries yet</p>
      <p class="text-muted-foreground/70 text-sm mt-1">Create one to get started.</p>
    </div>
  {:else}
    <div class="space-y-3">
      {#each libraries as lib}
        <div class="bg-card card-soft rounded-2xl p-5 flex items-center justify-between group hover:shadow-md transition-all duration-200">
          <div class="flex items-center gap-3.5">
            <div class="w-10 h-10 rounded-xl flex-shrink-0 flex items-center justify-center {lib.visibility === LibraryVisibility.Private ? 'bg-secondary text-muted-foreground' : 'bg-primary/15 text-primary'}">
              {#if lib.visibility === LibraryVisibility.Private}
                <Lock size={18} />
              {:else}
                <Globe size={18} />
              {/if}
            </div>
            <div>
              <p class="font-semibold text-foreground">{lib.name}</p>
              {#if lib.description}
                <p class="text-muted-foreground text-sm">{lib.description}</p>
              {/if}
            </div>
          </div>
          <div class="flex items-center gap-1.5">
            <a
              href="/admin/libraries/{lib.id}"
              class="w-8 h-8 rounded-full bg-secondary flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
              title="Manage"
            >
              <Settings size={14} />
            </a>
            <button
              class="w-8 h-8 rounded-full bg-secondary/50 flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
              onclick={() => handleDelete(lib.id, lib.name)}
              title="Delete"
            >
              <Trash2 size={14} />
            </button>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

<Modal title="Create Library" open={showCreateModal} onclose={() => (showCreateModal = false)}>
  <div class="space-y-4">
    <div class="space-y-1">
      <label class="block text-sm font-medium text-foreground" for="lib-name">Name</label>
      <input id="lib-name" bind:value={createForm.name} class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30" />
    </div>
    <div class="space-y-1">
      <label class="block text-sm font-medium text-foreground" for="lib-desc">Description</label>
      <input id="lib-desc" bind:value={createForm.description} class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30" />
    </div>
    <div class="space-y-1">
      <label class="block text-sm font-medium text-foreground" for="lib-vis">Visibility</label>
      <select id="lib-vis" bind:value={createForm.visibility} class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30">
        <option value={LibraryVisibility.Public}>Public</option>
        <option value={LibraryVisibility.Private}>Private (whitelist)</option>
      </select>
    </div>
    <div class="flex justify-end gap-2 pt-2">
      <button class="px-4 py-2 text-sm text-muted-foreground hover:text-foreground" onclick={() => (showCreateModal = false)}>Cancel</button>
      <button
        disabled={!createForm.name || creating}
        class="px-5 py-2.5 text-sm bg-primary hover:bg-primary/90 disabled:opacity-50 text-primary-foreground font-semibold rounded-xl"
        onclick={handleCreate}
      >
        {creating ? 'Creating...' : 'Create'}
      </button>
    </div>
  </div>
</Modal>
