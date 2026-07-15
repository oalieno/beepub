<script lang="ts">
  import { onMount } from "svelte";
  import { isNative } from "$lib/platform";
  import { authStore } from "$lib/stores/auth";
  import { librariesApi } from "$lib/api/libraries";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import { confirmDialog } from "$lib/stores/confirm";
  import Modal from "$lib/components/Modal.svelte";
  import CollectionCard from "$lib/components/CollectionCard.svelte";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import type { LibraryOut } from "$lib/types";
  import { UserRole } from "$lib/types";
  import {
    Cloud,
    EllipsisVertical,
    HardDrive,
    Library,
    Pencil,
    Plus,
    Trash2,
  } from "@lucide/svelte";
  import { CardListSkeleton } from "$lib/components/skeletons";
  import * as m from "$lib/paraglide/messages.js";

  let libraries = $state<LibraryOut[]>([]);
  let allBooks = $state<{ count: number; previewIds: string[] }>({
    count: 0,
    previewIds: [],
  });
  // null = not native (card hidden).
  let device = $state<{ count: number; previewSrcs: string[] } | null>(null);
  let loading = $state(true);

  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);

  onMount(loadData);

  async function loadData() {
    loading = true;
    try {
      const [libs, all] = await Promise.all([
        librariesApi.list(),
        booksApi.getAll({
          limit: 4,
          offset: 0,
          sort: "added_at",
          order: "desc",
        }),
      ]);
      libraries = libs;
      allBooks = {
        count: all.total,
        previewIds: all.items.filter((b) => b.cover_path).map((b) => b.id),
      };
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
    if (isNative()) {
      try {
        const { listLocalBooks, getLocalCoverSrc } =
          await import("$lib/services/localLibrary");
        const books = await listLocalBooks();
        const newest = books
          .filter((b) => b.coverPath)
          .sort((a, b) => b.importedAt.localeCompare(a.importedAt))
          .slice(0, 4);
        // Cover URIs go stale across app restarts — always re-derived here.
        const srcs = await Promise.all(newest.map(getLocalCoverSrc));
        device = {
          count: books.length,
          previewSrcs: srcs.filter((s): s is string => !!s),
        };
      } catch {
        device = { count: 0, previewSrcs: [] };
      }
    }
  }

  let showCreateModal = $state(false);
  let createName = $state("");
  let createDesc = $state("");
  let creating = $state(false);

  async function handleCreate() {
    if (!createName) return;
    creating = true;
    try {
      const lib = await librariesApi.create({
        name: createName,
        description: createDesc || undefined,
      });
      libraries = [
        ...libraries,
        { ...lib, book_count: 0, preview_book_ids: [] },
      ];
      showCreateModal = false;
      createName = "";
      createDesc = "";
      toastStore.success(m.library_created());
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      creating = false;
    }
  }

  let editingLibrary = $state<LibraryOut | null>(null);
  let editName = $state("");
  let editDesc = $state("");
  let saving = $state(false);

  function openEdit(lib: LibraryOut) {
    editingLibrary = lib;
    editName = lib.name;
    editDesc = lib.description ?? "";
  }

  async function handleEditSave() {
    if (!editingLibrary || !editName) return;
    saving = true;
    try {
      const updated = await librariesApi.update(editingLibrary.id, {
        name: editName,
        description: editDesc,
      });
      libraries = libraries.map((l) =>
        l.id === updated.id ? { ...l, ...updated } : l,
      );
      editingLibrary = null;
      toastStore.success(m.library_updated());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
    saving = false;
  }

  async function handleDelete(lib: LibraryOut) {
    if (
      !(await confirmDialog({
        title: m.library_delete_confirm({ name: lib.name }),
        description: m.library_delete_warning({
          count: String(lib.book_count ?? 0),
        }),
        destructive: true,
      }))
    )
      return;
    try {
      await librariesApi.delete(lib.id);
      libraries = libraries.filter((l) => l.id !== lib.id);
      toastStore.success(m.library_deleted());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>{m.libraries_page_title()}</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6">
  {#if !loading && isAdmin}
    <div class="flex justify-start mb-6">
      <button
        class="flex items-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-medium px-4 sm:px-5 py-2.5 rounded-xl transition-colors whitespace-nowrap text-sm sm:text-base shrink-0"
        onclick={() => (showCreateModal = true)}
      >
        <Plus size={16} />
        {m.library_new()}
      </button>
    </div>
  {/if}

  {#if loading}
    <CardListSkeleton count={4} />
  {:else}
    <div class="grid grid-cols-1 gap-5 collection-grid">
      {#if device}
        <CollectionCard
          href="/local"
          name={m.libraries_this_device()}
          previewSrcs={device.previewSrcs}
          bookCount={device.count}
        >
          {#snippet icon()}
            <HardDrive class="text-muted-foreground/50 shrink-0" size={16} />
          {/snippet}
        </CollectionCard>
      {/if}
      {#if libraries.length > 0}
        <CollectionCard
          href="/libraries/all"
          name={isNative() ? m.libraries_cloud_books() : m.allbooks_heading()}
          previewBookIds={allBooks.previewIds}
          bookCount={allBooks.count}
        >
          {#snippet icon()}
            {#if isNative()}
              <Cloud class="text-muted-foreground/50 shrink-0" size={16} />
            {:else}
              <Library class="text-muted-foreground/50 shrink-0" size={16} />
            {/if}
          {/snippet}
        </CollectionCard>
      {/if}
      {#each libraries as lib (lib.id)}
        <CollectionCard
          href="/libraries/{lib.id}"
          name={lib.name}
          previewBookIds={lib.preview_book_ids ?? []}
          bookCount={lib.book_count ?? 0}
          badgeLabel={lib.calibre_path ? m.library_calibre_badge() : undefined}
          badgeClass="bg-amber-500/15 text-amber-600"
        >
          {#snippet icon()}
            <!-- On native the page contrasts cloud vs device, so every
                 server library carries the cloud mark. -->
            {#if isNative()}
              <Cloud class="text-muted-foreground/50 shrink-0" size={16} />
            {:else}
              <Library class="text-muted-foreground/50 shrink-0" size={16} />
            {/if}
          {/snippet}
          {#snippet overlay()}
            {#if isAdmin}
              <DropdownMenu.Root>
                <DropdownMenu.Trigger
                  aria-label={m.book_more_actions()}
                  class="absolute top-2 right-2 z-10 w-7 h-7 rounded-full bg-black/20 backdrop-blur-sm flex items-center justify-center text-white/70 hover:text-white hover:bg-black/40 can-hover:opacity-0 can-hover:group-hover:opacity-100 data-[state=open]:opacity-100 transition-all"
                >
                  <EllipsisVertical size={14} />
                </DropdownMenu.Trigger>
                <DropdownMenu.Content align="end">
                  <DropdownMenu.Item onclick={() => openEdit(lib)}>
                    <Pencil size={14} />
                    {m.library_edit_title()}
                  </DropdownMenu.Item>
                  <DropdownMenu.Separator />
                  <DropdownMenu.Item
                    variant="destructive"
                    onclick={() => handleDelete(lib)}
                  >
                    <Trash2 size={14} />
                    {m.common_delete()}
                  </DropdownMenu.Item>
                </DropdownMenu.Content>
              </DropdownMenu.Root>
            {/if}
          {/snippet}
        </CollectionCard>
      {/each}
    </div>

    {#if libraries.length === 0 && !isAdmin}
      <div class="text-center py-16">
        <Library class="mx-auto text-muted-foreground/30 mb-4" size={48} />
        <p class="text-foreground font-medium">{m.libraries_empty()}</p>
        <p class="text-muted-foreground text-sm mt-1">
          {m.libraries_empty_subtitle()}
        </p>
      </div>
    {/if}
  {/if}
</div>

<Modal
  title={m.library_create_title()}
  open={showCreateModal}
  onclose={() => (showCreateModal = false)}
>
  <div class="space-y-4">
    <div class="space-y-1">
      <label class="block text-sm font-medium text-foreground" for="lib-name"
        >{m.library_name()}</label
      >
      <input
        id="lib-name"
        bind:value={createName}
        placeholder={m.library_name_placeholder()}
        class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
    </div>
    <div class="space-y-1">
      <label class="block text-sm font-medium text-foreground" for="lib-desc"
        >{m.library_description()}</label
      >
      <input
        id="lib-desc"
        bind:value={createDesc}
        placeholder={m.library_description_placeholder()}
        class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
    </div>
    <div class="flex justify-end gap-2 pt-2">
      <button
        class="px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
        onclick={() => (showCreateModal = false)}>{m.common_cancel()}</button
      >
      <button
        disabled={!createName || creating}
        class="px-5 py-2.5 text-sm bg-primary hover:bg-primary/90 disabled:opacity-50 text-primary-foreground font-semibold rounded-xl"
        onclick={handleCreate}
      >
        {creating ? m.library_creating() : m.library_create_title()}
      </button>
    </div>
  </div>
</Modal>

<Modal
  title={m.library_edit_title()}
  open={editingLibrary != null}
  onclose={() => (editingLibrary = null)}
>
  <div class="space-y-4">
    <div class="space-y-1">
      <label
        class="block text-sm font-medium text-foreground"
        for="lib-edit-name">{m.library_name()}</label
      >
      <input
        id="lib-edit-name"
        bind:value={editName}
        placeholder={m.library_name_placeholder()}
        class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
    </div>
    <div class="space-y-1">
      <label
        class="block text-sm font-medium text-foreground"
        for="lib-edit-desc">{m.library_description()}</label
      >
      <input
        id="lib-edit-desc"
        bind:value={editDesc}
        placeholder={m.library_description_placeholder()}
        class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
    </div>
    <div class="flex justify-end gap-2 pt-2">
      <button
        class="px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
        onclick={() => (editingLibrary = null)}>{m.common_cancel()}</button
      >
      <button
        disabled={!editName || saving}
        class="px-5 py-2.5 text-sm bg-primary hover:bg-primary/90 disabled:opacity-50 text-primary-foreground font-semibold rounded-xl"
        onclick={handleEditSave}
      >
        {m.common_save()}
      </button>
    </div>
  </div>
</Modal>
