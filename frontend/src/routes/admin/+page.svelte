<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import { adminApi } from '$lib/api/bookshelves';
  import { toastStore } from '$lib/stores/toast';
  import type { AdminStats } from '$lib/types';
  import { UserRole } from '$lib/types';
  import { Users, BookOpen, Library, ChevronRight } from 'lucide-svelte';

  let stats: AdminStats | null = null;
  let loading = true;

  onMount(async () => {
    if (!$authStore.user || $authStore.user.role !== UserRole.Admin) {
      goto('/');
      return;
    }
    try {
      stats = await adminApi.getStats($authStore.token!);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  });
</script>

<svelte:head>
  <title>Admin - BeePub</title>
</svelte:head>

<div class="max-w-4xl mx-auto px-4 py-8">
  <h1 class="text-3xl font-bold mb-8">Admin Dashboard</h1>

  {#if loading}
    <div class="flex items-center justify-center h-40">
      <div class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-amber-500"></div>
    </div>
  {:else}
    <!-- Stats -->
    <div class="grid grid-cols-3 gap-4 mb-8">
      <div class="bg-gray-800 rounded-xl p-5 text-center">
        <Users class="mx-auto text-amber-500 mb-2" size={28} />
        <p class="text-3xl font-bold">{stats?.users ?? 0}</p>
        <p class="text-gray-400 text-sm">Users</p>
      </div>
      <div class="bg-gray-800 rounded-xl p-5 text-center">
        <BookOpen class="mx-auto text-amber-500 mb-2" size={28} />
        <p class="text-3xl font-bold">{stats?.books ?? 0}</p>
        <p class="text-gray-400 text-sm">Books</p>
      </div>
      <div class="bg-gray-800 rounded-xl p-5 text-center">
        <Library class="mx-auto text-amber-500 mb-2" size={28} />
        <p class="text-3xl font-bold">{stats?.libraries ?? 0}</p>
        <p class="text-gray-400 text-sm">Libraries</p>
      </div>
    </div>

    <!-- Links -->
    <div class="space-y-3">
      <a
        href="/admin/libraries"
        class="flex items-center justify-between bg-gray-800 hover:bg-gray-750 rounded-xl p-4 transition-colors group"
      >
        <div class="flex items-center gap-3">
          <Library class="text-amber-500" size={20} />
          <div>
            <p class="font-semibold">Libraries</p>
            <p class="text-gray-400 text-sm">Manage libraries, visibility, and book access</p>
          </div>
        </div>
        <ChevronRight class="text-gray-500 group-hover:text-white transition-colors" size={20} />
      </a>
      <a
        href="/admin/users"
        class="flex items-center justify-between bg-gray-800 hover:bg-gray-750 rounded-xl p-4 transition-colors group"
      >
        <div class="flex items-center gap-3">
          <Users class="text-amber-500" size={20} />
          <div>
            <p class="font-semibold">Users</p>
            <p class="text-gray-400 text-sm">Manage user roles and accounts</p>
          </div>
        </div>
        <ChevronRight class="text-gray-500 group-hover:text-white transition-colors" size={20} />
      </a>
    </div>
  {/if}
</div>
