<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { bookshelvesApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import { BookGridSkeleton } from "$lib/components/skeletons";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import { BookOpen } from "@lucide/svelte";
  import BackButton from "$lib/components/BackButton.svelte";
  import * as m from "$lib/paraglide/messages.js";
  import type { BookshelfOut, BookOut } from "$lib/types";

  let shelfId = $derived(page.params.id as string);

  let shelf = $state<BookshelfOut | null>(null);
  let books = $state<BookOut[]>([]);
  let loading = $state(true);
  let pendingRemoveTimer: ReturnType<typeof setTimeout> | null = null;

  onMount(async () => {
    await loadData();
  });

  async function loadData() {
    loading = true;
    try {
      const [s, b] = await Promise.all([
        bookshelvesApi.get(shelfId),
        bookshelvesApi.getBooks(shelfId),
      ]);
      shelf = s;
      books = b;
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  function removeBook(bookId: string) {
    const removedBook = books.find((b) => b.id === bookId);
    if (!removedBook) return;

    books = books.filter((b) => b.id !== bookId);

    if (pendingRemoveTimer) clearTimeout(pendingRemoveTimer);

    toastStore.info(m.bookshelf_removed(), {
      action: {
        label: m.common_undo(),
        onclick: () => {
          if (pendingRemoveTimer) clearTimeout(pendingRemoveTimer);
          pendingRemoveTimer = null;
          books = [...books, removedBook];
        },
      },
      duration: 5000,
    });

    pendingRemoveTimer = setTimeout(async () => {
      try {
        await bookshelvesApi.removeBook(shelfId, bookId);
      } catch (e) {
        toastStore.error((e as Error).message);
        books = [...books, removedBook];
      }
      pendingRemoveTimer = null;
    }, 5000);
  }
</script>

<svelte:head>
  <title>{m.bookshelf_page_title({ name: shelf?.name ?? "Bookshelf" })}</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6">
  {#if loading}
    <div class="mb-8">
      <Skeleton class="h-4 w-20 mb-1" />
      <Skeleton class="h-9 w-48" />
    </div>
    <BookGridSkeleton count={12} />
  {:else if shelf}
    <div class="mb-8">
      <div class="mb-1">
        <BackButton href="/bookshelves" label={m.nav_shelves()} />
      </div>
      <h1 class="text-3xl font-bold text-foreground">{shelf.name}</h1>
      {#if shelf.description}
        <p class="text-muted-foreground mt-1">{shelf.description}</p>
      {/if}
    </div>

    {#if books.length === 0}
      <div class="flex flex-col items-center justify-center py-24 text-center">
        <div class="mb-4 p-3 bg-primary/10 rounded-xl">
          <BookOpen class="text-primary/50" size={28} />
        </div>
        <p class="text-foreground text-lg font-medium mb-2">
          {m.bookshelf_empty()}
        </p>
        <p class="text-muted-foreground text-sm max-w-xs">
          {m.bookshelf_empty_subtitle()}
        </p>
      </div>
    {:else}
      <BookGrid {books} enableInteractions />
    {/if}
  {/if}
</div>
