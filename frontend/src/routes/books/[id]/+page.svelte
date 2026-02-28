<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import { booksApi } from '$lib/api/books';
  import { bookshelvesApi } from '$lib/api/bookshelves';
  import { toastStore } from '$lib/stores/toast';
  import StarRating from '$lib/components/StarRating.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import type { BookOut, ExternalMetadataOut, BookshelfOut, InteractionOut } from '$lib/types';
  import { UserRole } from '$lib/types';
  import { Heart, BookOpen, Trash2, Edit, RefreshCw, BookMarked, ExternalLink } from 'lucide-svelte';

  $: bookId = $page.params.id;

  let book: BookOut | null = null;
  let interaction: InteractionOut | null = null;
  let externalMeta: ExternalMetadataOut[] = [];
  let bookshelves: BookshelfOut[] = [];
  let loading = true;
  let showEditModal = false;
  let showAddToShelf = false;
  let editForm = { title: '', authors: '', description: '', publisher: '', published_date: '' };

  $: isAdmin = $authStore.user?.role === UserRole.Admin;

  onMount(async () => {
    if (!$authStore.token) { goto('/login'); return; }
    await loadData();
  });

  async function loadData() {
    loading = true;
    try {
      const [b, ext, shelves] = await Promise.all([
        booksApi.get(bookId, $authStore.token!),
        booksApi.getExternal(bookId, $authStore.token!).catch(() => [] as ExternalMetadataOut[]),
        bookshelvesApi.list($authStore.token!),
      ]);
      book = b;
      externalMeta = ext;
      bookshelves = shelves;
      if (book) {
        editForm = {
          title: book.display_title ?? '',
          authors: (book.display_authors ?? []).join(', '),
          description: book.description ?? '',
          publisher: book.publisher ?? '',
          published_date: book.published_date ?? '',
        };
      }
      // Load user interaction (rating, favorite, progress)
      try {
        interaction = await booksApi.getInteraction(bookId, $authStore.token!);
      } catch {
        // ignore
      }
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleRating(e: CustomEvent<number | null>) {
    if (!book || !$authStore.token) return;
    try {
      await booksApi.updateRating(bookId, e.detail, $authStore.token);
      if (interaction) interaction = { ...interaction, rating: e.detail };
      else interaction = { rating: e.detail, is_favorite: false, reading_progress: null, updated_at: '' };
      toastStore.success('Rating updated');
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function toggleFavorite() {
    if (!book || !$authStore.token) return;
    const newVal = !interaction?.is_favorite;
    try {
      await booksApi.updateFavorite(bookId, newVal, $authStore.token);
      if (interaction) interaction = { ...interaction, is_favorite: newVal };
      else interaction = { rating: null, is_favorite: newVal, reading_progress: null, updated_at: '' };
      toastStore.success(newVal ? 'Added to favorites' : 'Removed from favorites');
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleSaveEdit() {
    if (!book || !$authStore.token) return;
    try {
      const updated = await booksApi.updateMetadata(bookId, {
        title: editForm.title || null,
        authors: editForm.authors.split(',').map(a => a.trim()).filter(Boolean),
        description: editForm.description || null,
        publisher: editForm.publisher || null,
        published_date: editForm.published_date || null,
      }, $authStore.token);
      book = updated;
      showEditModal = false;
      toastStore.success('Metadata updated');
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleDelete() {
    if (!confirm('Delete this book permanently?') || !$authStore.token) return;
    try {
      await booksApi.delete(bookId, $authStore.token);
      toastStore.success('Book deleted');
      history.back();
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleRefreshMeta() {
    if (!$authStore.token) return;
    try {
      await booksApi.refreshMetadata(bookId, $authStore.token);
      toastStore.success('Metadata refresh queued');
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function addToShelf(shelfId: string) {
    if (!$authStore.token) return;
    try {
      await bookshelvesApi.addBook(shelfId, bookId, $authStore.token);
      toastStore.success('Added to bookshelf');
      showAddToShelf = false;
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>{book?.display_title ?? 'Book'} - BeePub</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-4 py-8">
  {#if loading}
    <div class="flex items-center justify-center h-64">
      <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-amber-500"></div>
    </div>
  {:else if book}
    <div class="flex flex-col md:flex-row gap-8">
      <!-- Cover -->
      <div class="flex-shrink-0 w-48 mx-auto md:mx-0">
        <div class="aspect-[2/3] bg-gray-800 rounded-lg overflow-hidden shadow-xl">
          {#if book.cover_path}
            <img src="/covers/{book.id}.jpg" alt="{book.display_title} cover" class="w-full h-full object-cover" />
          {:else}
            <div class="w-full h-full flex items-center justify-center">
              <BookOpen class="text-gray-600" size={48} />
            </div>
          {/if}
        </div>

        <!-- Actions -->
        <div class="mt-4 flex flex-col gap-2">
          <a
            href="/books/{book.id}/read"
            class="flex items-center justify-center gap-2 bg-amber-500 hover:bg-amber-600 text-gray-900 font-semibold px-4 py-2.5 rounded-lg transition-colors"
          >
            <BookOpen size={16} />
            Read
          </a>
          <button
            class="flex items-center justify-center gap-2 border border-gray-700 hover:border-gray-600 text-gray-300 hover:text-white px-4 py-2.5 rounded-lg transition-colors"
            on:click={toggleFavorite}
          >
            <Heart size={16} class="{interaction?.is_favorite ? 'fill-red-500 text-red-500' : ''}" />
            {interaction?.is_favorite ? 'Unfavorite' : 'Favorite'}
          </button>
          <button
            class="flex items-center justify-center gap-2 border border-gray-700 hover:border-gray-600 text-gray-300 hover:text-white px-4 py-2.5 rounded-lg transition-colors"
            on:click={() => (showAddToShelf = true)}
          >
            <BookMarked size={16} />
            Add to Shelf
          </button>
        </div>
      </div>

      <!-- Details -->
      <div class="flex-1 min-w-0">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h1 class="text-3xl font-bold leading-tight">{book.display_title ?? 'Untitled'}</h1>
            {#if (book.display_authors ?? []).length > 0}
              <p class="text-gray-400 text-lg mt-1">{(book.display_authors ?? []).join(', ')}</p>
            {/if}
          </div>
          {#if isAdmin}
            <div class="flex items-center gap-2 flex-shrink-0">
              <button class="p-2 text-gray-400 hover:text-white" on:click={() => (showEditModal = true)} title="Edit metadata">
                <Edit size={18} />
              </button>
              <button class="p-2 text-gray-400 hover:text-white" on:click={handleRefreshMeta} title="Refresh metadata">
                <RefreshCw size={18} />
              </button>
              <button class="p-2 text-red-400 hover:text-red-300" on:click={handleDelete} title="Delete book">
                <Trash2 size={18} />
              </button>
            </div>
          {/if}
        </div>

        <!-- Rating -->
        <div class="mt-4">
          <p class="text-sm text-gray-500 mb-1">Your rating</p>
          <StarRating value={interaction?.rating ?? null} on:change={handleRating} />
        </div>

        <!-- Metadata -->
        <div class="mt-4 grid grid-cols-2 gap-2 text-sm">
          {#if book.publisher ?? book.epub_publisher}
            <div><span class="text-gray-500">Publisher:</span> <span class="text-gray-300">{book.publisher ?? book.epub_publisher}</span></div>
          {/if}
          {#if book.published_date ?? book.epub_published_date}
            <div><span class="text-gray-500">Published:</span> <span class="text-gray-300">{book.published_date ?? book.epub_published_date}</span></div>
          {/if}
          {#if book.epub_language}
            <div><span class="text-gray-500">Language:</span> <span class="text-gray-300">{book.epub_language}</span></div>
          {/if}
          {#if book.epub_isbn}
            <div><span class="text-gray-500">ISBN:</span> <span class="text-gray-300">{book.epub_isbn}</span></div>
          {/if}
        </div>

        <!-- Description -->
        {#if book.description ?? book.epub_description}
          <div class="mt-6">
            <h2 class="text-lg font-semibold mb-2">Description</h2>
            <p class="text-gray-400 leading-relaxed">{book.description ?? book.epub_description}</p>
          </div>
        {/if}

        <!-- External metadata -->
        {#if externalMeta.length > 0}
          <div class="mt-6">
            <h2 class="text-lg font-semibold mb-3">External Ratings</h2>
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {#each externalMeta as meta}
                <div class="bg-gray-800 rounded-lg p-3">
                  <p class="text-sm font-medium capitalize mb-1">{meta.source.replace('_', ' ')}</p>
                  {#if meta.rating !== null}
                    <p class="text-amber-500 text-lg font-bold">{meta.rating?.toFixed(1)}</p>
                  {:else}
                    <p class="text-gray-500 text-sm">No rating</p>
                  {/if}
                  {#if meta.rating_count !== null}
                    <p class="text-gray-500 text-xs">{meta.rating_count?.toLocaleString()} ratings</p>
                  {/if}
                  {#if meta.source_url}
                    <a href={meta.source_url} target="_blank" rel="noopener" class="text-xs text-amber-500 hover:underline flex items-center gap-1 mt-1">
                      View <ExternalLink size={10} />
                    </a>
                  {/if}
                </div>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    </div>
  {/if}
</div>

<!-- Edit Modal -->
{#if book}
  <Modal title="Edit Metadata" open={showEditModal} on:close={() => (showEditModal = false)}>
    <div class="space-y-4">
      <div>
        <label class="block text-sm font-medium text-gray-300 mb-1">Title</label>
        <input bind:value={editForm.title} class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-500" />
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-300 mb-1">Authors (comma-separated)</label>
        <input bind:value={editForm.authors} class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-500" />
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-300 mb-1">Publisher</label>
        <input bind:value={editForm.publisher} class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-500" />
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-300 mb-1">Published Date</label>
        <input bind:value={editForm.published_date} class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-500" />
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-300 mb-1">Description</label>
        <textarea bind:value={editForm.description} rows={4} class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-500 resize-none"></textarea>
      </div>
      <div class="flex justify-end gap-2 pt-2">
        <button class="px-4 py-2 text-sm text-gray-400 hover:text-white" on:click={() => (showEditModal = false)}>Cancel</button>
        <button class="px-4 py-2 text-sm bg-amber-500 hover:bg-amber-600 text-gray-900 font-semibold rounded-lg" on:click={handleSaveEdit}>Save</button>
      </div>
    </div>
  </Modal>

  <Modal title="Add to Bookshelf" open={showAddToShelf} on:close={() => (showAddToShelf = false)}>
    <div class="space-y-2">
      {#if bookshelves.length === 0}
        <p class="text-gray-400 text-sm">No bookshelves yet. <a href="/bookshelves" class="text-amber-500">Create one</a>.</p>
      {:else}
        {#each bookshelves as shelf}
          <button
            class="w-full text-left px-4 py-3 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
            on:click={() => addToShelf(shelf.id)}
          >
            <p class="font-medium">{shelf.name}</p>
            {#if shelf.description}
              <p class="text-gray-400 text-xs mt-0.5">{shelf.description}</p>
            {/if}
          </button>
        {/each}
      {/if}
    </div>
  </Modal>
{/if}
