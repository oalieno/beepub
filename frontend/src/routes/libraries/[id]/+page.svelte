<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/stores";
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { librariesApi } from "$lib/api/libraries";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import Modal from "$lib/components/Modal.svelte";
  import type { LibraryOut, BookOut } from "$lib/types";
  import { UserRole } from "$lib/types";
  import { Upload, Search, X, HardDrive } from "@lucide/svelte";

  let libraryId = $derived($page.params.id as string);

  let library = $state<LibraryOut | null>(null);
  let isCalibre = $derived(!!library?.calibre_path);
  let canUpload = $derived(isAdmin && !isCalibre);
  let books = $state<BookOut[]>([]);
  let loading = $state(true);
  let searchQuery = $state("");
  let uploading = $state(false);
  let fileInput: HTMLInputElement;
  let showUploadModal = $state(false);
  let dragOver = $state(false);

  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);

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
      books = await librariesApi.getBooks(
        libraryId,
        $authStore.token,
        searchQuery || undefined,
      );
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
        toastStore.error(
          `Failed to upload ${file.name}: ${(e as Error).message}`,
        );
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
  <title>{library?.name ?? "Library"} - BeePub</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
  {#if loading}
    <div class="flex items-center justify-center h-64">
      <div
        class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-primary"
      ></div>
    </div>
  {:else if library}
    <div
      class="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-8"
    >
      <div>
        <div class="flex items-center gap-2 mb-1">
          <span
            class="text-xs px-2.5 py-1 rounded-full font-medium {library.visibility ===
            'public'
              ? 'bg-primary/15 text-primary'
              : 'bg-secondary text-muted-foreground'}"
          >
            {library.visibility}
          </span>
          {#if isCalibre}
            <span
              class="text-xs px-2.5 py-1 rounded-full font-medium bg-amber-500/15 text-amber-600 flex items-center gap-1"
            >
              <HardDrive size={12} />
              Calibre
            </span>
          {/if}
        </div>
        <h1 class="text-3xl font-bold text-foreground">{library.name}</h1>
        {#if library.description}
          <p class="text-muted-foreground mt-1">{library.description}</p>
        {/if}
      </div>
      {#if canUpload}
        <button
          class="flex items-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-medium px-5 py-2.5 rounded-xl transition-colors"
          onclick={() => (showUploadModal = true)}
        >
          <Upload size={16} />
          Upload Books
        </button>
      {/if}
    </div>

    <!-- Search -->
    <div class="relative mb-8">
      <Search
        class="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground"
        size={16}
      />
      <input
        type="text"
        bind:value={searchQuery}
        oninput={handleSearch}
        placeholder="Search by title, author, or topic..."
        class="w-full bg-card card-soft rounded-xl pl-10 pr-10 py-3 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
      {#if searchQuery}
        <button
          class="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          onclick={() => {
            searchQuery = "";
            handleSearch();
          }}
        >
          <X size={16} />
        </button>
      {/if}
    </div>

    {#if books.length === 0}
      <div
        class="border-2 border-dashed rounded-2xl p-12 text-center transition-colors {dragOver
          ? 'border-primary bg-primary/5'
          : 'border-border'}"
        ondragover={canUpload
          ? (e) => {
              e.preventDefault();
              dragOver = true;
            }
          : undefined}
        ondragleave={canUpload ? () => (dragOver = false) : undefined}
        ondrop={canUpload ? onDrop : undefined}
        role="region"
        aria-label="Drop zone"
      >
        <Upload class="mx-auto text-muted-foreground/30 mb-4" size={48} />
        <p class="text-muted-foreground text-lg">No books yet</p>
        <p class="text-muted-foreground/70 text-sm mt-1">
          {#if isCalibre}
            Sync from Calibre to add books.
          {:else if isAdmin}
            Upload EPUBs or drag and drop here.
          {:else}
            No books in this library.
          {/if}
        </p>
      </div>
    {:else}
      <div
        ondragover={canUpload
          ? (e) => {
              e.preventDefault();
              dragOver = true;
            }
          : undefined}
        ondragleave={canUpload ? () => (dragOver = false) : undefined}
        ondrop={canUpload ? onDrop : undefined}
        role="region"
        aria-label="Books"
      >
        <BookGrid {books} />
      </div>
    {/if}
  {/if}
</div>

<Modal
  title="Upload Books"
  open={showUploadModal}
  onclose={() => (showUploadModal = false)}
>
  <div class="space-y-4">
    <div
      class="border-2 border-dashed border-border rounded-2xl p-10 text-center cursor-pointer hover:border-primary/50 hover:bg-primary/5 transition-colors"
      onclick={() => fileInput?.click()}
      ondragover={(e) => e.preventDefault()}
      ondrop={(e) => {
        e.preventDefault();
        handleUpload(e.dataTransfer?.files ?? null);
      }}
      role="button"
      tabindex="0"
      onkeydown={(e) => e.key === "Enter" && fileInput?.click()}
    >
      <Upload class="mx-auto text-muted-foreground/40 mb-3" size={36} />
      <p class="text-foreground font-medium">Click or drag files</p>
      <p class="text-muted-foreground text-sm mt-1">EPUB format supported</p>
      <input
        bind:this={fileInput}
        type="file"
        accept=".epub"
        multiple
        class="hidden"
        onchange={(e) => handleUpload(e.currentTarget.files)}
      />
    </div>
    {#if uploading}
      <div class="flex items-center gap-2 text-primary text-sm">
        <div
          class="animate-spin rounded-full h-4 w-4 border-t-2 border-b-2 border-primary"
        ></div>
        Uploading...
      </div>
    {/if}
  </div>
</Modal>
