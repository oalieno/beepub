<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { isNative } from "$lib/platform";
  import { hasServerUrl } from "$lib/api/client";
  import { isOnline } from "$lib/services/network";
  import { authStore } from "$lib/stores/auth";
  import { toastStore } from "$lib/stores/toast";
  import { confirmDialog } from "$lib/stores/confirm";
  import { Button } from "$lib/components/ui/button";
  import {
    ChevronRight,
    CloudUpload,
    FileUp,
    HardDrive,
    Plus,
    Loader2,
    Rss,
  } from "@lucide/svelte";
  import BottomSheet from "$lib/components/BottomSheet.svelte";
  import LocalBookCard, {
    type LocalShelfEntry,
  } from "$lib/components/LocalBookCard.svelte";
  import { BookGridSkeleton } from "$lib/components/skeletons";
  import * as m from "$lib/paraglide/messages.js";
  import { UserRole, type LibraryOut } from "$lib/types";
  import type { LocalBookEntry } from "$lib/services/localLibrary";

  let entries = $state<LocalShelfEntry[]>([]);
  let totalSize = $state(0);
  let loading = $state(true);
  let importing = $state(false);
  let fileInput = $state<HTMLInputElement | null>(null);
  let addSheetOpen = $state(false);

  // Upload-to-cloud: offered per unlinked card when a server is connected
  // and the account may upload. Calibre libraries can't take uploads, so
  // eligibility is decided against the fetched library list.
  let canUploadToCloud = $derived(
    isNative() &&
      hasServerUrl() &&
      $isOnline &&
      ($authStore.user?.role === UserRole.Admin ||
        !!$authStore.user?.can_upload),
  );
  let uploadingId = $state<string | null>(null);
  let pickerEntry = $state<LocalShelfEntry | null>(null);
  let pickerLibraries = $state<LibraryOut[]>([]);
  let pickerOpen = $state(false);
  const UPLOAD_LIB_KEY = "upload-library";

  function formatSize(bytes: number): string {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  // Cover URIs are re-derived per mount, so keep them beside the entry
  // instead of mutating the manifest shape.
  async function withCover(
    entry: LocalBookEntry,
    links: Record<string, string>,
  ): Promise<LocalShelfEntry> {
    const { getLocalCoverSrc } = await import("$lib/services/localLibrary");
    return {
      ...entry,
      coverSrc: await getLocalCoverSrc(entry),
      linked: entry.id in links,
    };
  }

  async function loadEntries() {
    if (!isNative()) {
      loading = false;
      return;
    }
    try {
      const { listLocalBooks, getLocalStorageUsage, getLocalBookLinks } =
        await import("$lib/services/localLibrary");
      const books = await listLocalBooks();
      const links = await getLocalBookLinks();
      entries = await Promise.all(books.map((b) => withCover(b, links)));
      totalSize = await getLocalStorageUsage();
    } catch {
      // ignore
    } finally {
      loading = false;
    }
  }

  async function handleImport(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    importing = true;
    const { importLocalBook, DuplicateBookError, InvalidEpubError } =
      await import("$lib/services/localLibrary");
    try {
      const entry = await importLocalBook(file);
      entries = [await withCover(entry, {}), ...entries];
      totalSize += entry.fileSize;
      toastStore.success(m.local_import_success({ title: entry.title }));
      // Fire-and-forget: if the same file exists on the server, link it
      // and start syncing right away.
      void import("$lib/services/readingSync").then(({ linkAndSyncBook }) =>
        linkAndSyncBook(entry).then((linked) => {
          if (!linked) return;
          entries = entries.map((b) =>
            b.id === entry.id ? { ...b, linked: true } : b,
          );
          toastStore.info(m.local_linked());
        }),
      );
    } catch (err) {
      if (err instanceof DuplicateBookError) {
        toastStore.info(
          m.local_import_duplicate({ title: err.existing.title }),
        );
      } else if (err instanceof InvalidEpubError) {
        toastStore.error(m.local_import_invalid());
      } else {
        toastStore.error((err as Error).message);
      }
    } finally {
      importing = false;
      // Re-picking the same file must fire change again.
      input.value = "";
    }
  }

  function markLinked(id: string) {
    entries = entries.map((b) => (b.id === id ? { ...b, linked: true } : b));
    void import("$lib/stores/linkedBooks").then(({ refreshLinkedBookIds }) =>
      refreshLinkedBookIds(),
    );
  }

  async function startUpload(entry: LocalShelfEntry) {
    if (uploadingId) return;
    try {
      const { booksApi } = await import("$lib/api/books");
      // Already on the server (upload has no digest dedup — a re-upload
      // would mint a duplicate book)? Then this is a link, not an upload.
      const { matches } = await booksApi.lookupByDigest([entry.digest]);
      const match = matches[entry.digest];
      if (match) {
        const { setLocalBookLink } = await import("$lib/services/localLibrary");
        await setLocalBookLink(entry.id, match.id);
        markLinked(entry.id);
        toastStore.info(m.local_linked());
        void import("$lib/services/readingSync").then(({ syncLocalBook }) =>
          syncLocalBook(entry.id).catch(() => {}),
        );
        return;
      }
      const { librariesApi } = await import("$lib/api/libraries");
      const libs = (await librariesApi.list()).filter((l) => !l.calibre_path);
      if (libs.length === 0) {
        toastStore.error(m.local_upload_no_library());
        return;
      }
      if (libs.length === 1) {
        await doUpload(entry, libs[0].id);
        return;
      }
      // Picker, with the last-used library sorted first.
      let last: string | null = null;
      try {
        last = localStorage.getItem(UPLOAD_LIB_KEY);
      } catch {
        /* ignore */
      }
      pickerLibraries = last
        ? [...libs].sort(
            (a, b) => Number(b.id === last) - Number(a.id === last),
          )
        : libs;
      pickerEntry = entry;
      pickerOpen = true;
    } catch (err) {
      toastStore.error((err as Error).message);
    }
  }

  async function doUpload(entry: LocalShelfEntry, libraryId: string) {
    pickerOpen = false;
    pickerEntry = null;
    uploadingId = entry.id;
    try {
      try {
        localStorage.setItem(UPLOAD_LIB_KEY, libraryId);
      } catch {
        /* ignore */
      }
      const { readLocalBookBytes, setLocalBookLink } =
        await import("$lib/services/localLibrary");
      const bytes = await readLocalBookBytes(entry.id);
      if (!bytes) throw new Error(`Local book file missing: ${entry.id}`);
      const { sanitizeFilename } = await import("$lib/services/epubDownload");
      const { booksApi } = await import("$lib/api/books");
      const file = new File([bytes], `${sanitizeFilename(entry.title)}.epub`, {
        type: "application/epub+zip",
      });
      const book = await booksApi.upload(file, libraryId);
      await setLocalBookLink(entry.id, book.id);
      markLinked(entry.id);
      toastStore.success(m.local_upload_success({ title: entry.title }));
      // Ship the accumulated reading state to the fresh server book.
      void import("$lib/services/readingSync").then(({ syncLocalBook }) =>
        syncLocalBook(entry.id).catch(() => {}),
      );
    } catch (err) {
      toastStore.error((err as Error).message);
    } finally {
      uploadingId = null;
    }
  }

  async function handleDelete(e: MouseEvent, entry: LocalShelfEntry) {
    e.stopPropagation();
    e.preventDefault();
    if (
      !(await confirmDialog({
        title: m.local_delete_confirm({ title: entry.title }),
        destructive: true,
      }))
    )
      return;
    try {
      const { removeLocalBook } = await import("$lib/services/localLibrary");
      await removeLocalBook(entry.id);
      // Removal also unlinks — drop the "on this device" badge upstream.
      void import("$lib/stores/linkedBooks").then(({ refreshLinkedBookIds }) =>
        refreshLinkedBookIds(),
      );
      entries = entries.filter((b) => b.id !== entry.id);
      totalSize = entries.reduce((sum, b) => sum + b.fileSize, 0);
      toastStore.success(m.local_deleted());
    } catch (err) {
      toastStore.error((err as Error).message);
    }
  }

  onMount(loadEntries);
</script>

<svelte:head>
  <title>{m.local_page_title()}</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6">
  {#if loading}
    <BookGridSkeleton count={6} />
  {:else if !isNative()}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      <HardDrive class="mx-auto mb-4 text-muted-foreground/30" size={48} />
      <p class="text-muted-foreground text-lg">
        {m.local_native_only()}
      </p>
    </div>
  {:else}
    <input
      bind:this={fileInput}
      type="file"
      accept=".epub,application/epub+zip"
      class="hidden"
      onchange={handleImport}
    />

    <div class="flex items-center justify-between gap-3 mb-6">
      <p class="text-sm text-muted-foreground">
        {#if entries.length > 0}
          {formatSize(totalSize)}
        {/if}
      </p>
      <Button
        size="sm"
        disabled={importing}
        onclick={() => (addSheetOpen = true)}
      >
        {#if importing}
          <Loader2 class="animate-spin" size={16} />
          {m.local_importing()}
        {:else}
          <Plus size={16} />
          {m.local_add()}
        {/if}
      </Button>
    </div>

    {#if entries.length === 0}
      <div class="flex flex-col items-center justify-center py-24 text-center">
        <div class="mb-4 p-3 bg-primary/10 rounded-xl">
          <HardDrive class="text-primary/50" size={28} />
        </div>
        <p class="text-foreground text-lg font-medium mb-2">
          {m.local_empty()}
        </p>
        <p class="text-muted-foreground text-sm max-w-xs mb-6">
          {m.local_empty_subtitle()}
        </p>
      </div>
    {:else}
      <div
        class="grid gap-4"
        style="grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));"
      >
        {#each entries as entry (entry.id)}
          <LocalBookCard
            {entry}
            ondelete={handleDelete}
            onupload={canUploadToCloud ? startUpload : undefined}
            uploading={uploadingId === entry.id}
          />
        {/each}
      </div>
    {/if}
  {/if}
</div>

<BottomSheet bind:open={addSheetOpen}>
  <h2 class="text-base font-semibold px-3 pt-2 pb-3">{m.local_add()}</h2>
  <div class="pb-2 space-y-1">
    <button
      class="w-full flex items-center gap-3 p-3 rounded-xl hover:bg-secondary/50 active:bg-secondary transition-colors text-left"
      style="-webkit-tap-highlight-color: transparent;"
      onclick={() => {
        addSheetOpen = false;
        fileInput?.click();
      }}
    >
      <div class="p-2.5 bg-primary/10 rounded-xl shrink-0">
        <FileUp class="text-primary" size={18} />
      </div>
      <div class="flex-1 min-w-0">
        <h3 class="font-medium text-sm text-foreground">
          {m.local_add_file()}
        </h3>
        <p class="text-muted-foreground text-xs mt-0.5">
          {m.local_add_file_desc()}
        </p>
      </div>
      <ChevronRight size={16} class="text-muted-foreground shrink-0" />
    </button>
    <button
      class="w-full flex items-center gap-3 p-3 rounded-xl hover:bg-secondary/50 active:bg-secondary transition-colors text-left"
      style="-webkit-tap-highlight-color: transparent;"
      onclick={() => {
        addSheetOpen = false;
        goto("/catalogs");
      }}
    >
      <div class="p-2.5 bg-primary/10 rounded-xl shrink-0">
        <Rss class="text-primary" size={18} />
      </div>
      <div class="flex-1 min-w-0">
        <h3 class="font-medium text-sm text-foreground">{m.nav_catalogs()}</h3>
        <p class="text-muted-foreground text-xs mt-0.5">
          {m.local_add_opds_desc()}
        </p>
      </div>
      <ChevronRight size={16} class="text-muted-foreground shrink-0" />
    </button>
  </div>
</BottomSheet>

<!-- Target-library picker: only shown when more than one library accepts
     uploads (single-target uploads go straight through). -->
<BottomSheet bind:open={pickerOpen}>
  <h2 class="text-base font-semibold px-3 pt-2 pb-3">
    {m.local_upload_pick_library()}
  </h2>
  <div class="pb-2 space-y-1">
    {#each pickerLibraries as lib (lib.id)}
      <button
        class="w-full flex items-center gap-3 p-3 rounded-xl hover:bg-secondary/50 active:bg-secondary transition-colors text-left"
        style="-webkit-tap-highlight-color: transparent;"
        onclick={() => pickerEntry && doUpload(pickerEntry, lib.id)}
      >
        <div class="p-2.5 bg-primary/10 rounded-xl shrink-0">
          <CloudUpload class="text-primary" size={18} />
        </div>
        <h3 class="flex-1 min-w-0 font-medium text-sm text-foreground truncate">
          {lib.name}
        </h3>
        <ChevronRight size={16} class="text-muted-foreground shrink-0" />
      </button>
    {/each}
  </div>
</BottomSheet>
