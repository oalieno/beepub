<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import { adminApi } from '$lib/api/bookshelves';
  import { toastStore } from '$lib/stores/toast';
  import type { UserOut } from '$lib/types';
  import { UserRole } from '$lib/types';
  import { Trash2, Shield, User } from 'lucide-svelte';

  let users: UserOut[] = [];
  let loading = true;

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
      users = await adminApi.getUsers($authStore.token!);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function toggleRole(user: UserOut) {
    if (!$authStore.token) return;
    const newRole = user.role === UserRole.Admin ? UserRole.User : UserRole.Admin;
    try {
      await adminApi.updateRole(user.id, newRole, $authStore.token);
      users = users.map(u => u.id === user.id ? { ...u, role: newRole } : u);
      toastStore.success(`Updated role for ${user.username}`);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleDelete(user: UserOut) {
    if (!confirm(`Delete user "${user.username}"?`) || !$authStore.token) return;
    try {
      await adminApi.deleteUser(user.id, $authStore.token);
      users = users.filter(u => u.id !== user.id);
      toastStore.success(`Deleted user ${user.username}`);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>Users - Admin - BeePub</title>
</svelte:head>

<div class="max-w-4xl mx-auto px-4 py-8">
  <div class="flex items-center gap-3 mb-8">
    <a href="/admin" class="text-gray-400 hover:text-white text-sm">← Admin</a>
    <h1 class="text-3xl font-bold">Users</h1>
  </div>

  {#if loading}
    <div class="flex items-center justify-center h-40">
      <div class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-amber-500"></div>
    </div>
  {:else}
    <div class="bg-gray-800 rounded-xl overflow-hidden">
      <table class="w-full">
        <thead class="bg-gray-750 border-b border-gray-700">
          <tr>
            <th class="text-left px-4 py-3 text-sm font-medium text-gray-400">Username</th>
            <th class="text-left px-4 py-3 text-sm font-medium text-gray-400">Email</th>
            <th class="text-left px-4 py-3 text-sm font-medium text-gray-400">Role</th>
            <th class="text-left px-4 py-3 text-sm font-medium text-gray-400">Joined</th>
            <th class="px-4 py-3"></th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-700">
          {#each users as user}
            <tr class="hover:bg-gray-750">
              <td class="px-4 py-3 font-medium">{user.username}</td>
              <td class="px-4 py-3 text-gray-400 text-sm">{user.email}</td>
              <td class="px-4 py-3">
                <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded {user.role === UserRole.Admin ? 'bg-amber-900 text-amber-300' : 'bg-gray-700 text-gray-300'}">
                  {#if user.role === UserRole.Admin}
                    <Shield size={10} />
                  {:else}
                    <User size={10} />
                  {/if}
                  {user.role}
                </span>
              </td>
              <td class="px-4 py-3 text-gray-400 text-sm">{new Date(user.created_at).toLocaleDateString()}</td>
              <td class="px-4 py-3">
                <div class="flex items-center justify-end gap-2">
                  {#if user.id !== $authStore.user?.id}
                    <button
                      class="text-xs px-2 py-1 border border-gray-600 hover:border-gray-500 rounded text-gray-300 hover:text-white"
                      on:click={() => toggleRole(user)}
                      title="Toggle admin role"
                    >
                      {user.role === UserRole.Admin ? 'Demote' : 'Promote'}
                    </button>
                    <button
                      class="p-1 text-gray-500 hover:text-red-400"
                      on:click={() => handleDelete(user)}
                      title="Delete user"
                    >
                      <Trash2 size={14} />
                    </button>
                  {:else}
                    <span class="text-xs text-gray-600">You</span>
                  {/if}
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
