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
  import type { BookOut, ExternalMetadataOut, BookshelfOut, InteractionOut, HighlightOut } from '$lib/types';
  import HighlightList from '$lib/components/HighlightList.svelte';
  import { UserRole } from '$lib/types';
  import { Heart, BookOpen, Trash2, Edit, RefreshCw, BookMarked, ExternalLink } from '@lucide/svelte';

  let bookId = $derived($page.params.id as string);

  let book = $state<BookOut | null>(null);
  let interaction = $state<InteractionOut | null>(null);
  let externalMeta = $state<ExternalMetadataOut[]>([]);
  let bookshelves = $state<BookshelfOut[]>([]);
  let bookHighlights = $state<HighlightOut[]>([]);
  let loading = $state(true);
  let showEditModal = $state(false);
  let showAddToShelf = $state(false);
  let editForm = $state({ title: '', authors: '', description: '', publisher: '', published_date: '' });

  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);

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
      // Load highlights
      try {
        bookHighlights = await booksApi.getHighlights(bookId, $authStore.token!);
      } catch {
        // ignore
      }
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleRating(rating: number) {
    if (!book || !$authStore.token) return;
    try {
      await booksApi.updateRating(bookId, rating, $authStore.token);
      if (interaction) interaction = { ...interaction, rating };
      else interaction = { rating, is_favorite: false, reading_progress: null, updated_at: '' };
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

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
  {#if loading}
    <div class="flex items-center justify-center h-64">
      <div class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-primary"></div>
    </div>
  {:else if book}
    <div class="flex flex-col md:flex-row gap-10">
      <!-- Cover -->
      <div class="flex-shrink-0 w-64 mx-auto md:mx-0">
        <div class="aspect-[2/3] rounded-lg overflow-hidden book-shadow">
          {#if book.cover_path}
            <img src="/covers/{book.id}.jpg" alt="{book.display_title} cover" class="w-full h-full object-cover" />
          {:else}
            <div class="w-full h-full bg-secondary flex items-center justify-center">
              <BookOpen class="text-muted-foreground/30" size={48} />
            </div>
          {/if}
        </div>

        <!-- Actions -->
        <div class="mt-5 flex flex-col gap-2.5">
          <a
            href="/books/{book.id}/read"
            class="flex items-center justify-center gap-2 bg-foreground hover:bg-foreground/90 text-background font-semibold px-4 py-3 rounded-xl transition-colors"
          >
            <BookOpen size={16} />
            Start Reading
          </a>
          <div class="flex gap-2">
            <button
              class="flex-1 flex items-center justify-center gap-1.5 bg-card card-soft text-foreground px-3 py-2.5 rounded-xl text-sm font-medium hover:shadow-md transition-all"
              onclick={toggleFavorite}
            >
              <Heart size={14} class={interaction?.is_favorite ? 'fill-red-500 text-red-500' : ''} />
              {interaction?.is_favorite ? 'Saved' : 'Save'}
            </button>
            <button
              class="flex-1 flex items-center justify-center gap-1.5 bg-card card-soft text-foreground px-3 py-2.5 rounded-xl text-sm font-medium hover:shadow-md transition-all"
              onclick={() => (showAddToShelf = true)}
            >
              <BookMarked size={14} />
              Shelf
            </button>
          </div>
        </div>
      </div>

      <!-- Details -->
      <div class="flex-1 min-w-0">
        <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
          <div>
            <h1 class="text-3xl font-bold leading-tight text-foreground">{book.display_title ?? 'Untitled'}</h1>
            {#if (book.display_authors ?? []).length > 0}
              <p class="text-muted-foreground text-lg mt-1.5">{(book.display_authors ?? []).join(', ')}</p>
            {/if}
          </div>
          {#if isAdmin}
            <div class="flex items-center gap-1 flex-shrink-0 self-start sm:self-auto">
              <button class="w-8 h-8 rounded-full bg-secondary flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors" onclick={() => (showEditModal = true)} title="Edit metadata">
                <Edit size={14} />
              </button>
              <button class="w-8 h-8 rounded-full bg-secondary flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors" onclick={handleRefreshMeta} title="Refresh metadata">
                <RefreshCw size={14} />
              </button>
              <button class="w-8 h-8 rounded-full bg-secondary flex items-center justify-center text-destructive hover:bg-destructive/10 transition-colors" onclick={handleDelete} title="Delete book">
                <Trash2 size={14} />
              </button>
            </div>
          {/if}
        </div>

        <!-- Rating -->
        <div class="mt-5">
          <p class="text-sm text-muted-foreground mb-1.5">Your rating</p>
          <StarRating value={interaction?.rating ?? null} onchange={handleRating} />
        </div>

        <!-- Metadata -->
        <div class="mt-6 bg-card card-soft rounded-2xl p-5">
          <div class="grid grid-cols-2 gap-3 text-sm">
            {#if book.publisher ?? book.epub_publisher}
              <div><span class="text-muted-foreground block text-xs">Publisher</span> <span class="text-foreground font-medium">{book.publisher ?? book.epub_publisher}</span></div>
            {/if}
            {#if book.published_date ?? book.epub_published_date}
              <div><span class="text-muted-foreground block text-xs">Published</span> <span class="text-foreground font-medium">{book.published_date ?? book.epub_published_date}</span></div>
            {/if}
            {#if book.epub_language}
              <div><span class="text-muted-foreground block text-xs">Language</span> <span class="text-foreground font-medium">{book.epub_language}</span></div>
            {/if}
            {#if book.epub_isbn}
              <div><span class="text-muted-foreground block text-xs">ISBN</span> <span class="text-foreground font-medium">{book.epub_isbn}</span></div>
            {/if}
          </div>
        </div>

        <!-- Highlights -->
        {#if bookHighlights.length > 0}
          <div class="mt-6">
            <h2 class="text-xl font-bold mb-3 text-foreground">Highlights</h2>
            <div class="bg-card card-soft rounded-2xl p-4 max-h-80 overflow-y-auto">
              <HighlightList
                highlights={bookHighlights}
                onselect={(hl) => goto(`/books/${bookId}/read`)}
                ondelete={async (hl) => {
                  if (!$authStore.token) return;
                  try {
                    await booksApi.deleteHighlight(bookId, hl.id, $authStore.token);
                    bookHighlights = bookHighlights.filter((h) => h.id !== hl.id);
                    toastStore.success('Highlight removed');
                  } catch (e) {
                    toastStore.error((e as Error).message);
                  }
                }}
              />
            </div>
          </div>
        {/if}

        <!-- Description -->
        {#if book.description ?? book.epub_description}
          <div class="mt-6">
            <h2 class="text-xl font-bold mb-3 text-foreground">Description</h2>
            <div class="text-muted-foreground leading-relaxed prose-description">
              {@html book.description ?? book.epub_description}
            </div>
          </div>
        {/if}

        <!-- External metadata -->
        {#if externalMeta.length > 0}
          <div class="mt-6">
            <h2 class="text-xl font-bold mb-3 text-foreground">External Ratings</h2>
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {#each externalMeta as meta}
                <div class="bg-card card-soft rounded-2xl p-4">
                  <p class="text-sm font-medium capitalize mb-1 text-foreground">{meta.source.replace('_', ' ')}</p>
                  {#if meta.rating !== null}
                    <p class="text-primary text-xl font-bold">{meta.rating?.toFixed(1)}</p>
                  {:else}
                    <p class="text-muted-foreground text-sm">No rating</p>
                  {/if}
                  {#if meta.rating_count !== null}
                    <p class="text-muted-foreground text-xs">{meta.rating_count?.toLocaleString()} ratings</p>
                  {/if}
                  {#if meta.source_url}
                    <a href={meta.source_url} target="_blank" rel="noopener" class="text-xs text-primary hover:underline flex items-center gap-1 mt-1.5">
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
  <Modal title="Edit Metadata" open={showEditModal} onclose={() => (showEditModal = false)}>
    <div class="space-y-4">
      <div class="space-y-1">
        <label class="block text-sm font-medium text-foreground" for="edit-title">Title</label>
        <input id="edit-title" bind:value={editForm.title} class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30" />
      </div>
      <div class="space-y-1">
        <label class="block text-sm font-medium text-foreground" for="edit-authors">Authors (comma-separated)</label>
        <input id="edit-authors" bind:value={editForm.authors} class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30" />
      </div>
      <div class="space-y-1">
        <label class="block text-sm font-medium text-foreground" for="edit-publisher">Publisher</label>
        <input id="edit-publisher" bind:value={editForm.publisher} class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30" />
      </div>
      <div class="space-y-1">
        <label class="block text-sm font-medium text-foreground" for="edit-date">Published Date</label>
        <input id="edit-date" bind:value={editForm.published_date} class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30" />
      </div>
      <div class="space-y-1">
        <label class="block text-sm font-medium text-foreground" for="edit-desc">Description</label>
        <textarea id="edit-desc" bind:value={editForm.description} rows={4} class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none"></textarea>
      </div>
      <div class="flex justify-end gap-2 pt-2">
        <button class="px-4 py-2 text-sm text-muted-foreground hover:text-foreground" onclick={() => (showEditModal = false)}>Cancel</button>
        <button class="px-5 py-2.5 text-sm bg-primary hover:bg-primary/90 text-primary-foreground font-semibold rounded-xl" onclick={handleSaveEdit}>Save</button>
      </div>
    </div>
  </Modal>

  <Modal title="Add to Bookshelf" open={showAddToShelf} onclose={() => (showAddToShelf = false)}>
    <div class="space-y-2">
      {#if bookshelves.length === 0}
        <p class="text-muted-foreground text-sm">No bookshelves yet. <a href="/bookshelves" class="text-primary">Create one</a>.</p>
      {:else}
        {#each bookshelves as shelf}
          <button
            class="w-full text-left px-4 py-3 rounded-xl bg-secondary/50 hover:bg-secondary hover:shadow-sm transition-all"
            onclick={() => addToShelf(shelf.id)}
          >
            <p class="font-medium text-foreground">{shelf.name}</p>
            {#if shelf.description}
              <p class="text-muted-foreground text-xs mt-0.5">{shelf.description}</p>
            {/if}
          </button>
        {/each}
      {/if}
    </div>
  </Modal>
{/if}
