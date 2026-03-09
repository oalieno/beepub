<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { adminApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import type { UserOut } from "$lib/types";
  import { UserRole } from "$lib/types";
  import { Trash2, Shield, User } from "@lucide/svelte";

  let users = $state<UserOut[]>([]);
  let loading = $state(true);

  onMount(async () => {
    if (!$authStore.user || $authStore.user.role !== UserRole.Admin) {
      goto("/");
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
    const newRole =
      user.role === UserRole.Admin ? UserRole.User : UserRole.Admin;
    try {
      await adminApi.updateRole(user.id, newRole, $authStore.token);
      users = users.map((u) =>
        u.id === user.id ? { ...u, role: newRole } : u,
      );
      toastStore.success(`Updated role for ${user.username}`);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleDelete(user: UserOut) {
    if (!confirm(`Delete user "${user.username}"?`) || !$authStore.token)
      return;
    try {
      await adminApi.deleteUser(user.id, $authStore.token);
      users = users.filter((u) => u.id !== user.id);
      toastStore.success(`Deleted user ${user.username}`);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>Users - Admin - BeePub</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
  <div class="mb-8">
    <a
      href="/admin"
      class="text-muted-foreground hover:text-foreground text-sm mb-1 inline-block"
      >← Admin</a
    >
    <h1 class="text-3xl font-bold text-foreground">Users</h1>
    <p class="text-muted-foreground mt-1">Manage user accounts and roles</p>
  </div>

  {#if loading}
    <div class="flex items-center justify-center h-40">
      <div
        class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-primary"
      ></div>
    </div>
  {:else}
    <div class="bg-card card-soft rounded-2xl overflow-hidden overflow-x-auto">
      <table class="w-full min-w-[600px]">
        <thead class="border-b border-border/50">
          <tr>
            <th
              class="text-left px-5 py-3.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider"
              >Username</th
            >
            <th
              class="text-left px-5 py-3.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider"
              >Email</th
            >
            <th
              class="text-left px-5 py-3.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider"
              >Role</th
            >
            <th
              class="text-left px-5 py-3.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider"
              >Joined</th
            >
            <th class="px-5 py-3.5"></th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border/30">
          {#each users as user}
            <tr class="hover:bg-secondary/30 transition-colors">
              <td class="px-5 py-3.5 font-medium text-foreground"
                >{user.username}</td
              >
              <td class="px-5 py-3.5 text-muted-foreground text-sm"
                >{user.email}</td
              >
              <td class="px-5 py-3.5">
                <span
                  class="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full font-medium {user.role ===
                  UserRole.Admin
                    ? 'bg-primary/10 text-primary'
                    : 'bg-secondary text-muted-foreground'}"
                >
                  {#if user.role === UserRole.Admin}
                    <Shield size={10} />
                  {:else}
                    <User size={10} />
                  {/if}
                  {user.role}
                </span>
              </td>
              <td class="px-5 py-3.5 text-muted-foreground text-sm"
                >{new Date(user.created_at).toLocaleDateString()}</td
              >
              <td class="px-5 py-3.5">
                <div class="flex items-center justify-end gap-2">
                  {#if user.id !== $authStore.user?.id}
                    <button
                      class="text-xs px-3 py-1.5 rounded-lg bg-secondary hover:bg-secondary/80 text-foreground font-medium transition-colors"
                      onclick={() => toggleRole(user)}
                      title="Toggle admin role"
                    >
                      {user.role === UserRole.Admin ? "Demote" : "Promote"}
                    </button>
                    <button
                      class="w-7 h-7 rounded-full bg-secondary/50 flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                      onclick={() => handleDelete(user)}
                      title="Delete user"
                    >
                      <Trash2 size={13} />
                    </button>
                  {:else}
                    <span class="text-xs text-muted-foreground italic">You</span
                    >
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
