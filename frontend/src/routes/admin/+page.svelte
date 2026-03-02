<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import { adminApi } from '$lib/api/bookshelves';
  import { toastStore } from '$lib/stores/toast';
  import type { AdminStats } from '$lib/types';
  import { UserRole } from '$lib/types';
  import { Users, BookOpen, Library, ChevronRight } from '@lucide/svelte';

  let stats = $state<AdminStats | null>(null);
  let loading = $state(true);

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

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
  <div class="mb-8">
    <h1 class="text-3xl font-bold text-foreground">Admin Dashboard</h1>
    <p class="text-muted-foreground mt-1">Overview and management tools</p>
  </div>

  {#if loading}
    <div class="flex items-center justify-center h-40">
      <div class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-primary"></div>
    </div>
  {:else}
    <!-- Stats -->
    <div class="grid grid-cols-3 gap-4 mb-10">
      <div class="bg-card card-soft rounded-2xl p-6 text-center">
        <div class="mx-auto w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center mb-3"><Users class="text-primary" size={22} /></div>
        <p class="text-3xl font-bold text-foreground">{stats?.users ?? 0}</p>
        <p class="text-muted-foreground text-sm mt-0.5">Users</p>
      </div>
      <div class="bg-card card-soft rounded-2xl p-6 text-center">
        <div class="mx-auto w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center mb-3"><BookOpen class="text-primary" size={22} /></div>
        <p class="text-3xl font-bold text-foreground">{stats?.books ?? 0}</p>
        <p class="text-muted-foreground text-sm mt-0.5">Books</p>
      </div>
      <div class="bg-card card-soft rounded-2xl p-6 text-center">
        <div class="mx-auto w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center mb-3"><Library class="text-primary" size={22} /></div>
        <p class="text-3xl font-bold text-foreground">{stats?.libraries ?? 0}</p>
        <p class="text-muted-foreground text-sm mt-0.5">Libraries</p>
      </div>
    </div>

    <!-- Links -->
    <div class="space-y-3">
      <a
        href="/admin/libraries"
        class="flex items-center justify-between bg-card card-soft rounded-2xl hover:shadow-md p-5 transition-all duration-200 group"
      >
        <div class="flex items-center gap-4">
          <div class="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
            <Library class="text-primary" size={18} />
          </div>
          <div>
            <p class="font-semibold text-foreground group-hover:text-primary transition-colors">Libraries</p>
            <p class="text-muted-foreground text-sm">Manage libraries, visibility, and book access</p>
          </div>
        </div>
        <ChevronRight class="text-muted-foreground/40 group-hover:text-primary transition-colors" size={20} />
      </a>
      <a
        href="/admin/users"
        class="flex items-center justify-between bg-card card-soft rounded-2xl hover:shadow-md p-5 transition-all duration-200 group"
      >
        <div class="flex items-center gap-4">
          <div class="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
            <Users class="text-primary" size={18} />
          </div>
          <div>
            <p class="font-semibold text-foreground group-hover:text-primary transition-colors">Users</p>
            <p class="text-muted-foreground text-sm">Manage user roles and accounts</p>
          </div>
        </div>
        <ChevronRight class="text-muted-foreground/40 group-hover:text-primary transition-colors" size={20} />
      </a>
    </div>
  {/if}
</div>
