<script lang="ts">
  import { onMount } from "svelte";
  import { bookshelvesApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import Modal from "$lib/components/Modal.svelte";
  import CollectionCard from "$lib/components/CollectionCard.svelte";
  import type { BookshelfOut } from "$lib/types";
  import { Plus, ShelvingUnit, Trash2 } from "@lucide/svelte";
  import { CardListSkeleton } from "$lib/components/skeletons";
  import * as m from "$lib/paraglide/messages.js";

  let bookshelves = $state<BookshelfOut[]>([]);
  let loading = $state(true);
  let showCreateModal = $state(false);
  let createName = $state("");
  let createDesc = $state("");
  let creating = $state(false);
  let isPublic = $state(false);

  onMount(async () => {
    await loadData();
  });

  async function loadData() {
    loading = true;
    try {
      bookshelves = await bookshelvesApi.list();
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
        is_public: isPublic,
      });
      bookshelves = [
        ...bookshelves,
        { ...shelf, book_count: 0, preview_book_ids: [] },
      ];
      showCreateModal = false;
      createName = "";
      createDesc = "";
      isPublic = false;
      toastStore.success(m.shelves_created());
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      creating = false;
    }
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(m.shelves_confirm_delete({ name }))) return;
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
  {#if !loading && bookshelves.length > 0}
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
  {:else if bookshelves.length === 0}
    <div class="flex flex-col items-center justify-center py-24 text-center">
      <div class="mb-4 p-3 bg-primary/10 rounded-xl">
        <ShelvingUnit class="text-primary/50" size={28} />
      </div>
      <p class="text-foreground text-lg font-medium mb-2">
        {m.shelves_no_shelves()}
      </p>
      <p class="text-muted-foreground text-sm max-w-xs mb-6">
        {m.shelves_empty_description()}
      </p>
      <button
        class="flex items-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-medium px-5 py-2.5 rounded-xl transition-colors text-sm"
        onclick={() => (showCreateModal = true)}
      >
        <Plus size={16} />
        {m.shelves_create_shelf()}
      </button>
    </div>
  {:else}
    <div class="grid grid-cols-1 gap-5 collection-grid">
      {#each bookshelves as shelf}
        <CollectionCard
          href="/bookshelves/{shelf.id}"
          name={shelf.name}
          previewBookIds={shelf.preview_book_ids}
          bookCount={shelf.book_count}
          badgeLabel={shelf.is_public
            ? m.shelves_public()
            : m.shelves_private()}
          badgeClass={shelf.is_public
            ? "bg-primary/15 text-primary"
            : "bg-secondary text-muted-foreground"}
        >
          {#snippet icon()}
            <ShelvingUnit class="text-muted-foreground/50 shrink-0" size={16} />
          {/snippet}
          {#snippet overlay()}
            <button
              class="absolute top-2 right-2 z-10 w-7 h-7 rounded-full bg-black/20 backdrop-blur-sm flex items-center justify-center text-white/70 hover:text-white hover:bg-red-500/80 sm:opacity-0 sm:group-hover:opacity-100 transition-all"
              onclick={() => handleDelete(shelf.id, shelf.name)}
            >
              <Trash2 size={13} />
            </button>
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
    <label class="flex items-center gap-2 cursor-pointer">
      <input type="checkbox" bind:checked={isPublic} class="accent-primary" />
      <span class="text-sm text-foreground">{m.shelves_make_public()}</span>
    </label>
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
        {creating ? "Creating..." : "Create"}
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
