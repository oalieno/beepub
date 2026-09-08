<script lang="ts">
  import { tick } from "svelte";
  import { page } from "$app/state";
  import { goto, replaceState, afterNavigate } from "$app/navigation";
  import { isNative } from "$lib/platform";
  import { authStore } from "$lib/stores/auth";
  import { getLocale } from "$lib/paraglide/runtime.js";
  import ZhConversionToggle from "$lib/components/ZhConversionToggle.svelte";
  import { librariesApi } from "$lib/api/libraries";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import { setActiveLibrary } from "$lib/stores/activeLibrary";
  import BookBrowser from "$lib/components/BookBrowser.svelte";
  import type { BookBrowserState } from "$lib/components/BookBrowser.svelte";
  import Modal from "$lib/components/Modal.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { LibraryDetailSkeleton } from "$lib/components/skeletons";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import type { LibraryOut } from "$lib/types";
  import { UserRole } from "$lib/types";
  import { ArrowLeftRight, BookCopy, Plus, Upload, X } from "@lucide/svelte";
  import { Button } from "$lib/components/ui/button";
  import * as m from "$lib/paraglide/messages.js";
  import type { Snapshot } from "./$types";

  // The "all" pseudo-library spans every accessible library.
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

  let id = $derived(page.params.id as string);
  // null while loading a concrete library, and always null for "all".
  let library = $state<LibraryOut | null>(null);
  let loading = $state(true);
  // Bumped after an upload to force the browser to reload the current view.
  let reloadNonce = $state(0);

  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);
  let isCalibre = $derived(!!library?.calibre_path);
  let canUpload = $derived(
    (isAdmin || !!$authStore.user?.can_upload) && !!library && !isCalibre,
  );
  let heading = $derived(
    library?.name ??
      (isNative() ? m.libraries_cloud_books() : m.allbooks_heading()),
  );

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
    library: LibraryOut | null;
    scrollY: number;
  }

  export const snapshot: Snapshot<PageSnapshot> = {
    capture: () => ({
      browserState: bookBrowser?.getState() ?? emptyState(),
      library,
      scrollY: window.scrollY,
    }),
    restore: (data) => {
      library = data.library;
      restoreData = data.browserState;
      pendingScrollY = data.scrollY;
      restoredFromSnapshot = true;
      loading = false;
    },
  };

  // Also runs on same-route navigation (library A -> library B), which does
  // NOT remount this component — every bit of per-library state resets here.
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
    library = null;
    if (id === ALL) {
      setActiveLibrary(ALL);
      loading = false;
      return;
    }
    loading = true;
    try {
      library = await librariesApi.get(id);
    } catch (e) {
      toastStore.error((e as Error).message);
      // Don't leave the active library pointing at a dead id — the nav
      // entry would bounce through this error on every tap.
      setActiveLibrary(ALL);
      goto("/libraries", { replaceState: true });
      return;
    }
    setActiveLibrary(id);
    loading = false;
  });

  function fetchBooks(params: {
    search?: string;
    author?: string;
    tag?: string;
    series?: string;
    format?: string;
    sort?: string;
    order?: string;
    limit?: number;
    offset?: number;
  }) {
    return id === ALL
      ? booksApi.getAll(params)
      : librariesApi.getBooks(id, params);
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
    return id === ALL
      ? booksApi.getFeed(params)
      : librariesApi.getFeed(id, params);
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
    if (state.filterFormat) url.searchParams.set("format", state.filterFormat);
    else url.searchParams.delete("format");
    if (state.sortValue !== "added_at:desc")
      url.searchParams.set("sort", state.sortValue);
    else url.searchParams.delete("sort");
    if (state.collapse) url.searchParams.set("collapse", "1");
    else url.searchParams.delete("collapse");
    replaceState(url, {});
  }

  // Two-step upload: files are listed first (a chance to catch a wrong
  // file, and to see the options that apply to them), then sent together.
  let pendingFiles = $state<File[]>([]);
  let uploadedCount = $state(0);
  let pendingHasTxt = $derived(
    pendingFiles.some((f) => f.name.toLowerCase().endsWith(".txt")),
  );

  // The Simplified-to-Traditional switch is a Traditional Chinese reader's
  // concern: shown for that UI language, or while the setting is on, and
  // only when a TXT is waiting. Decided when the dialog opens so switching
  // it off keeps the row until the dialog closes.
  let showZhToggle = $state(false);
  function openUploadModal() {
    showZhToggle =
      getLocale() === "zh-Hant" || !!$authStore.user?.upload_zh_conversion;
    showUploadModal = true;
  }
  function closeUploadModal() {
    if (uploading) return;
    showUploadModal = false;
    pendingFiles = [];
  }

  function addFiles(files: FileList | null) {
    if (!files) return;
    for (const file of Array.from(files)) {
      const dup = pendingFiles.some(
        (p) => p.name === file.name && p.size === file.size,
      );
      if (!dup) pendingFiles.push(file);
    }
  }

  function fmtSize(bytes: number): string {
    if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }

  async function uploadPending() {
    if (pendingFiles.length === 0 || uploading || id === ALL) return;
    uploading = true;
    uploadedCount = 0;
    let successCount = 0;
    for (const file of pendingFiles) {
      try {
        await booksApi.upload(file, id);
        successCount++;
      } catch (e) {
        toastStore.error(
          `Failed to upload ${file.name}: ${(e as Error).message}`,
        );
      }
      uploadedCount++;
    }
    if (successCount > 0) {
      toastStore.success(m.library_uploaded({ count: String(successCount) }));
      // Force the browser to remount and reload the current view.
      reloadNonce += 1;
    }
    uploading = false;
    pendingFiles = [];
    showUploadModal = false;
  }

  // A drop anywhere on the page lands in the dialog, not straight on the
  // server.
  function onDrop(e: DragEvent) {
    e.preventDefault();
    dragOver = false;
    if (id === ALL) return;
    addFiles(e.dataTransfer?.files ?? null);
    openUploadModal();
  }
