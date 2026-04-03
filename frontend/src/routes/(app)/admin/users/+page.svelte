<script lang="ts">
  import { onMount } from "svelte";
  import { adminApi } from "$lib/api/admin";
  import { toastStore } from "$lib/stores/toast";
  import type { UserOut } from "$lib/types";
  import { UserRole } from "$lib/types";
  import { Shield, User, UserPlus, ChevronRight } from "@lucide/svelte";
  import { TableSkeleton } from "$lib/components/skeletons";
  import BackButton from "$lib/components/BackButton.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as Dialog from "$lib/components/ui/dialog";
  import { goto } from "$app/navigation";

  let users = $state<UserOut[]>([]);
  let loading = $state(true);

  // Create user dialog
  let showCreateDialog = $state(false);
  let newUsername = $state("");
  let newPassword = $state("");
  let creating = $state(false);
  let createError = $state("");

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
    <TableSkeleton rows={5} columns={3} />
  {:else}
    <div class="bg-card card-soft rounded-2xl overflow-hidden overflow-x-auto">
      <table class="w-full min-w-[500px]">
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
            <th class="w-10 px-5 py-3.5"></th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border/30">
          {#each users as user}
            <tr
              class="hover:bg-secondary/30 transition-colors cursor-pointer"
              onclick={() => goto(`/admin/users/${user.id}`)}
            >
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
              <td class="px-5 py-3.5 text-muted-foreground">
                <ChevronRight size={16} />
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
  <Dialog.Content class="sm:max-w-md bg-white dark:bg-neutral-900">
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
