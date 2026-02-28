<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import { bookshelvesApi } from '$lib/api/bookshelves';
  import { librariesApi } from '$lib/api/libraries';
  import { toastStore } from '$lib/stores/toast';
  import BookGrid from '$lib/components/BookGrid.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import type { BookshelfOut, BookOut, LibraryOut } from '$lib/types';
  import { Plus } from 'lucide-svelte';

  $: shelfId = $page.params.id;

  let shelf: BookshelfOut | null = null;
  let books: BookOut[] = [];
  let loading = true;
  let showAddModal = false;
  let allBooks: BookOut[] = [];
  let addSearchQuery = '';

  $: filteredAddBooks = addSearchQuery
    ? allBooks.filter(b => (b.display_title ?? '').toLowerCase().includes(addSearchQuery.toLowerCase()))
    : allBooks;

  onMount(async () => {
    if (!$authStore.token) { goto('/login'); return; }
    await loadData();
  });

  async function loadData() {
    loading = true;
    try {
      const [s, b] = await Promise.all([
        bookshelvesApi.get(shelfId, $authStore.token!),
        bookshelvesApi.getBooks(shelfId, $authStore.token!),
      ]);
      shelf = s;
      books = b;
      // Load all books for the "Add Books" modal
      allBooks = await import('$lib/api/books').then(m => m.booksApi.search('', $authStore.token!)).catch(() => []);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function addBook(bookId: string) {
    if (!$authStore.token) return;
    try {
      await bookshelvesApi.addBook(shelfId, bookId, $authStore.token);
      toastStore.success('Book added to shelf');
      showAddModal = false;
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function removeBook(bookId: string) {
    if (!$authStore.token) return;
    try {
      await bookshelvesApi.removeBook(shelfId, bookId, $authStore.token);
      books = books.filter(b => b.id !== bookId);
      toastStore.success('Book removed from shelf');
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>{shelf?.name ?? 'Bookshelf'} - BeePub</title>
</svelte:head>

<div class="max-w-7xl mx-auto px-4 py-8">
  {#if loading}
    <div class="flex items-center justify-center h-64">
      <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-amber-500"></div>
    </div>
  {:else if shelf}
    <div class="flex items-start justify-between mb-8">
      <div>
        <h1 class="text-3xl font-bold">{shelf.name}</h1>
        {#if shelf.description}
          <p class="text-gray-400 mt-1">{shelf.description}</p>
        {/if}
      </div>
      <button
        class="flex items-center gap-2 bg-amber-500 hover:bg-amber-600 text-gray-900 font-semibold px-4 py-2 rounded-lg"
        on:click={() => (showAddModal = true)}
      >
        <Plus size={16} />
        Add Books
      </button>
    </div>

    {#if books.length === 0}
      <div class="text-center py-16 text-gray-500">
        <p>No books in this shelf yet. Add some!</p>
      </div>
    {:else}
      <BookGrid {books} />
    {/if}
  {/if}
</div>

<Modal title="Add Books to Shelf" open={showAddModal} on:close={() => (showAddModal = false)}>
  <div class="space-y-3">
    <input
      bind:value={addSearchQuery}
      placeholder="Search books..."
      class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-500"
    />
    <div class="max-h-80 overflow-y-auto space-y-2">
      {#each filteredAddBooks as book}
        <button
          class="w-full text-left px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg flex items-center gap-3"
          on:click={() => addBook(book.id)}
        >
          {#if book.cover_path}
            <img src="/covers/{book.id}.jpg" alt="" class="w-8 h-12 object-cover rounded" />
          {:else}
            <div class="w-8 h-12 bg-gray-600 rounded flex items-center justify-center text-gray-400 text-xs">No cover</div>
          {/if}
          <div class="min-w-0">
            <p class="font-medium truncate">{book.display_title ?? 'Untitled'}</p>
            <p class="text-gray-400 text-xs truncate">{(book.display_authors ?? []).join(', ')}</p>
          </div>
        </button>
      {/each}
    </div>
  </div>
</Modal>