</script>

<svelte:head>
  <title>{m.library_page_title({ name: heading })}</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6">
  {#if loading}
    <LibraryDetailSkeleton />
  {:else}
    <div
      class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6"
    >
      <div class="min-w-0">
        <!-- Calibre-style: the library name IS the switcher — tapping it
             goes up to the cards page to pick another library. -->
        <a
          href="/libraries"
          class="group inline-flex items-center gap-2 max-w-full"
          title={m.library_switch()}
          aria-label={m.library_switch()}
        >
          <h1
            class="text-2xl font-bold text-foreground truncate group-hover:text-primary transition-colors"
          >
            {heading}
          </h1>
          <ArrowLeftRight
            size={18}
            class="shrink-0 text-muted-foreground/60 group-hover:text-primary transition-colors"
          />
        </a>
        {#if library?.description}
          <p class="text-muted-foreground text-sm mt-1">
            {library.description}
          </p>
        {/if}
      </div>
      {#if canUpload}
        <DropdownMenu.Root>
          <DropdownMenu.Trigger>
            <button
              class="shrink-0 flex items-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-medium px-4 py-2 rounded-xl transition-colors"
            >
              <Plus size={16} />
              {m.library_add_books()}
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Content align="end">
            <DropdownMenu.Item onclick={openUploadModal}>
              <Upload size={14} />
              {m.library_upload()}
            </DropdownMenu.Item>
            <DropdownMenu.Item
              onclick={() => goto(`/libraries/${id}/physical/new`)}
            >
              <BookCopy size={14} />
              {m.physical_add()}
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Root>
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
      {#key `${id}:${reloadNonce}`}
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
          initialFormat={(page.url.searchParams.get("format") ?? "").trim()}
          initialSort={page.url.searchParams.get("sort") || "added_at:desc"}
          initialCollapse={page.url.searchParams.get("collapse") === "1"}
          emptyMessage={m.browser_library_empty()}
          searchPlaceholder={library
            ? m.browser_search_in_library({ name: library.name })
            : m.browser_search_all()}
          onStateChange={handleStateChange}
        />
      {/key}
    </div>
  {/if}
</div>

<Modal
  title={m.library_upload()}
  open={showUploadModal}
  onclose={closeUploadModal}
>
  <div class="space-y-4">
    <div
      class="border-2 border-dashed border-border rounded-2xl text-center cursor-pointer hover:border-primary/50 hover:bg-primary/5 transition-colors {pendingFiles.length
        ? 'p-5'
        : 'p-10'}"
      onclick={() => fileInput?.click()}
      ondragover={(e) => e.preventDefault()}
      ondrop={(e) => {
        e.preventDefault();
        addFiles(e.dataTransfer?.files ?? null);
      }}
      role="button"
      tabindex="0"
      onkeydown={(e) => e.key === "Enter" && fileInput?.click()}
    >
      <Upload
        class="mx-auto text-muted-foreground/40 mb-3"
        size={pendingFiles.length ? 24 : 36}
      />
      <p class="text-foreground font-medium">{m.library_upload_drag()}</p>
      <p class="text-muted-foreground text-sm mt-1">
        {m.library_upload_hint()}
      </p>
      <input
        bind:this={fileInput}
        type="file"
        accept=".epub,.txt"
        multiple
        class="hidden"
        onchange={(e) => {
          addFiles(e.currentTarget.files);
          e.currentTarget.value = "";
        }}
      />
    </div>
    {#if pendingFiles.length}
      <ul class="divide-y divide-border rounded-xl border border-border">
        {#each pendingFiles as file, i (file.name + file.size)}
          <li class="flex items-center gap-3 px-3 py-2 text-sm">
            <span class="flex-1 truncate" title={file.name}>{file.name}</span>
            <span class="text-muted-foreground tabular-nums shrink-0"
              >{fmtSize(file.size)}</span
            >
            <button
              type="button"
              class="text-muted-foreground hover:text-foreground disabled:opacity-40 shrink-0"
              aria-label={m.library_upload_remove({ name: file.name })}
              disabled={uploading}
              onclick={() => pendingFiles.splice(i, 1)}
            >
              <X size={16} />
            </button>
          </li>
        {/each}
      </ul>
    {/if}
    {#if showZhToggle && pendingHasTxt}
      <ZhConversionToggle />
    {/if}
    <div class="flex items-center justify-end gap-3">
      {#if uploading}
        <span class="flex items-center gap-2 text-primary text-sm">
          <Spinner size="sm" />
          {m.library_uploading_progress({
            done: String(uploadedCount),
            total: String(pendingFiles.length),
          })}
        </span>
      {/if}
      <Button
        class="rounded-xl"
        disabled={pendingFiles.length === 0 || uploading}
        onclick={uploadPending}
      >
        {m.library_upload_confirm({ count: String(pendingFiles.length) })}
      </Button>
    </div>
  </div>
</Modal>
