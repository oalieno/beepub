<script lang="ts">
  import { page } from "$app/state";
  import { onMount } from "svelte";
  import { adminApi } from "$lib/api/admin";
  import { toastStore } from "$lib/stores/toast";
  import type { UserOut, UserLibraryAccess } from "$lib/types";
  import { UserRole } from "$lib/types";
  import {
    Shield,
    User,
    Download,
    Library,
    KeyRound,
    Trash2,
    TriangleAlert,
  } from "@lucide/svelte";
  import { authStore } from "$lib/stores/auth";
  import BackButton from "$lib/components/BackButton.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as Dialog from "$lib/components/ui/dialog";
  import { goto } from "$app/navigation";

  let userId = $derived(page.params.id as string);
  let user = $state<UserOut | null>(null);
  let allUsers = $state<UserOut[]>([]);
  let libraryAccess = $state<UserLibraryAccess[]>([]);
  let loading = $state(true);

  // Reset password dialog
  let showResetDialog = $state(false);
  let resetPassword = $state("");
  let resetting = $state(false);

  onMount(async () => {
    await loadData();
  });

  async function loadData() {
    loading = true;
    try {
      const [users, access] = await Promise.all([
        adminApi.getUsers(),
        adminApi.getLibraryAccess(userId),
      ]);
      allUsers = users;
      user = users.find((u) => u.id === userId) ?? null;
      libraryAccess = access;
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function toggleDownload() {
    if (!user) return;
    try {
      const updated = await adminApi.updatePermissions(userId, {
        can_download: !user.can_download,
      });
      user = updated;
      toastStore.success(
        `Download ${updated.can_download ? "enabled" : "disabled"} for ${user.username}`,
      );
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function toggleLibraryExclusion(libraryId: string) {
    const current = libraryAccess.find((a) => a.library_id === libraryId);
    if (!current) return;

    const newExcluded = libraryAccess
      .map((a) => {
        if (a.library_id === libraryId) {
          return { ...a, excluded: !a.excluded };
        }
        return a;
      })
      .filter((a) => a.excluded)
      .map((a) => a.library_id);

    try {
      await adminApi.updateLibraryAccess(userId, newExcluded);
      libraryAccess = libraryAccess.map((a) =>
        a.library_id === libraryId ? { ...a, excluded: !a.excluded } : a,
      );
      toastStore.success(
        `${current.excluded ? "Granted" : "Revoked"} access to ${current.library_name}`,
      );
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function setAllLibraryAccess(grantAll: boolean) {
    const newExcluded = grantAll ? [] : libraryAccess.map((a) => a.library_id);

    try {
      await adminApi.updateLibraryAccess(userId, newExcluded);
      libraryAccess = libraryAccess.map((a) => ({
        ...a,
        excluded: !grantAll,
      }));
      toastStore.success(
        grantAll ? "Granted all library access" : "Revoked all library access",
      );
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function toggleRole() {
    if (!user) return;
    const newRole =
      user.role === UserRole.Admin ? UserRole.User : UserRole.Admin;
    try {
      await adminApi.updateRole(userId, newRole);
      user = { ...user, role: newRole };
      toastStore.success(`Updated role for ${user.username}`);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleResetPassword() {
    if (!user || !resetPassword) return;
    resetting = true;
    try {
      await adminApi.resetPassword(userId, resetPassword);
      toastStore.success(`Password reset for ${user.username}`);
      showResetDialog = false;
      resetPassword = "";
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      resetting = false;
    }
  }

  async function handleDelete() {
    if (!user) return;
    if (!confirm(`Delete user "${user.username}"? This cannot be undone.`))
      return;
    try {
      await adminApi.deleteUser(userId);
      toastStore.success(`Deleted user ${user.username}`);
      goto("/admin/users");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  let isAdmin = $derived(user?.role === UserRole.Admin);
  let isSelf = $derived(user?.id === $authStore.user?.id);
  let isLastAdmin = $derived(
    isAdmin && allUsers.filter((u) => u.role === UserRole.Admin).length <= 1,
  );
  let cannotDelete = $derived(isSelf);
  let allGranted = $derived(libraryAccess.every((a) => !a.excluded));
  let allExcluded = $derived(libraryAccess.every((a) => a.excluded));
</script>

<svelte:head>
  <title>{user?.username ?? "User"} - Admin - BeePub</title>
</svelte:head>

<div class="max-w-3xl mx-auto px-4 sm:px-8 py-6">
  <div class="mb-1">
    <BackButton href="/admin/users" label="Users" />
  </div>

  {#if loading}
    <div class="animate-pulse space-y-4 mt-6">
      <div class="h-8 bg-secondary/50 rounded w-48"></div>
      <div class="h-4 bg-secondary/30 rounded w-32"></div>
      <div class="h-32 bg-secondary/20 rounded-2xl"></div>
    </div>
  {:else if !user}
    <p class="text-muted-foreground mt-6">User not found.</p>
  {:else}
    <!-- Header -->
    <div class="flex items-center justify-between mt-4 mb-8">
      <div>
        <h1 class="text-3xl font-bold text-foreground">{user.username}</h1>
        <div class="flex items-center gap-3 mt-2">
          <span
            class="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full font-medium {isAdmin
              ? 'bg-primary/10 text-primary'
              : 'bg-secondary text-muted-foreground'}"
          >
            {#if isAdmin}
              <Shield size={10} />
            {:else}
              <User size={10} />
            {/if}
            {user.role}
          </span>
          <span class="text-sm text-muted-foreground">
            Joined {new Date(user.created_at).toLocaleDateString()}
          </span>
        </div>
      </div>
    </div>

    {#if isLastAdmin}
      <div
        class="flex items-center gap-2 px-4 py-3 mb-6 rounded-xl bg-amber-500/10 text-amber-700 text-sm"
      >
        <TriangleAlert size={16} class="shrink-0" />
        This is the only admin. Cannot demote or delete.
      </div>
    {/if}

    <!-- Actions -->
    <div class="flex items-center gap-3 flex-wrap mb-6">
      <Button
        variant="outline"
        class="rounded-xl bg-white"
        onclick={toggleRole}
        disabled={isLastAdmin}
      >
        <Shield size={14} />
        {isAdmin ? "Demote to User" : "Promote to Admin"}
      </Button>
      <Button
        variant="outline"
        class="rounded-xl bg-white"
        onclick={() => {
          resetPassword = "";
          showResetDialog = true;
        }}
      >
        <KeyRound size={14} />
        Reset Password
      </Button>
    </div>

    <!-- Permissions -->
    {#if isAdmin}
      <div class="bg-card card-soft rounded-2xl p-5 mb-6">
        <div class="flex items-center gap-2 text-muted-foreground">
          <Shield size={16} />
          <span class="text-sm"
            >Admin users have full access to all features and libraries.</span
          >
        </div>
      </div>
    {:else}
      <!-- Download Permission -->
      <div class="bg-card card-soft rounded-2xl p-5 mb-6">
        <h2 class="text-lg font-semibold text-foreground mb-4">Permissions</h2>
        <div class="flex items-center justify-between gap-4">
          <div class="flex items-center gap-3 min-w-0">
            <Download size={18} class="text-muted-foreground shrink-0" />
            <div class="min-w-0">
              <p class="text-sm font-medium text-foreground">Download EPUBs</p>
              <p class="text-xs text-muted-foreground">
                Allow this user to download EPUB files to their device
              </p>
            </div>
          </div>
          <button
            class="relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors {user.can_download
              ? 'bg-primary'
              : 'bg-secondary'}"
            onclick={toggleDownload}
            aria-label="Toggle download permission"
          >
            <span
              class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform {user.can_download
                ? 'translate-x-6'
                : 'translate-x-1'}"
            ></span>
          </button>
        </div>
      </div>

      <!-- Library Access -->
      <div class="bg-card card-soft rounded-2xl p-5 mb-6">
        <div class="flex items-center justify-between gap-3 mb-4">
          <h2 class="text-lg font-semibold text-foreground shrink-0">
            Library Access
          </h2>
          {#if libraryAccess.length > 1}
            <div class="flex items-center gap-1.5">
              <button
                class="text-xs px-2 py-1 rounded-lg bg-secondary hover:bg-secondary/80 text-foreground font-medium transition-colors disabled:opacity-40 whitespace-nowrap"
                onclick={() => setAllLibraryAccess(true)}
                disabled={allGranted}
              >
                Select all
              </button>
              <button
                class="text-xs px-2 py-1 rounded-lg bg-secondary hover:bg-secondary/80 text-foreground font-medium transition-colors disabled:opacity-40 whitespace-nowrap"
                onclick={() => setAllLibraryAccess(false)}
                disabled={allExcluded}
              >
                Deselect all
              </button>
            </div>
          {/if}
        </div>
        {#if libraryAccess.length === 0}
          <p class="text-sm text-muted-foreground">No libraries configured.</p>
        {:else}
          <div class="space-y-3">
            {#each libraryAccess as lib}
              <div class="flex items-center justify-between gap-4">
                <div class="flex items-center gap-3 min-w-0">
                  <Library size={18} class="text-muted-foreground shrink-0" />
                  <span class="text-sm font-medium text-foreground truncate"
                    >{lib.library_name}</span
                  >
                </div>
                <button
                  class="relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors {!lib.excluded
                    ? 'bg-primary'
                    : 'bg-secondary'}"
                  onclick={() => toggleLibraryExclusion(lib.library_id)}
                  aria-label="Toggle access to {lib.library_name}"
                >
                  <span
                    class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform {!lib.excluded
                      ? 'translate-x-6'
                      : 'translate-x-1'}"
                  ></span>
                </button>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    <!-- Danger Zone -->
    <h2 class="text-sm font-semibold text-destructive mb-2 ml-1">
      Danger Zone
    </h2>
    <div class="border border-destructive/30 rounded-2xl p-5">
      <div class="flex items-center justify-between gap-4">
        <div class="min-w-0">
          <p class="text-sm font-medium text-foreground">Delete this user</p>
          <p class="text-xs text-muted-foreground">
            Permanently remove this user and all their data.
          </p>
        </div>
        <Button
          variant="outline"
          class="rounded-xl border-destructive/30 text-destructive hover:bg-destructive hover:text-white shrink-0"
          onclick={handleDelete}
          disabled={cannotDelete}
        >
          <Trash2 size={14} />
          Delete
        </Button>
      </div>
    </div>
  {/if}
</div>

<!-- Reset Password Dialog -->
<Dialog.Root bind:open={showResetDialog}>
  <Dialog.Content class="sm:max-w-md bg-white dark:bg-neutral-900">
    <Dialog.Header>
      <Dialog.Title>Reset Password</Dialog.Title>
      <Dialog.Description
        >Set a new password for {user?.username}</Dialog.Description
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
