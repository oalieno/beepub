<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { isNative } from "$lib/platform";
  import { toastStore } from "$lib/stores/toast";
  import { confirmDialog } from "$lib/stores/confirm";
  import { Button } from "$lib/components/ui/button";
  import * as Select from "$lib/components/ui/select";
  import {
    ArrowUpDown,
    ChevronRight,
    FileUp,
    HardDrive,
    Plus,
    Loader2,
    Rss,
    Search,
    X,
  } from "@lucide/svelte";
  import BottomSheet from "$lib/components/BottomSheet.svelte";
  import LocalBookCard, {
    type LocalShelfEntry,
  } from "$lib/components/LocalBookCard.svelte";
  import { BookGridSkeleton } from "$lib/components/skeletons";
  import * as m from "$lib/paraglide/messages.js";

  // The local library's shelf: a root tab, so no back navigation.

  let entries = $state<LocalShelfEntry[]>([]);
  let totalSize = $state(0);
  let loading = $state(true);

  // Client-side search/sort — the shelf is small enough to filter in memory.
  // Newest first by default, like the cloud libraries; resuming a book is
  // Home's continue-reading row.
  const SORT_OPTIONS = [
    { value: "importedAt:desc", label: () => m.browser_sort_newest() },
    { value: "lastRead:desc", label: () => m.local_sort_last_read() },
    { value: "importedAt:asc", label: () => m.browser_sort_oldest() },
    { value: "title:asc", label: () => m.browser_sort_title_asc() },
    { value: "title:desc", label: () => m.browser_sort_title_desc() },
  ];
  let searchQuery = $state("");
  let sortValue = $state("importedAt:desc");
  let sortLabel = $derived(
    (
      SORT_OPTIONS.find((o) => o.value === sortValue) ?? SORT_OPTIONS[0]
    ).label(),
  );
  let visibleEntries = $derived.by(() => {
    const q = searchQuery.trim().toLowerCase();
    const filtered = q
      ? entries.filter(
          (e) =>
            e.title.toLowerCase().includes(q) ||
            e.authors.join(" ").toLowerCase().includes(q),
        )
      : entries;
    const sorted = [...filtered];
    switch (sortValue) {
      case "importedAt:desc":
        sorted.sort((a, b) => b.importedAt.localeCompare(a.importedAt));
        break;
      case "importedAt:asc":
        sorted.sort((a, b) => a.importedAt.localeCompare(b.importedAt));
        break;
      case "title:asc":
        sorted.sort((a, b) => a.title.localeCompare(b.title));
        break;
      case "title:desc":
        sorted.sort((a, b) => b.title.localeCompare(a.title));
        break;
      default:
        // Recently read first; never-opened books follow, newest import
        // first.
        sorted.sort((a, b) => {
          if (a.lastReadAt && b.lastReadAt)
            return b.lastReadAt.localeCompare(a.lastReadAt);
          if (a.lastReadAt) return -1;
          if (b.lastReadAt) return 1;
          return b.importedAt.localeCompare(a.importedAt);
        });
    }
    return sorted;
  });
  let importing = $state(false);
  let fileInput = $state<HTMLInputElement | null>(null);
  let addSheetOpen = $state(false);

  function formatSize(bytes: number): string {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  async function loadEntries() {
    if (!isNative()) {
      loading = false;
      return;
    }
    try {
      const { getLocalStorageUsage } =
        await import("$lib/services/localLibrary");
      const { loadShelfEntries } = await import("$lib/services/localShelf");
      entries = await loadShelfEntries();
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
      const { toShelfEntry } = await import("$lib/services/localShelf");
      entries = [await toShelfEntry(entry, {}), ...entries];
      totalSize += entry.fileSize;
      toastStore.success(m.local_import_success({ title: entry.title }));
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

  async function handleExport(entry: LocalShelfEntry) {
    try {
      const { shareLocalBookFile } = await import("$lib/services/localLibrary");
      await shareLocalBookFile(entry.id);
    } catch (err) {
      // Dismissing the share sheet also rejects — that is not an error.
      const msg = (err as Error).message ?? "";
      if (!/cancel/i.test(msg)) {
        toastStore.error(msg || m.local_export_failed());
      }
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

  onMount(async () => {
    await loadEntries();
  });
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
      <!-- Search & sort, mirroring the cloud library browser's controls -->
      <div class="mb-6 space-y-4">
        <div class="relative">
          <Search
            class="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground"
            size={16}
          />
          <input
            type="text"
            bind:value={searchQuery}
            placeholder={m.local_search_placeholder()}
            class="w-full bg-card card-soft rounded-xl pl-10 pr-10 py-3 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          {#if searchQuery}
            <button
              aria-label={m.common_clear()}
              class="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              onclick={() => (searchQuery = "")}
            >
              <X size={16} />
            </button>
          {/if}
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <Select.Root
            type="single"
            value={sortValue}
            onValueChange={(v) => {
              if (v) sortValue = v;
            }}
          >
            <Select.Trigger
              class="!h-8 inline-flex items-center gap-1.5 text-xs px-2.5 rounded-full bg-secondary text-muted-foreground font-medium hover:bg-secondary/80 transition-colors border-none shadow-none"
            >
              <ArrowUpDown size={12} />
              {sortLabel}
            </Select.Trigger>
            <Select.Content>
              {#each SORT_OPTIONS as opt (opt.value)}
                <Select.Item value={opt.value}>{opt.label()}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        </div>
      </div>

      {#if visibleEntries.length === 0}
        <p class="text-muted-foreground text-sm text-center py-16">
          {m.browser_no_books()}
        </p>
      {:else}
        <div
          class="grid gap-4 items-start book-grid"
          style="grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));"
        >
          {#each visibleEntries as entry (entry.id)}
            <LocalBookCard
              {entry}
              ondelete={handleDelete}
              onexport={isNative() ? handleExport : undefined}
              onopenlegacy={(e) => goto(`/books/${e.id}/read-legacy`)}
            />
          {/each}
        </div>
      {/if}
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
        <h3 class="font-medium text-sm text-foreground">
          {m.nav_catalogs()}
        </h3>
        <p class="text-muted-foreground text-xs mt-0.5">
          {m.local_add_opds_desc()}
        </p>
      </div>
      <ChevronRight size={16} class="text-muted-foreground shrink-0" />
    </button>
  </div>
</BottomSheet>
