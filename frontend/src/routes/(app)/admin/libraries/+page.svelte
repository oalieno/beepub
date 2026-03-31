<script lang="ts">
  import { onMount } from "svelte";
  import { librariesApi } from "$lib/api/libraries";
  import { toastStore } from "$lib/stores/toast";
  import Modal from "$lib/components/Modal.svelte";
  import { Input } from "$lib/components/ui/input";
  import { Textarea } from "$lib/components/ui/textarea";
  import { Button } from "$lib/components/ui/button";
  import * as Select from "$lib/components/ui/select";
  import type { LibraryOut } from "$lib/types";
  import { LibraryVisibility } from "$lib/types";
  import {
    Plus,
    Trash2,
    Lock,
    Globe,
    Settings,
    HardDrive,
  } from "@lucide/svelte";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import BackButton from "$lib/components/BackButton.svelte";

  let libraries = $state<LibraryOut[]>([]);
  let loading = $state(true);
  let showCreateModal = $state(false);
  let createForm = $state({
    name: "",
    description: "",
    visibility: LibraryVisibility.Public as string,
  });
  let creating = $state(false);

  const VISIBILITY_OPTIONS = [
    { value: LibraryVisibility.Public, label: "Public" },
    { value: LibraryVisibility.Private, label: "Private (whitelist)" },
  ];

  onMount(async () => {
    await loadData();
  });

  async function loadData() {
    loading = true;
    try {
      libraries = await librariesApi.list();
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleCreate() {
    if (!createForm.name) return;
    creating = true;
    try {
      const lib = await librariesApi.create(createForm);
      libraries = [...libraries, lib];
      showCreateModal = false;
      createForm = {
        name: "",
        description: "",
        visibility: LibraryVisibility.Public,
      };
      toastStore.success("Library created");
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      creating = false;
    }
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`Delete library "${name}"?`)) return;
    try {
      await librariesApi.delete(id);
      libraries = libraries.filter((l) => l.id !== id);
      toastStore.success("Library deleted");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>Libraries - Admin - BeePub</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
  <div class="flex items-end justify-between mb-8">
    <div>
      <div class="mb-1">
        <BackButton href="/admin" label="Admin" />
      </div>
      <h1 class="text-3xl font-bold text-foreground">Libraries</h1>
      <p class="text-muted-foreground mt-1">
        Manage libraries, visibility, and access
      </p>
    </div>
    <Button class="rounded-xl" onclick={() => (showCreateModal = true)}>
      <Plus size={16} />
      New Library
    </Button>
  </div>

  {#if loading}
    <div role="status" aria-label="Loading" class="space-y-3">
      {#each Array(6) as _}
        <div
          class="bg-card card-soft rounded-2xl p-5 flex items-center justify-between"
        >
          <div class="flex items-center gap-3.5">
            <Skeleton class="w-10 h-10 rounded-xl shrink-0" />
            <div class="flex items-center gap-2">
              <Skeleton class="h-5 w-28" />
              <Skeleton class="h-5 w-16 rounded-full" />
            </div>
          </div>
          <div class="flex items-center gap-2">
            <Skeleton class="w-8 h-8 rounded-full" />
            <Skeleton class="w-8 h-8 rounded-full" />
          </div>
        </div>
      {/each}
    </div>
  {:else if libraries.length === 0}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      <p class="text-muted-foreground text-lg">No libraries yet</p>
      <p class="text-muted-foreground/70 text-sm mt-1">
        Create one to get started.
      </p>
    </div>
  {:else}
    <div class="space-y-3">
      {#each libraries as lib}
        <div
          class="bg-card card-soft rounded-2xl p-5 flex items-center justify-between group hover:shadow-md transition-all duration-200"
        >
          <div class="flex items-center gap-3.5">
            <div
              class="w-10 h-10 rounded-xl flex-shrink-0 flex items-center justify-center {lib.visibility ===
              LibraryVisibility.Private
                ? 'bg-secondary text-muted-foreground'
                : 'bg-primary/15 text-primary'}"
            >
              {#if lib.visibility === LibraryVisibility.Private}
                <Lock size={18} />
              {:else}
                <Globe size={18} />
              {/if}
            </div>
            <div>
              <p class="font-semibold text-foreground">
                {lib.name}
                {#if lib.calibre_path}
                  <span
                    class="ml-2 text-xs bg-amber-500/15 text-amber-600 px-2 py-0.5 rounded-full inline-flex items-center gap-1"
                  >
                    <HardDrive size={10} />
                    Calibre
                  </span>
                {/if}
              </p>
              {#if lib.description}
                <p class="text-muted-foreground text-sm">{lib.description}</p>
              {/if}
            </div>
          </div>
          <div class="flex items-center gap-1.5">
            <a
              href="/admin/libraries/{lib.id}"
              class="w-8 h-8 rounded-full bg-secondary flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
              title="Manage"
            >
              <Settings size={14} />
            </a>
            <button
              class="w-8 h-8 rounded-full bg-secondary/50 flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
              onclick={() => handleDelete(lib.id, lib.name)}
              title="Delete"
            >
              <Trash2 size={14} />
            </button>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

<Modal
  title="Create Library"
  open={showCreateModal}
  onclose={() => (showCreateModal = false)}
>
  <div class="space-y-4">
    <div class="space-y-1">
      <label class="block text-sm font-medium text-foreground" for="lib-name"
        >Name</label
      >
      <Input id="lib-name" bind:value={createForm.name} class="rounded-xl" />
    </div>
    <div class="space-y-1">
      <label class="block text-sm font-medium text-foreground" for="lib-desc"
        >Description</label
      >
      <Textarea
        id="lib-desc"
        bind:value={createForm.description}
        class="rounded-xl bg-background"
        rows={3}
      />
    </div>
    <div class="space-y-1">
      <span class="block text-sm font-medium text-foreground">Visibility</span>
      <Select.Root
        type="single"
        value={createForm.visibility}
        onValueChange={(v) => (createForm.visibility = v)}
      >
        <Select.Trigger class="w-full rounded-xl bg-background">
          {@const current = VISIBILITY_OPTIONS.find(
            (o) => o.value === createForm.visibility,
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
    <div class="flex justify-end gap-2 pt-2">
      <Button
        variant="ghost"
        class="rounded-xl"
        onclick={() => (showCreateModal = false)}>Cancel</Button
      >
      <Button
        disabled={!createForm.name || creating}
        class="rounded-xl"
        onclick={handleCreate}
      >
        {creating ? "Creating..." : "Create"}
      </Button>
    </div>
  </div>
</Modal>
