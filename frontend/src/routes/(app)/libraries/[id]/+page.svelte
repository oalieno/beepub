<script lang="ts">
  import { tick } from "svelte";
  import { page } from "$app/state";
  import { replaceState, afterNavigate } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { librariesApi } from "$lib/api/libraries";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import BookBrowser from "$lib/components/BookBrowser.svelte";
  import type { BookBrowserState } from "$lib/components/BookBrowser.svelte";
  import Modal from "$lib/components/Modal.svelte";
  import type { LibraryOut, BookOut } from "$lib/types";
  import { UserRole } from "$lib/types";
  import { Upload, HardDrive } from "@lucide/svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { LibraryDetailSkeleton } from "$lib/components/skeletons";
  import type { Snapshot } from "./$types";

  let libraryId = $derived(page.params.id as string);

  let library = $state<LibraryOut | null>(null);
  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);
  let isCalibre = $derived(!!library?.calibre_path);
  let canUpload = $derived(isAdmin && !isCalibre);
  let libraryLoading = $state(true);
  let uploading = $state(false);
  let fileInput: HTMLInputElement;
  let showUploadModal = $state(false);
  let dragOver = $state(false);
  let restoredFromSnapshot = $state(false);
  let pendingScrollY = $state(0);

  let bookBrowser = $state<BookBrowser>();
  let browserState = $state<BookBrowserState | null>(null);

  interface PageSnapshot {
    browserState: BookBrowserState;
    library: LibraryOut | null;
    scrollY: number;
  }

  export const snapshot: Snapshot<PageSnapshot> = {
    capture: () => ({
      browserState: bookBrowser?.getState() ?? {
        books: [],
        totalBooks: 0,
        searchQuery: "",
        filterAuthor: "",
        filterTag: "",
        filterSeries: "",
        sortValue: "added_at:desc",
      },
      library,
      scrollY: window.scrollY,
    }),
    restore: (data) => {
      library = data.library;
      browserState = data.browserState;
      pendingScrollY = data.scrollY;
      restoredFromSnapshot = true;
      libraryLoading = false;
    },
  };

  afterNavigate(async () => {
    if (restoredFromSnapshot) {
      restoredFromSnapshot = false;
      await tick();
      if (browserState && bookBrowser) {
        bookBrowser.restoreState(browserState);
      }
      await tick();
      window.scrollTo(0, pendingScrollY);
      return;
    }

    libraryLoading = true;
    try {
      library = await librariesApi.get(libraryId);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      libraryLoading = false;
    }
  });

  function fetchBooks(params: {
    search?: string;
    author?: string;
    tag?: string;
    series?: string;
    sort?: string;
    order?: string;
    limit?: number;
    offset?: number;
  }) {
    return librariesApi.getBooks(libraryId, params);
  }

  function handleStateChange(state: BookBrowserState) {
    // Sync URL params
    const url = new URL(page.url);
    if (state.searchQuery) url.searchParams.set("search", state.searchQuery);
    else url.searchParams.delete("search");
    if (state.filterAuthor) url.searchParams.set("author", state.filterAuthor);
    else url.searchParams.delete("author");
    if (state.filterTag) url.searchParams.set("tag", state.filterTag);
    else url.searchParams.delete("tag");
    if (state.filterSeries) url.searchParams.set("series", state.filterSeries);
    else url.searchParams.delete("series");
    if (state.sortValue !== "added_at:desc")
      url.searchParams.set("sort", state.sortValue);
    else url.searchParams.delete("sort");
    replaceState(url, {});
  }

  async function handleUpload(files: FileList | null) {
    if (!files || files.length === 0) return;
    uploading = true;
    let successCount = 0;
    for (const file of Array.from(files)) {
      try {
        await booksApi.upload(file, libraryId);
        successCount++;
      } catch (e) {
        toastStore.error(
          `Failed to upload ${file.name}: ${(e as Error).message}`,
        );
      }
    }
    if (successCount > 0) {
      toastStore.success(`Uploaded ${successCount} book(s)`);
      // Reload the BookBrowser by re-mounting
      // (the simplest approach — BookBrowser loads on mount)
      libraryLoading = true;
      await tick();
      libraryLoading = false;
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

<div class="px-6 sm:px-8 py-6">
  {#if libraryLoading}
    <LibraryDetailSkeleton />
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

    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      ondragover={canUpload
        ? (e) => {
            e.preventDefault();
            dragOver = true;
          }
        : undefined}
      ondragleave={canUpload ? () => (dragOver = false) : undefined}
      ondrop={canUpload ? onDrop : undefined}
      class={dragOver ? "ring-2 ring-primary/30 rounded-2xl" : ""}
    >
      <BookBrowser
        bind:this={bookBrowser}
        {fetchBooks}
        initialSearch={(page.url.searchParams.get("search") ?? "").trim()}
        initialTag={(page.url.searchParams.get("tag") ?? "").trim()}
        initialAuthor={(page.url.searchParams.get("author") ?? "").trim()}
        initialSeries={(page.url.searchParams.get("series") ?? "").trim()}
        initialSort={page.url.searchParams.get("sort") || "added_at:desc"}
        emptyMessage={isCalibre
          ? "Sync from Calibre to add books."
          : isAdmin
            ? "Upload EPUBs or drag and drop here."
            : "No books in this library."}
        onStateChange={handleStateChange}
      />
    </div>
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
        <Spinner size="sm" />
        Uploading...
      </div>
    {/if}
  </div>
</Modal>
