<script lang="ts">
  import { onMount } from "svelte";
  import { bookshelvesApi } from "$lib/api/bookshelves";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import { confirmDialog } from "$lib/stores/confirm";
  import Modal from "$lib/components/Modal.svelte";
  import CollectionCard from "$lib/components/CollectionCard.svelte";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import type { BookshelfOut, ReadingStatus } from "$lib/types";
  import {
    Bookmark,
    BookOpenCheck,
    CircleCheck,
    CircleX,
    EllipsisVertical,
    Heart,
    Pencil,
    Plus,
    ShelvingUnit,
    Trash2,
  } from "@lucide/svelte";
  import { CardListSkeleton } from "$lib/components/skeletons";
  import * as m from "$lib/paraglide/messages.js";

  // Goodreads-style exclusive shelves: reading statuses (plus the favorites
  // flag) pinned as system shelves. Purely a display wrapper over /my-books —
  // the backend has no system-shelf concept.
  const systemShelves: {
    tab: string;
    label: () => string;
    icon: typeof Bookmark;
    query: { status?: ReadingStatus; favorite?: boolean; sort: string };
  }[] = [
    {
      tab: "want_to_read",
      label: m.mybooks_tab_want_to_read,
      icon: Bookmark,
      query: { status: "want_to_read", sort: "updated_at" },
    },
    {
      tab: "currently_reading",
      label: m.mybooks_tab_reading,
      icon: BookOpenCheck,
      query: { status: "currently_reading", sort: "last_read_at" },
    },
    {
      tab: "read",
      label: m.mybooks_tab_read,
      icon: CircleCheck,
      query: { status: "read", sort: "updated_at" },
    },
    {
      tab: "did_not_finish",
      label: m.mybooks_tab_did_not_finish,
      icon: CircleX,
      query: { status: "did_not_finish", sort: "updated_at" },
    },
    {
      tab: "favorites",
      label: m.mybooks_tab_favorites,
      icon: Heart,
      query: { favorite: true, sort: "updated_at" },
    },
  ];

  let systemData = $state<{ count: number; previewIds: string[] }[]>([]);
  let bookshelves = $state<BookshelfOut[]>([]);
  let loading = $state(true);
  let showCreateModal = $state(false);
  let createName = $state("");
  let createDesc = $state("");
  let creating = $state(false);

  onMount(async () => {
    await loadData();
  });

  async function loadData() {
    loading = true;
    try {
      const [system, shelves] = await Promise.all([
        Promise.all(
          systemShelves.map((s) =>
            booksApi.getMyBooks({ ...s.query, limit: 4, offset: 0 }),
          ),
        ),
        bookshelvesApi.list(),
      ]);
      systemData = system.map((r) => ({
        count: r.total,
        previewIds: r.items.filter((b) => b.cover_path).map((b) => b.id),
      }));
      bookshelves = shelves;
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleCreate() {
    if (!createName) return;
    creating = true;
    try {
      const shelf = await bookshelvesApi.create({
        name: createName,
        description: createDesc,
      });
      bookshelves = [
        ...bookshelves,
        { ...shelf, book_count: 0, preview_book_ids: [] },
      ];
      showCreateModal = false;
      createName = "";
      createDesc = "";
      toastStore.success(m.shelves_created());
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      creating = false;
    }
  }

  let editingShelf = $state<BookshelfOut | null>(null);
  let editName = $state("");
  let editDesc = $state("");
  let saving = $state(false);

  function openEdit(shelf: BookshelfOut) {
    editingShelf = shelf;
    editName = shelf.name;
    editDesc = shelf.description ?? "";
  }

  async function handleEditSave() {
    if (!editingShelf || !editName) return;
    saving = true;
    try {
      const updated = await bookshelvesApi.update(editingShelf.id, {
        name: editName,
        description: editDesc,
      });
      bookshelves = bookshelves.map((s) =>
        s.id === updated.id ? { ...s, ...updated } : s,
      );
      editingShelf = null;
      toastStore.success(m.shelves_updated());
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      saving = false;
    }
  }

  async function handleDelete(id: string, name: string) {
    if (
      !(await confirmDialog({
        title: m.shelves_confirm_delete({ name }),
        destructive: true,
      }))
    )
      return;
    try {
      await bookshelvesApi.delete(id);
      bookshelves = bookshelves.filter((s) => s.id !== id);
      toastStore.success(m.shelves_deleted());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>{m.shelves_page_title()}</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6">
  {#if !loading}
    <div class="flex justify-start mb-6">
      <button
        class="flex items-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-medium px-4 sm:px-5 py-2.5 rounded-xl transition-colors whitespace-nowrap text-sm sm:text-base shrink-0"
        onclick={() => (showCreateModal = true)}
      >
        <Plus size={16} />
        {m.shelves_new()}
      </button>
    </div>
  {/if}

  {#if loading}
    <CardListSkeleton count={4} />
  {:else}
    <div class="grid grid-cols-1 gap-5 collection-grid">
      {#each systemShelves as shelf, i}
        <CollectionCard
          href="/my-books?tab={shelf.tab}"
          name={shelf.label()}
          previewBookIds={systemData[i]?.previewIds ?? []}
          bookCount={systemData[i]?.count ?? 0}
        >
          {#snippet icon()}
            <shelf.icon class="text-muted-foreground/50 shrink-0" size={16} />
          {/snippet}
        </CollectionCard>
      {/each}
      {#each bookshelves as shelf}
        <CollectionCard
          href="/bookshelves/{shelf.id}"
          name={shelf.name}
          previewBookIds={shelf.preview_book_ids}
          bookCount={shelf.book_count}
        >
          {#snippet icon()}
            <ShelvingUnit class="text-muted-foreground/50 shrink-0" size={16} />
          {/snippet}
          {#snippet overlay()}
            <!-- Destructive action demoted into a menu — a bare trash can
                 as the card's only visible action invites misclicks. -->
            <DropdownMenu.Root>
              <DropdownMenu.Trigger
                aria-label={m.book_more_actions()}
                class="absolute top-2 right-2 z-10 w-7 h-7 rounded-full bg-black/20 backdrop-blur-sm flex items-center justify-center text-white/70 hover:text-white hover:bg-black/40 can-hover:opacity-0 can-hover:group-hover:opacity-100 transition-all"
              >
                <EllipsisVertical size={14} />
              </DropdownMenu.Trigger>
              <DropdownMenu.Content align="end">
                <DropdownMenu.Item onclick={() => openEdit(shelf)}>
                  <Pencil size={14} />
                  {m.shelves_edit_title()}
                </DropdownMenu.Item>
                <DropdownMenu.Separator />
                <DropdownMenu.Item
                  variant="destructive"
                  onclick={() => handleDelete(shelf.id, shelf.name)}
                >
                  <Trash2 size={14} />
                  {m.common_delete()}
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Root>
          {/snippet}
        </CollectionCard>
      {/each}
    </div>
  {/if}
</div>

<Modal
  title={m.shelves_create_title()}
  open={showCreateModal}
  onclose={() => (showCreateModal = false)}
>
  <div class="space-y-4">
    <div class="space-y-1">
      <label class="block text-sm font-medium text-foreground" for="shelf-name"
        >{m.shelves_name()}</label
      >
      <input
        id="shelf-name"
        bind:value={createName}
        placeholder={m.shelves_name_placeholder()}
        class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
    </div>
    <div class="space-y-1">
      <label class="block text-sm font-medium text-foreground" for="shelf-desc"
        >{m.shelves_description()}</label
      >
      <input
        id="shelf-desc"
        bind:value={createDesc}
        placeholder={m.shelves_description_placeholder()}
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
        {creating ? m.shelves_creating() : m.shelves_create()}
      </button>
    </div>
  </div>
</Modal>

<Modal
  title={m.shelves_edit_title()}
  open={editingShelf != null}
  onclose={() => (editingShelf = null)}
>
  <div class="space-y-4">
    <div class="space-y-1">
      <label
        class="block text-sm font-medium text-foreground"
        for="shelf-edit-name">{m.shelves_name()}</label
      >
      <input
        id="shelf-edit-name"
        bind:value={editName}
        placeholder={m.shelves_name_placeholder()}
        class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
    </div>
    <div class="space-y-1">
      <label
        class="block text-sm font-medium text-foreground"
        for="shelf-edit-desc">{m.shelves_description()}</label
      >
      <input
        id="shelf-edit-desc"
        bind:value={editDesc}
        placeholder={m.shelves_description_placeholder()}
        class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
    </div>
    <div class="flex justify-end gap-2 pt-2">
      <button
        class="px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
        onclick={() => (editingShelf = null)}>{m.common_cancel()}</button
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

<style>
  @media (min-width: 640px) {
    .collection-grid {
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    }
  }
</style>
