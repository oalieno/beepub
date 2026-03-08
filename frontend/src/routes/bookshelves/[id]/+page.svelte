<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/stores";
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { bookshelvesApi } from "$lib/api/bookshelves";
  import { librariesApi } from "$lib/api/libraries";
  import { toastStore } from "$lib/stores/toast";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import Modal from "$lib/components/Modal.svelte";
  import type { BookshelfOut, BookOut, LibraryOut } from "$lib/types";
  import { Plus } from "@lucide/svelte";

  let shelfId = $derived($page.params.id as string);

  let shelf = $state<BookshelfOut | null>(null);
  let books = $state<BookOut[]>([]);
  let loading = $state(true);
  let showAddModal = $state(false);
  let allBooks = $state<BookOut[]>([]);
  let addSearchQuery = $state("");

  let filteredAddBooks = $derived(
    addSearchQuery
      ? allBooks.filter((b) =>
          (b.display_title ?? "")
            .toLowerCase()
            .includes(addSearchQuery.toLowerCase()),
        )
      : allBooks,
  );

  onMount(async () => {
    if (!$authStore.token) {
      goto("/login");
      return;
    }
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
      allBooks = await import("$lib/api/books")
        .then((m) => m.booksApi.search("", $authStore.token!))
        .catch(() => []);
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
      toastStore.success("Book added to shelf");
      showAddModal = false;
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function removeBook(bookId: string) {
    if (!$authStore.token) return;
    try {
      await bookshelvesApi.removeBook(shelfId, bookId, $authStore.token);
      books = books.filter((b) => b.id !== bookId);
      toastStore.success("Book removed from shelf");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>{shelf?.name ?? "Bookshelf"} - BeePub</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
  {#if loading}
    <div class="flex items-center justify-center h-64">
      <div
        class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-primary"
      ></div>
    </div>
  {:else if shelf}
    <div class="flex items-end justify-between mb-8">
      <div>
        <a
          href="/bookshelves"
          class="text-muted-foreground hover:text-foreground text-sm mb-1 inline-block"
          >← Shelves</a
        >
        <h1 class="text-3xl font-bold text-foreground">{shelf.name}</h1>
        {#if shelf.description}
          <p class="text-muted-foreground mt-1">{shelf.description}</p>
        {/if}
      </div>
      <button
        class="flex items-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-medium px-5 py-2.5 rounded-xl transition-colors"
        onclick={() => (showAddModal = true)}
      >
        <Plus size={16} />
        Add Books
      </button>
    </div>

    {#if books.length === 0}
      <div class="bg-card card-soft rounded-2xl p-12 text-center">
        <p class="text-muted-foreground text-lg">No books in this shelf yet</p>
        <p class="text-muted-foreground/70 text-sm mt-1">
          Add some books to get started.
        </p>
      </div>
    {:else}
      <BookGrid {books} />
    {/if}
  {/if}
</div>

<Modal
  title="Add Books to Shelf"
  open={showAddModal}
  onclose={() => (showAddModal = false)}
>
  <div class="space-y-3">
    <input
      bind:value={addSearchQuery}
      placeholder="Search books..."
      class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
    />
    <div class="max-h-80 overflow-y-auto space-y-2">
      {#each filteredAddBooks as book}
        <button
          class="w-full text-left px-3 py-2.5 rounded-xl bg-secondary/50 hover:bg-secondary hover:shadow-sm flex items-center gap-3 transition-all"
          onclick={() => addBook(book.id)}
        >
          {#if book.cover_path}
            <img
              src="/covers/{book.id}.jpg"
              alt=""
              class="w-8 h-12 object-cover rounded"
            />
          {:else}
            <div
              class="w-8 h-12 bg-muted rounded flex items-center justify-center text-muted-foreground text-xs"
            >
              No cover
            </div>
          {/if}
          <div class="min-w-0">
            <p class="font-medium truncate text-foreground">
              {book.display_title ?? "Untitled"}
            </p>
            <p class="text-muted-foreground text-xs truncate">
              {(book.display_authors ?? []).join(", ")}
            </p>
          </div>
        </button>
      {/each}
    </div>
  </div>
</Modal>
