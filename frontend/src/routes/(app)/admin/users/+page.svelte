<script lang="ts">
  import { onMount } from "svelte";
  import { authStore } from "$lib/stores/auth";
  import { adminApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import type { UserOut } from "$lib/types";
  import { UserRole } from "$lib/types";
  import { Trash2, Shield, User, UserPlus, KeyRound } from "@lucide/svelte";
  import { TableSkeleton } from "$lib/components/skeletons";
  import BackButton from "$lib/components/BackButton.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as Dialog from "$lib/components/ui/dialog";

  let users = $state<UserOut[]>([]);
  let loading = $state(true);

  // Create user dialog
  let showCreateDialog = $state(false);
  let newUsername = $state("");
  let newPassword = $state("");
  let creating = $state(false);
  let createError = $state("");

  // Reset password dialog
  let showResetDialog = $state(false);
  let resetUser = $state<UserOut | null>(null);
  let resetPassword = $state("");
  let resetting = $state(false);

  onMount(async () => {
    await loadData();
  });

  async function loadData() {
    loading = true;
    try {
      users = await adminApi.getUsers();
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleCreateUser() {
    if (!newUsername || !newPassword) return;
    creating = true;
    createError = "";
    try {
      const user = await adminApi.createUser({
        username: newUsername,
        password: newPassword,
      });
      users = [...users, user];
      showCreateDialog = false;
      newUsername = "";
      newPassword = "";
      toastStore.success(`Created user ${user.username}`);
    } catch (e) {
      createError = (e as Error).message;
    } finally {
      creating = false;
    }
  }

  async function toggleRole(user: UserOut) {
    const newRole =
      user.role === UserRole.Admin ? UserRole.User : UserRole.Admin;
    try {
      await adminApi.updateRole(user.id, newRole);
      users = users.map((u) =>
        u.id === user.id ? { ...u, role: newRole } : u,
      );
      toastStore.success(`Updated role for ${user.username}`);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleResetPassword() {
    if (!resetUser || !resetPassword) return;
    resetting = true;
    try {
      await adminApi.resetPassword(resetUser.id, resetPassword);
      toastStore.success(`Password reset for ${resetUser.username}`);
      showResetDialog = false;
      resetUser = null;
      resetPassword = "";
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      resetting = false;
    }
  }

  async function handleDelete(user: UserOut) {
    if (!confirm(`Delete user "${user.username}"?`)) return;
    try {
      await adminApi.deleteUser(user.id);
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

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
  <div class="flex items-start justify-between mb-8">
    <div>
      <div class="mb-1">
        <BackButton href="/admin" label="Admin" />
      </div>
      <h1 class="text-3xl font-bold text-foreground">Users</h1>
      <p class="text-muted-foreground mt-1">Manage user accounts and roles</p>
    </div>
    <Button
      class="rounded-xl"
      onclick={() => {
        createError = "";
        showCreateDialog = true;
      }}
    >
      <UserPlus size={16} />
      Create User
    </Button>
  </div>

  {#if loading}
    <TableSkeleton rows={5} columns={5} />
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
                      class="text-xs px-3 py-1.5 rounded-lg bg-secondary hover:bg-secondary/80 text-foreground font-medium transition-colors"
                      onclick={() => {
                        resetUser = user;
                        resetPassword = "";
                        showResetDialog = true;
                      }}
                      title="Reset password"
                    >
                      <KeyRound size={13} />
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

<!-- Create User Dialog -->
<Dialog.Root bind:open={showCreateDialog}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Create User</Dialog.Title>
      <Dialog.Description>Create a new user account</Dialog.Description>
    </Dialog.Header>
    <form
      onsubmit={(e) => {
        e.preventDefault();
        handleCreateUser();
      }}
      class="space-y-4"
    >
      <div class="space-y-1.5">
        <Label for="new-username">Username</Label>
        <Input
          id="new-username"
          bind:value={newUsername}
          placeholder="Username"
          required
        />
      </div>
      <div class="space-y-1.5">
        <Label for="new-password">Password</Label>
        <Input
          id="new-password"
          type="password"
          bind:value={newPassword}
          placeholder="Password"
          required
        />
      </div>
      {#if createError}
        <p class="text-sm text-red-600">{createError}</p>
      {/if}
      <Dialog.Footer>
        <Button
          variant="outline"
          class="rounded-xl"
          onclick={() => (showCreateDialog = false)}>Cancel</Button
        >
        <Button type="submit" disabled={creating} class="rounded-xl">
          {creating ? "Creating..." : "Create"}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>

<!-- Reset Password Dialog -->
<Dialog.Root bind:open={showResetDialog}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Reset Password</Dialog.Title>
      <Dialog.Description
        >Set a new password for {resetUser?.username}</Dialog.Description
      >
    </Dialog.Header>
    <form
      onsubmit={(e) => {
        e.preventDefault();
        handleResetPassword();
      }}
      class="space-y-4"
    >
      <div class="space-y-1.5">
        <Label for="reset-password">New Password</Label>
        <Input
          id="reset-password"
          type="password"
          bind:value={resetPassword}
          placeholder="New password"
          required
        />
      </div>
      <Dialog.Footer>
        <Button
          variant="outline"
          class="rounded-xl"
          onclick={() => (showResetDialog = false)}>Cancel</Button
        >
        <Button type="submit" disabled={resetting} class="rounded-xl">
          {resetting ? "Resetting..." : "Reset Password"}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
