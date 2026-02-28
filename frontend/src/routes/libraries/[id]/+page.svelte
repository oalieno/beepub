<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import { librariesApi } from '$lib/api/libraries';
  import { booksApi } from '$lib/api/books';
  import { toastStore } from '$lib/stores/toast';
  import BookGrid from '$lib/components/BookGrid.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import type { LibraryOut, BookOut } from '$lib/types';
  import { UserRole } from '$lib/types';
  import { Upload, Search, X } from 'lucide-svelte';

  $: libraryId = $page.params.id;

  let library: LibraryOut | null = null;
  let books: BookOut[] = [];
  let loading = true;
  let searchQuery = '';
  let uploading = false;
  let fileInput: HTMLInputElement;
  let showUploadModal = false;
  let dragOver = false;

  $: isAdmin = $authStore.user?.role === UserRole.Admin;

  onMount(async () => {
    if (!$authStore.token) { goto('/login'); return; }
    await loadData();
  });

  async function loadData() {
    loading = true;
    try {
      [library, books] = await Promise.all([
        librariesApi.get(libraryId, $authStore.token!),
        librariesApi.getBooks(libraryId, $authStore.token!),
      ]);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleSearch() {
    if (!$authStore.token) return;
    try {
      books = await librariesApi.getBooks(libraryId, $authStore.token, searchQuery || undefined);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleUpload(files: FileList | null) {
    if (!files || files.length === 0 || !$authStore.token) return;
    uploading = true;
    let successCount = 0;
    for (const file of Array.from(files)) {
      try {
        await booksApi.upload(file, $authStore.token, libraryId);
        successCount++;
      } catch (e) {
        toastStore.error(`Failed to upload ${file.name}: ${(e as Error).message}`);
      }
    }
    if (successCount > 0) {
      toastStore.success(`Uploaded ${successCount} book(s)`);
      await loadData();
    }
    uploading = false;
    showUploadModal = false;
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    dragOver = false;
    handleUpload(e.dataTransfer?.files ?? null);
  }
</script>

<svelte:head>
  <title>{library?.name ?? 'Library'} - BeePub</title>
</svelte:head>

<div class="max-w-7xl mx-auto px-4 py-8">
  {#if loading}
    <div class="flex items-center justify-center h-64">
      <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-amber-500"></div>
    </div>
  {:else if library}
    <div class="flex flex-col sm:flex-row sm:items-start justify-between gap-4 mb-8">
      <div>
        <h1 class="text-3xl font-bold">{library.name}</h1>
        {#if library.description}
          <p class="text-gray-400 mt-1">{library.description}</p>
        {/if}
        <span class="inline-block mt-2 text-xs px-2 py-0.5 rounded {library.visibility === 'public' ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'}">
          {library.visibility}
        </span>
      </div>
      {#if isAdmin}
        <button
          class="flex items-center gap-2 bg-amber-500 hover:bg-amber-600 text-gray-900 font-semibold px-4 py-2 rounded-lg transition-colors"
          on:click={() => (showUploadModal = true)}
        >
          <Upload size={16} />
          Upload Books
        </button>
      {/if}
    </div>

    <!-- Search -->
    <div class="relative mb-6">
      <Search class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={16} />
      <input
        type="text"
        bind:value={searchQuery}
        on:input={handleSearch}
        placeholder="Search books..."
        class="w-full bg-gray-800 border border-gray-700 rounded-lg pl-9 pr-4 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-amber-500"
      />
      {#if searchQuery}
        <button
          class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white"
          on:click={() => { searchQuery = ''; handleSearch(); }}
        >
          <X size={16} />
        </button>
      {/if}
    </div>

    {#if books.length === 0}
      <div
        class="border-2 border-dashed border-gray-700 rounded-xl p-12 text-center {dragOver ? 'border-amber-500 bg-amber-500/10' : ''}"
        on:dragover|preventDefault={() => (dragOver = true)}
        on:dragleave={() => (dragOver = false)}
        on:drop={onDrop}
        role="region"
        aria-label="Drop zone"
      >
        <Upload class="mx-auto text-gray-600 mb-3" size={40} />
        <p class="text-gray-400">No books yet. {isAdmin ? 'Upload EPUBs or drag and drop here.' : 'No books in this library.'}</p>
      </div>
    {:else}
      <div
        on:dragover|preventDefault={() => (dragOver = true)}
        on:dragleave={() => (dragOver = false)}
        on:drop={onDrop}
        role="region"
        aria-label="Books"
      >
        <BookGrid {books} />
      </div>
    {/if}
  {/if}
</div>

<Modal title="Upload Books" open={showUploadModal} on:close={() => (showUploadModal = false)}>
  <div class="space-y-4">
    <div
      class="border-2 border-dashed border-gray-600 rounded-lg p-8 text-center cursor-pointer hover:border-amber-500 transition-colors"
      on:click={() => fileInput?.click()}
      on:dragover|preventDefault
      on:drop={(e) => { e.preventDefault(); handleUpload(e.dataTransfer?.files ?? null); }}
      role="button"
      tabindex="0"
      on:keydown={(e) => e.key === 'Enter' && fileInput?.click()}
    >
      <Upload class="mx-auto text-gray-500 mb-2" size={32} />
      <p class="text-gray-400 text-sm">Click or drag EPUB files here</p>
      <input
        bind:this={fileInput}
        type="file"
        accept=".epub"
        multiple
        class="hidden"
        on:change={(e) => handleUpload(e.currentTarget.files)}
      />
    </div>
    {#if uploading}
      <div class="flex items-center gap-2 text-amber-500">
        <div class="animate-spin rounded-full h-4 w-4 border-t-2 border-b-2 border-amber-500"></div>
        Uploading...
      </div>
    {/if}
  </div>
</Modal>
