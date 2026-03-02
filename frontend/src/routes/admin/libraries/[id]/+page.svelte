<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import { librariesApi } from '$lib/api/libraries';
  import { adminApi } from '$lib/api/bookshelves';
  import { toastStore } from '$lib/stores/toast';
  import type { LibraryOut, UserOut } from '$lib/types';
  import { UserRole, LibraryVisibility } from '$lib/types';
  import { Trash2, UserPlus, Save } from '@lucide/svelte';

  let libraryId = $derived($page.params.id as string);

  let library = $state<LibraryOut | null>(null);
  let members = $state<{ user_id: string; granted_by: string; granted_at: string }[]>([]);
  let allUsers = $state<UserOut[]>([]);
  let loading = $state(true);
  let saving = $state(false);
  let editForm = $state({ name: '', description: '', visibility: LibraryVisibility.Public as string });
  let addUserId = $state('');

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
      [library, members, allUsers] = await Promise.all([
        librariesApi.get(libraryId, $authStore.token!),
        librariesApi.getMembers(libraryId, $authStore.token!).catch(() => []),
        adminApi.getUsers($authStore.token!),
      ]);
      if (library) {
        editForm = { name: library.name, description: library.description ?? '', visibility: library.visibility };
      }
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleSave() {
    if (!$authStore.token) return;
    saving = true;
    try {
      library = await librariesApi.update(libraryId, {
        name: editForm.name,
        description: editForm.description,
        visibility: editForm.visibility,
      }, $authStore.token);
      toastStore.success('Library updated');
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      saving = false;
    }
  }

  async function handleAddMember() {
    if (!addUserId || !$authStore.token) return;
    try {
      await librariesApi.addMember(libraryId, addUserId, $authStore.token);
      members = await librariesApi.getMembers(libraryId, $authStore.token);
      addUserId = '';
      toastStore.success('Member added');
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleRemoveMember(userId: string) {
    if (!$authStore.token) return;
    try {
      await librariesApi.removeMember(libraryId, userId, $authStore.token);
      members = members.filter(m => m.user_id !== userId);
      toastStore.success('Member removed');
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function getUserById(id: string) {
    return allUsers.find(u => u.id === id);
  }

  let nonMembers = $derived(allUsers.filter(u => !members.some(m => m.user_id === u.id)));
</script>

<svelte:head>
  <title>{library?.name ?? 'Library'} - Admin - BeePub</title>
</svelte:head>

<div class="max-w-2xl mx-auto px-4 sm:px-6 py-6">
  <div class="mb-8">
    <a href="/admin/libraries" class="text-muted-foreground hover:text-foreground text-sm mb-1 inline-block">← Libraries</a>
    <h1 class="text-3xl font-bold text-foreground">{library?.name ?? 'Library'}</h1>
  </div>

  {#if loading}
    <div class="flex items-center justify-center h-40">
      <div class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-primary"></div>
    </div>
  {:else if library}
    <!-- Edit form -->
    <div class="bg-card card-soft rounded-2xl p-6 mb-6">
      <h2 class="font-bold text-lg mb-4 text-foreground">Settings</h2>
      <div class="space-y-4">
        <div class="space-y-1">
          <label class="block text-sm font-medium text-foreground" for="adm-lib-name">Name</label>
          <input id="adm-lib-name" bind:value={editForm.name} class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30" />
        </div>
        <div class="space-y-1">
          <label class="block text-sm font-medium text-foreground" for="adm-lib-desc">Description</label>
          <input id="adm-lib-desc" bind:value={editForm.description} class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30" />
        </div>
        <div class="space-y-1">
          <label class="block text-sm font-medium text-foreground" for="adm-lib-vis">Visibility</label>
          <select id="adm-lib-vis" bind:value={editForm.visibility} class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30">
            <option value="public">Public</option>
            <option value="private">Private (whitelist)</option>
          </select>
        </div>
        <button
          disabled={saving}
          class="flex items-center gap-2 bg-primary hover:bg-primary/90 disabled:opacity-50 text-primary-foreground font-medium px-5 py-2.5 rounded-xl transition-colors"
          onclick={handleSave}
        >
          <Save size={16} />
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>
    </div>

    <!-- Members (only relevant for private libraries) -->
    {#if editForm.visibility === 'private'}
      <div class="bg-card card-soft rounded-2xl p-6">
        <h2 class="font-bold text-lg mb-4 text-foreground">Whitelist Members</h2>

        <!-- Add member -->
        <div class="flex gap-2 mb-4">
          <select bind:value={addUserId} class="flex-1 border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30">
            <option value="">Select user to add...</option>
            {#each nonMembers as user}
              <option value={user.id}>{user.username} ({user.email})</option>
            {/each}
          </select>
          <button
            disabled={!addUserId}
            class="flex items-center gap-2 bg-primary hover:bg-primary/90 disabled:opacity-50 text-primary-foreground font-medium px-3 py-2.5 rounded-xl transition-colors"
            onclick={handleAddMember}
          >
            <UserPlus size={16} />
          </button>
        </div>

        {#if members.length === 0}
          <p class="text-muted-foreground text-sm">No members. Add users to grant access.</p>
        {:else}
          <div class="space-y-2">
            {#each members as member}
              {@const user = getUserById(member.user_id)}
              <div class="flex items-center justify-between rounded-xl bg-secondary/50 px-4 py-3">
                <div>
                  <p class="text-sm font-medium text-foreground">{user?.username ?? member.user_id}</p>
                  <p class="text-xs text-muted-foreground">Added {new Date(member.granted_at).toLocaleDateString()}</p>
                </div>
                <button
                  class="w-7 h-7 rounded-full bg-background/50 flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                  onclick={() => handleRemoveMember(member.user_id)}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  {/if}
</div>
