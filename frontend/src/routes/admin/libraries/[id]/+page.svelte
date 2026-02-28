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
  import { Trash2, UserPlus, Save } from 'lucide-svelte';

  $: libraryId = $page.params.id;

  let library: LibraryOut | null = null;
  let members: { user_id: string; granted_by: string; granted_at: string }[] = [];
  let allUsers: UserOut[] = [];
  let loading = true;
  let saving = false;
  let editForm = { name: '', description: '', visibility: LibraryVisibility.Public as string };
  let addUserId = '';

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
        description: editForm.description || undefined,
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

  $: nonMembers = allUsers.filter(u => !members.some(m => m.user_id === u.id));
</script>

<svelte:head>
  <title>{library?.name ?? 'Library'} - Admin - BeePub</title>
</svelte:head>

<div class="max-w-2xl mx-auto px-4 py-8">
  <div class="flex items-center gap-3 mb-8">
    <a href="/admin/libraries" class="text-gray-400 hover:text-white text-sm">← Libraries</a>
    <h1 class="text-3xl font-bold">{library?.name ?? 'Library'}</h1>
  </div>

  {#if loading}
    <div class="flex items-center justify-center h-40">
      <div class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-amber-500"></div>
    </div>
  {:else if library}
    <!-- Edit form -->
    <div class="bg-gray-800 rounded-xl p-6 mb-6">
      <h2 class="font-semibold text-lg mb-4">Settings</h2>
      <div class="space-y-4">
        <div>
          <label class="block text-sm text-gray-400 mb-1">Name</label>
          <input bind:value={editForm.name} class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-500" />
        </div>
        <div>
          <label class="block text-sm text-gray-400 mb-1">Description</label>
          <input bind:value={editForm.description} class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-500" />
        </div>
        <div>
          <label class="block text-sm text-gray-400 mb-1">Visibility</label>
          <select bind:value={editForm.visibility} class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-500">
            <option value="public">Public</option>
            <option value="private">Private (whitelist)</option>
          </select>
        </div>
        <button
          disabled={saving}
          class="flex items-center gap-2 bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-gray-900 font-semibold px-4 py-2 rounded-lg"
          on:click={handleSave}
        >
          <Save size={16} />
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>
    </div>

    <!-- Members (only relevant for private libraries) -->
    {#if editForm.visibility === 'private'}
      <div class="bg-gray-800 rounded-xl p-6">
        <h2 class="font-semibold text-lg mb-4">Whitelist Members</h2>

        <!-- Add member -->
        <div class="flex gap-2 mb-4">
          <select bind:value={addUserId} class="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-500">
            <option value="">Select user to add...</option>
            {#each nonMembers as user}
              <option value={user.id}>{user.username} ({user.email})</option>
            {/each}
          </select>
          <button
            disabled={!addUserId}
            class="flex items-center gap-2 bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-gray-900 font-semibold px-3 py-2 rounded-lg"
            on:click={handleAddMember}
          >
            <UserPlus size={16} />
          </button>
        </div>

        {#if members.length === 0}
          <p class="text-gray-500 text-sm">No members. Add users to grant access.</p>
        {:else}
          <div class="space-y-2">
            {#each members as member}
              {@const user = getUserById(member.user_id)}
              <div class="flex items-center justify-between bg-gray-700 rounded-lg px-3 py-2">
                <div>
                  <p class="text-sm font-medium">{user?.username ?? member.user_id}</p>
                  <p class="text-xs text-gray-500">Added {new Date(member.granted_at).toLocaleDateString()}</p>
                </div>
                <button
                  class="text-gray-500 hover:text-red-400"
                  on:click={() => handleRemoveMember(member.user_id)}
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
