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
  import LibrarySelector from "$lib/components/LibrarySelector.svelte";
  import Modal from "$lib/components/Modal.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { BookGridSkeleton } from "$lib/components/skeletons";
  import type { LibraryOut } from "$lib/types";
  import { UserRole } from "$lib/types";
  import { Upload, HardDrive } from "@lucide/svelte";
  import * as m from "$lib/paraglide/messages.js";
  import type { Snapshot } from "./$types";

  const ALL = "all";

  function emptyState(): BookBrowserState {
    return {
      books: [],
      feedItems: [],
      totalBooks: 0,
      searchQuery: "",
      filterAuthor: "",
      filterTag: "",
      filterSeries: "",
      sortValue: "added_at:desc",
      collapse: false,
    };
  }

  let libraries = $state<LibraryOut[]>([]);
  let listLoading = $state(true);
  let selectedLib = $state<string>(page.url.searchParams.get("lib") || ALL);
  // Bumped after an upload to force the browser to reload the current view.
  let reloadNonce = $state(0);

  let selectedLibrary = $derived(
    selectedLib === ALL
      ? null
      : (libraries.find((l) => l.id === selectedLib) ?? null),
  );
  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);
  let isCalibre = $derived(!!selectedLibrary?.calibre_path);
  let canUpload = $derived(isAdmin && !!selectedLibrary && !isCalibre);

  let bookBrowser = $state<BookBrowser>();
  let restoreData = $state<BookBrowserState | null>(null);
  let restoredFromSnapshot = $state(false);
  let pendingScrollY = $state(0);

  let uploading = $state(false);
  let fileInput: HTMLInputElement;
  let showUploadModal = $state(false);
  let dragOver = $state(false);

  interface PageSnapshot {
    browserState: BookBrowserState;
    libraries: LibraryOut[];
    selectedLib: string;
    scrollY: number;
  }

  export const snapshot: Snapshot<PageSnapshot> = {
    capture: () => ({
      browserState: bookBrowser?.getState() ?? emptyState(),
      libraries,
      selectedLib,
      scrollY: window.scrollY,
    }),
    restore: (data) => {
      libraries = data.libraries;
      selectedLib = data.selectedLib;
      restoreData = data.browserState;
      pendingScrollY = data.scrollY;
      restoredFromSnapshot = true;
      listLoading = false;
    },
  };

  afterNavigate(async () => {
    if (restoredFromSnapshot) {
      restoredFromSnapshot = false;
      await tick();
      await tick();
      window.scrollTo(0, pendingScrollY);
      restoreData = null;
      return;
    }
    restoreData = null;
    listLoading = true;
    try {
      libraries = await librariesApi.list();
      // Fall back to All books if the URL points at an inaccessible library.
      if (selectedLib !== ALL && !libraries.some((l) => l.id === selectedLib)) {
        selectedLib = ALL;
      }
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      listLoading = false;
    }
  });

  function selectLibrary(lib: string) {
    if (lib === selectedLib) return;
    selectedLib = lib;
    const url = new URL(page.url);
    if (lib === ALL) url.searchParams.delete("lib");
    else url.searchParams.set("lib", lib);
    // Start the new library fresh, but keep the collapse preference.
    for (const k of ["search", "author", "tag", "series", "sort"])
      url.searchParams.delete(k);
    replaceState(url, {});
  }

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
    return selectedLib === ALL
      ? booksApi.getAll(params)
      : librariesApi.getBooks(selectedLib, params);
  }

  function fetchFeed(params: {
    search?: string;
    author?: string;
    tag?: string;
    sort?: string;
    order?: string;
    limit?: number;
    offset?: number;
  }) {
    return selectedLib === ALL
      ? booksApi.getFeed(params)
      : librariesApi.getFeed(selectedLib, params);
  }

  function handleStateChange(state: BookBrowserState) {
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
    if (state.collapse) url.searchParams.set("collapse", "1");
    else url.searchParams.delete("collapse");
    replaceState(url, {});
  }

  async function handleUpload(files: FileList | null) {
    if (!files || files.length === 0 || selectedLib === ALL) return;
    uploading = true;
    let successCount = 0;
    for (const file of Array.from(files)) {
      try {
        await booksApi.upload(file, selectedLib);
        successCount++;
      } catch (e) {
        toastStore.error(
          `Failed to upload ${file.name}: ${(e as Error).message}`,
        );
      }
    }
    if (successCount > 0) {
      toastStore.success(m.library_uploaded({ count: String(successCount) }));
      // Force the browser to remount and reload the current view.
      reloadNonce += 1;
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
  <title>{m.libraries_page_title()}</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6">
  {#if listLoading}
    <!-- Selector -->
    <div class="mb-6">
      <div class="inline-flex gap-1 rounded-md bg-muted p-1">
        {#each Array(4) as _}
          <div class="h-8 w-24 animate-pulse rounded-sm bg-foreground/10"></div>
        {/each}
      </div>
    </div>
    <!-- Search bar + toolbar (mirrors BookBrowser) -->
    <div class="mb-6 space-y-4">
      <div class="h-12 w-full animate-pulse rounded-xl bg-foreground/10"></div>
      <div class="flex gap-2">
        <div class="h-8 w-28 animate-pulse rounded-full bg-foreground/10"></div>
        <div class="h-8 w-20 animate-pulse rounded-full bg-foreground/10"></div>
        <div class="h-8 w-24 animate-pulse rounded-full bg-foreground/10"></div>
      </div>
    </div>
    <BookGridSkeleton count={12} />
  {:else}
    <!-- Library selector replaces the page headline -->
    <div class="mb-6">
      <LibrarySelector
        {libraries}
        selected={selectedLib}
        onSelect={selectLibrary}
      />
    </div>

    <!-- Selected-library context (badge / description / upload) -->
    {#if selectedLibrary}
      <div
        class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6"
      >
        <div class="min-w-0">
          {#if isCalibre}
            <span
              class="text-xs px-2.5 py-1 rounded-full font-medium bg-amber-500/15 text-amber-600 inline-flex items-center gap-1"
            >
              <HardDrive size={12} />
              {m.library_calibre_badge()}
            </span>
          {/if}
          {#if selectedLibrary.description}
            <p class="text-muted-foreground text-sm mt-1">
              {selectedLibrary.description}
            </p>
          {/if}
        </div>
        {#if canUpload}
          <button
            class="shrink-0 flex items-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-medium px-4 py-2 rounded-xl transition-colors"
            onclick={() => (showUploadModal = true)}
          >
            <Upload size={16} />
            {m.library_upload()}
          </button>
        {/if}
      </div>
    {/if}

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
      {#key `${selectedLib}:${reloadNonce}`}
        <BookBrowser
          bind:this={bookBrowser}
          {fetchBooks}
          {fetchFeed}
          collapsible
          {restoreData}
          initialSearch={(page.url.searchParams.get("search") ?? "").trim()}
          initialTag={(page.url.searchParams.get("tag") ?? "").trim()}
          initialAuthor={(page.url.searchParams.get("author") ?? "").trim()}
          initialSeries={(page.url.searchParams.get("series") ?? "").trim()}
          initialSort={page.url.searchParams.get("sort") || "added_at:desc"}
          initialCollapse={page.url.searchParams.get("collapse") === "1"}
          emptyMessage={m.browser_no_books()}
          onStateChange={handleStateChange}
        />
      {/key}
    </div>
  {/if}
</div>

<Modal
  title={m.library_upload()}
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
      <p class="text-foreground font-medium">{m.library_upload_drag()}</p>
      <p class="text-muted-foreground text-sm mt-1">
        {m.library_upload_hint()}
      </p>
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
        {m.library_uploading()}
      </div>
    {/if}
  </div>
</Modal>
