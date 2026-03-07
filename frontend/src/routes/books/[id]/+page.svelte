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
  import { Heart, BookOpen, Trash2, Edit, RefreshCw, BookMarked, ExternalLink, Star, StarHalf, EllipsisVertical } from '@lucide/svelte';

  const SOURCE_META: Record<string, { label: string; color: string; logo: string }> = {
    goodreads: { label: 'Goodreads', color: '#5C4B3A', logo: 'g' },
    readmoo: { label: 'Readmoo', color: '#2E7D32', logo: 'R' },
    kobo_tw: { label: 'Kobo', color: '#BF360C', logo: 'K' },
  };

  function renderStars(rating: number): { full: number; half: boolean; empty: number } {
    const full = Math.floor(rating);
    const half = rating - full >= 0.25 && rating - full < 0.75;
    const extra = rating - full >= 0.75 ? 1 : 0;
    const totalFull = full + extra;
    const empty = 5 - totalFull - (half ? 1 : 0);
    return { full: totalFull, half, empty };
  }

  let bookId = $derived($page.params.id as string);

  let book = $state<BookOut | null>(null);
  let interaction = $state<InteractionOut | null>(null);
  let externalMeta = $state<ExternalMetadataOut[]>([]);
  let bookshelves = $state<BookshelfOut[]>([]);
  let bookHighlights = $state<HighlightOut[]>([]);
  let loading = $state(true);
  let showEditModal = $state(false);
  let showAddToShelf = $state(false);
  let showAdminMenu = $state(false);
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
    <!-- Hero Section -->
    <div class="flex flex-col md:flex-row gap-12">
      <!-- Cover -->
      <div class="flex-shrink-0 w-64 mx-auto md:mx-0">
        <div class="aspect-[2/3] rounded-sm overflow-hidden book-shadow">
          {#if book.cover_path}
            <img src="/covers/{book.id}.jpg" alt="{book.display_title} cover" class="w-full h-full object-cover" />
          {:else}
            <div class="w-full h-full bg-secondary flex items-center justify-center">
              <BookOpen class="text-muted-foreground/30" size={48} />
            </div>
          {/if}
        </div>
      </div>

      <!-- Info -->
      <div class="flex-1 min-w-0 flex flex-col pt-6">
        <div>
          <h1 class="text-4xl font-bold leading-tight text-foreground">{book.display_title ?? 'Untitled'}</h1>
          {#if (book.display_authors ?? []).length > 0}
            <p class="text-muted-foreground text-lg mt-2">{(book.display_authors ?? []).join(', ')}</p>
          {/if}
        </div>

        <!-- Rating -->
        <div class="mt-5">
          <p class="text-sm text-muted-foreground mb-1.5">Your rating</p>
          <StarRating value={interaction?.rating ?? null} onchange={handleRating} />
        </div>

        <!-- External Ratings (compact inline) -->
        {#if externalMeta.length > 0}
          <div class="mt-4 flex flex-wrap items-center gap-4">
            {#each externalMeta as meta}
              {@const src = SOURCE_META[meta.source] ?? { label: meta.source, color: '#666', logo: '?' }}
              {@const stars = meta.rating != null ? renderStars(meta.rating) : null}
              <a
                href={meta.source_url ?? '#'}
                target={meta.source_url ? '_blank' : undefined}
                rel={meta.source_url ? 'noopener' : undefined}
                class="flex items-center gap-2 hover:opacity-80 transition-opacity"
                onclick={meta.source_url ? undefined : (e) => e.preventDefault()}
              >
                <span class="text-muted-foreground text-sm font-medium">{src.label}</span>
                {#if meta.rating != null && stars}
                  <span class="text-lg font-bold text-foreground">{meta.rating.toFixed(1)}</span>
                  <div class="flex items-center gap-px">
                    {#each Array(stars.full) as _}
                      <Star size={12} class="fill-muted-foreground text-muted-foreground" />
                    {/each}
                    {#if stars.half}
                      <StarHalf size={12} class="fill-muted-foreground text-muted-foreground" />
                    {/if}
                    {#each Array(stars.empty) as _}
                      <Star size={12} class="text-muted-foreground/30" />
                    {/each}
                  </div>
                {:else}
                  <span class="text-muted-foreground text-sm">-</span>
                {/if}
              </a>
            {/each}
          </div>
        {/if}

        <!-- Action Buttons -->
        <div class="mt-auto pt-6 flex items-center gap-3">
          <a
            href="/books/{book.id}/read"
            class="flex items-center justify-center gap-2 bg-foreground hover:bg-foreground/90 text-background font-semibold px-6 py-3 rounded-full transition-colors"
          >
            <BookOpen size={16} />
            Start Reading
          </a>
          <button
            class="w-10 h-10 flex items-center justify-center bg-card card-soft rounded-full text-foreground hover:shadow-md transition-all"
            onclick={toggleFavorite}
            title={interaction?.is_favorite ? 'Remove from favorites' : 'Add to favorites'}
          >
            <Heart size={16} class={interaction?.is_favorite ? 'fill-red-500 text-red-500' : ''} />
          </button>
          <button
            class="w-10 h-10 flex items-center justify-center bg-card card-soft rounded-full text-foreground hover:shadow-md transition-all"
            onclick={() => (showAddToShelf = true)}
            title="Add to bookshelf"
          >
            <BookMarked size={16} />
          </button>
          {#if isAdmin}
            <div class="relative">
              <button
                class="w-10 h-10 flex items-center justify-center bg-card card-soft rounded-full text-muted-foreground hover:text-foreground hover:shadow-md transition-all"
                onclick={() => (showAdminMenu = !showAdminMenu)}
                title="Admin actions"
              >
                <EllipsisVertical size={16} />
              </button>
              {#if showAdminMenu}
                <button class="fixed inset-0 z-40" onclick={() => (showAdminMenu = false)} aria-label="Close menu"></button>
                <div class="absolute left-0 bottom-full mb-2 z-50 bg-card border border-border rounded-xl shadow-lg whitespace-nowrap">
                  <button
                    class="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-foreground hover:bg-secondary transition-colors rounded-t-xl"
                    onclick={() => { showAdminMenu = false; showEditModal = true; }}
                  >
                    <Edit size={14} class="flex-shrink-0" />
                    Edit metadata
                  </button>
                  <button
                    class="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-foreground hover:bg-secondary transition-colors"
                    onclick={() => { showAdminMenu = false; handleRefreshMeta(); }}
                  >
                    <RefreshCw size={14} class="flex-shrink-0" />
                    Refresh metadata
                  </button>
                  <button
                    class="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-destructive hover:bg-destructive/10 transition-colors rounded-b-xl"
                    onclick={() => { showAdminMenu = false; handleDelete(); }}
                  >
                    <Trash2 size={14} class="flex-shrink-0" />
                    Delete book
                  </button>
                </div>
              {/if}
            </div>
          {/if}
        </div>
      </div>
    </div>

    <!-- Separator -->
    <div class="border-t border-border my-8"></div>

    <!-- Description + Metadata -->
    <div class="flex flex-col md:flex-row gap-10">
      {#if book.description ?? book.epub_description}
        <div class="flex-1 min-w-0">
          <h2 class="text-xl font-bold mb-3 text-foreground">Description</h2>
          <div class="text-muted-foreground leading-relaxed prose-description">
            {@html book.description ?? book.epub_description}
          </div>
        </div>
      {/if}

      {#if (book.publisher ?? book.epub_publisher) || (book.published_date ?? book.epub_published_date) || book.epub_language || book.epub_isbn}
        <div class="flex-shrink-0 w-full md:w-64">
          <div class="flex flex-col gap-4 text-sm">
            {#if book.publisher ?? book.epub_publisher}
              <div><span class="text-muted-foreground block text-xs mb-0.5">Publisher</span> <span class="text-foreground font-medium">{book.publisher ?? book.epub_publisher}</span></div>
            {/if}
            {#if book.published_date ?? book.epub_published_date}
              <div><span class="text-muted-foreground block text-xs mb-0.5">Published</span> <span class="text-foreground font-medium">{book.published_date ?? book.epub_published_date}</span></div>
            {/if}
            {#if book.epub_language}
              <div><span class="text-muted-foreground block text-xs mb-0.5">Language</span> <span class="text-foreground font-medium">{book.epub_language}</span></div>
            {/if}
            {#if book.epub_isbn}
              <div><span class="text-muted-foreground block text-xs mb-0.5">ISBN</span> <span class="text-foreground font-medium">{book.epub_isbn}</span></div>
            {/if}
          </div>
        </div>
      {/if}
    </div>

    <!-- Highlights -->
    {#if bookHighlights.length > 0}
      <div class="border-t border-border my-8"></div>
      <div>
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
