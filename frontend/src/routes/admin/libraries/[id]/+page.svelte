<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { librariesApi } from "$lib/api/libraries";
  import { adminApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import { Input } from "$lib/components/ui/input";
  import { Textarea } from "$lib/components/ui/textarea";
  import { Button } from "$lib/components/ui/button";
  import * as Select from "$lib/components/ui/select";
  import type { LibraryOut, UserOut } from "$lib/types";
  import { UserRole, LibraryVisibility } from "$lib/types";
  import { Trash2, UserPlus, Save } from "@lucide/svelte";
  import { FormSkeleton } from "$lib/components/skeletons";

  let libraryId = $derived(page.params.id as string);

  let library = $state<LibraryOut | null>(null);
  let members = $state<
    { user_id: string; granted_by: string; granted_at: string }[]
  >([]);
  let allUsers = $state<UserOut[]>([]);
  let loading = $state(true);
  let saving = $state(false);
  let editForm = $state({
    name: "",
    description: "",
    visibility: LibraryVisibility.Public as string,
  });
  let addUserId = $state("");

  const VISIBILITY_OPTIONS = [
    { value: LibraryVisibility.Public, label: "Public" },
    { value: LibraryVisibility.Private, label: "Private (whitelist)" },
  ];

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
      [library, members, allUsers] = await Promise.all([
        librariesApi.get(libraryId),
        librariesApi.getMembers(libraryId).catch(() => []),
        adminApi.getUsers(),
      ]);
      if (library) {
        editForm = {
          name: library.name,
          description: library.description ?? "",
          visibility: library.visibility,
        };
      }
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleSave() {
    saving = true;
    try {
      library = await librariesApi.update(libraryId, {
        name: editForm.name,
        description: editForm.description,
        visibility: editForm.visibility,
      });
      toastStore.success("Library updated");
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      saving = false;
    }
  }

  async function handleAddMember() {
    if (!addUserId) return;
    try {
      await librariesApi.addMember(libraryId, addUserId);
      members = await librariesApi.getMembers(libraryId);
      addUserId = "";
      toastStore.success("Member added");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleRemoveMember(userId: string) {
    try {
      await librariesApi.removeMember(libraryId, userId);
      members = members.filter((m) => m.user_id !== userId);
      toastStore.success("Member removed");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function getUserById(id: string) {
    return allUsers.find((u) => u.id === id);
  }

  let nonMembers = $derived(
    allUsers.filter((u) => !members.some((m) => m.user_id === u.id)),
  );
  let addUser = $derived(nonMembers.find((u) => u.id === addUserId));
</script>

<svelte:head>
  <title>{library?.name ?? "Library"} - Admin - BeePub</title>
</svelte:head>

<div class="max-w-2xl mx-auto px-4 sm:px-6 py-6">
  <div class="mb-8">
    <a
      href="/admin/libraries"
      class="text-muted-foreground hover:text-foreground text-sm mb-1 inline-block"
      >← Libraries</a
    >
    <h1 class="text-3xl font-bold text-foreground">
      {library?.name ?? "Library"}
    </h1>
  </div>

  {#if loading}
    <FormSkeleton cards={2} />
  {:else if library}
    <!-- Edit form -->
    <div class="bg-card card-soft rounded-2xl p-6 mb-6">
      <h2 class="font-bold text-lg mb-4 text-foreground">Settings</h2>
      <div class="space-y-4">
        <div class="space-y-1">
          <label
            class="block text-sm font-medium text-foreground"
            for="adm-lib-name">Name</label
          >
          <Input
            id="adm-lib-name"
            bind:value={editForm.name}
            class="rounded-sm"
          />
        </div>
        <div class="space-y-1">
          <label
            class="block text-sm font-medium text-foreground"
            for="adm-lib-desc">Description</label
          >
          <Textarea
            id="adm-lib-desc"
            bind:value={editForm.description}
            class="rounded-sm bg-background"
            rows={3}
          />
        </div>
        <div class="space-y-1">
          <span class="block text-sm font-medium text-foreground"
            >Visibility</span
          >
          <Select.Root
            type="single"
            value={editForm.visibility}
            onValueChange={(v) => (editForm.visibility = v)}
          >
            <Select.Trigger class="w-full rounded-sm bg-background">
              {@const current = VISIBILITY_OPTIONS.find(
                (o) => o.value === editForm.visibility,
              )}
              {current?.label ?? "Select visibility"}
            </Select.Trigger>
            <Select.Content align="start">
              {#each VISIBILITY_OPTIONS as opt}
                <Select.Item value={opt.value}>{opt.label}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        </div>
        <Button disabled={saving} class="w-fit rounded-xl" onclick={handleSave}>
          <Save size={16} />
          {saving ? "Saving..." : "Save"}
        </Button>
      </div>
    </div>

    <!-- Members (only relevant for private libraries) -->
    {#if editForm.visibility === "private"}
      <div class="bg-card card-soft rounded-2xl p-6">
        <h2 class="font-bold text-lg mb-4 text-foreground">
          Whitelist Members
        </h2>

        <!-- Add member -->
        <div class="flex gap-2 mb-4">
          <Select.Root
            type="single"
            value={addUserId || undefined}
            onValueChange={(v) => (addUserId = v)}
          >
            <Select.Trigger class="flex-1 rounded-xl bg-background">
              {#if addUser}
                {addUser.username}
              {:else}
                Select user to add...
              {/if}
            </Select.Trigger>
            <Select.Content align="start" class="max-h-64">
              {#if nonMembers.length === 0}
                <Select.Item value="__no_users__" disabled
                  >All users are already whitelisted</Select.Item
                >
              {:else}
                {#each nonMembers as user}
                  <Select.Item value={user.id}>{user.username}</Select.Item>
                {/each}
              {/if}
            </Select.Content>
          </Select.Root>
          <Button
            disabled={!addUserId}
            size="icon"
            class="rounded-xl"
            onclick={handleAddMember}
          >
            <UserPlus size={16} />
          </Button>
        </div>

        {#if members.length === 0}
          <p class="text-muted-foreground text-sm">
            No members. Add users to grant access.
          </p>
        {:else}
          <div class="space-y-2">
            {#each members as member}
              {@const user = getUserById(member.user_id)}
              <div
                class="flex items-center justify-between rounded-xl bg-secondary/50 px-4 py-3"
              >
                <div>
                  <p class="text-sm font-medium text-foreground">
                    {user?.username ?? member.user_id}
                  </p>
                  <p class="text-xs text-muted-foreground">
                    Added {new Date(member.granted_at).toLocaleDateString()}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  class="rounded-full text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                  onclick={() => handleRemoveMember(member.user_id)}
                >
                  <Trash2 size={14} />
                </Button>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  {/if}
</div>
