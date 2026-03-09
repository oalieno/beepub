<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/stores";
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { bookshelvesApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import type { BookshelfOut, BookOut } from "$lib/types";

  let shelfId = $derived($page.params.id as string);

  let shelf = $state<BookshelfOut | null>(null);
  let books = $state<BookOut[]>([]);
  let loading = $state(true);

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
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
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
    <div class="mb-8">
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

    {#if books.length === 0}
      <div class="bg-card card-soft rounded-2xl p-12 text-center">
        <p class="text-muted-foreground text-lg">No books in this shelf yet</p>
        <p class="text-muted-foreground/70 text-sm mt-1">
          Add books from book detail pages.
        </p>
      </div>
    {:else}
      <BookGrid {books} />
    {/if}
  {/if}
</div>
