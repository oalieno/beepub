<script lang="ts">
  import { onMount } from 'svelte';
  import { authStore } from '$lib/stores/auth';
  import { librariesApi } from '$lib/api/libraries';
  import { bookshelvesApi } from '$lib/api/bookshelves';
  import { toastStore } from '$lib/stores/toast';
  import BookGrid from '$lib/components/BookGrid.svelte';
  import type { BookOut, BookshelfOut, LibraryOut } from '$lib/types';
  import { goto } from '$app/navigation';
  import { BookOpen, Library, BookMarked } from 'lucide-svelte';

  let libraries: LibraryOut[] = [];
  let bookshelves: BookshelfOut[] = [];
  let recentBooks: BookOut[] = [];
  let loading = true;

  onMount(async () => {
    try {
      libraries = await librariesApi.list($authStore.token);
      bookshelves = await bookshelvesApi.list($authStore.token);

      // Gather recent books from all libraries
      const allBooks: BookOut[] = [];
      await Promise.all(
        libraries.map(async (lib) => {
          try {
            const books = await librariesApi.getBooks(lib.id, $authStore.token!);
            allBooks.push(...books);
          } catch {
            // skip
          }
        })
      );
      allBooks.sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      );
      recentBooks = allBooks.slice(0, 12);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  });
</script>

<svelte:head>
  <title>BeePub - Home</title>
</svelte:head>

<div class="max-w-7xl mx-auto px-4 py-8">
  {#if loading}
    <div class="flex items-center justify-center h-64">
      <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-amber-500"></div>
    </div>
  {:else}
    <!-- Stats -->
    <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-10">
      <div class="bg-gray-800 rounded-lg p-6 flex items-center gap-4">
        <Library class="text-amber-500" size={32} />
        <div>
          <p class="text-gray-400 text-sm">Libraries</p>
          <p class="text-2xl font-bold">{libraries.length}</p>
        </div>
      </div>
      <div class="bg-gray-800 rounded-lg p-6 flex items-center gap-4">
        <BookOpen class="text-amber-500" size={32} />
        <div>
          <p class="text-gray-400 text-sm">Total Books</p>
          <p class="text-2xl font-bold">{recentBooks.length > 0 ? recentBooks.length + '+' : 0}</p>
        </div>
      </div>
      <div class="bg-gray-800 rounded-lg p-6 flex items-center gap-4">
        <BookMarked class="text-amber-500" size={32} />
        <div>
          <p class="text-gray-400 text-sm">Bookshelves</p>
          <p class="text-2xl font-bold">{bookshelves.length}</p>
        </div>
      </div>
    </div>

    <!-- Recent Books -->
    <section class="mb-10">
      <h2 class="text-2xl font-bold mb-4">Recently Added</h2>
      {#if recentBooks.length === 0}
        <p class="text-gray-400">No books yet. Upload some books to get started.</p>
      {:else}
        <BookGrid books={recentBooks} />
      {/if}
    </section>

    <!-- Bookshelves -->
    <section>
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-2xl font-bold">My Bookshelves</h2>
        <a href="/bookshelves" class="text-amber-500 hover:text-amber-400 text-sm">View all</a>
      </div>
      {#if bookshelves.length === 0}
        <p class="text-gray-400">No bookshelves yet.</p>
      {:else}
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {#each bookshelves.slice(0, 6) as shelf}
            <a
              href="/bookshelves/{shelf.id}"
              class="bg-gray-800 rounded-lg p-4 hover:bg-gray-700 transition-colors"
            >
              <h3 class="font-semibold text-lg">{shelf.name}</h3>
              {#if shelf.description}
                <p class="text-gray-400 text-sm mt-1 line-clamp-2">{shelf.description}</p>
              {/if}
            </a>
          {/each}
        </div>
      {/if}
    </section>
  {/if}
</div>
