<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { isNative } from "$lib/platform";
  import { toastStore } from "$lib/stores/toast";
  import { BookOpen, Trash2, Download } from "@lucide/svelte";
  import type { DownloadEntry } from "$lib/services/offline";

  let entries = $state<DownloadEntry[]>([]);
  let totalSize = $state(0);
  let loading = $state(true);

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
      const { getDownloadedBooks, getStorageUsage, getCoverSrc } =
        await import("$lib/services/offline");
      const books = await getDownloadedBooks();
      // Always re-derive cover URIs (stored paths become stale after app restart)
      for (const book of books) {
        book.coverPath = await getCoverSrc(book);
      }
      entries = books;
      totalSize = await getStorageUsage();
    } catch {
      // ignore
    } finally {
      loading = false;
    }
  }

  async function handleDelete(bookId: string) {
    try {
      const { deleteLocalBook } = await import("$lib/services/offline");
      await deleteLocalBook(bookId);
      entries = entries.filter((e) => e.bookId !== bookId);
      totalSize = entries.reduce((sum, e) => sum + e.fileSize, 0);
      toastStore.success("Offline copy removed");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  onMount(loadEntries);
</script>

<svelte:head>
  <title>Downloads - BeePub</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
  <div class="mb-8">
    <h1 class="text-3xl font-bold text-foreground">Downloads</h1>
    <p class="text-muted-foreground mt-1">
      {#if entries.length > 0}
        {entries.length}
        {entries.length === 1 ? "book" : "books"} &middot; {formatSize(
          totalSize,
        )}
      {:else}
        Books downloaded for offline reading
      {/if}
    </p>
  </div>

  {#if loading}
    <div class="grid grid-cols-1 gap-4">
      {#each Array(3) as _}
        <div class="bg-card card-soft rounded-2xl p-4 animate-pulse">
          <div class="flex gap-4">
            <div class="w-16 h-24 rounded-lg bg-muted shrink-0"></div>
            <div class="flex-1 space-y-2">
              <div class="h-4 bg-muted rounded w-3/4"></div>
              <div class="h-3 bg-muted rounded w-1/2"></div>
              <div class="h-3 bg-muted rounded w-1/4"></div>
            </div>
          </div>
        </div>
      {/each}
    </div>
  {:else if !isNative()}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      <Download class="mx-auto mb-4 text-muted-foreground/30" size={48} />
      <p class="text-muted-foreground text-lg">
        Downloads are available in the mobile app
      </p>
    </div>
  {:else if entries.length === 0}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      <Download class="mx-auto mb-4 text-muted-foreground/30" size={48} />
      <p class="text-muted-foreground text-lg">No downloaded books</p>
      <p class="text-muted-foreground/70 text-sm mt-1">
        Download books from their detail page to read them offline.
      </p>
    </div>
  {:else}
    <div class="grid grid-cols-1 gap-3">
      {#each entries as entry (entry.bookId)}
        <div class="bg-card card-soft rounded-2xl p-4">
          <div class="flex gap-4 items-center">
            <!-- Cover -->
            <button
              class="w-16 h-24 rounded-lg overflow-hidden bg-muted shrink-0"
              onclick={() =>
                goto(`/books/${entry.bookId}/read`, { replaceState: true })}
            >
              {#if entry.coverPath}
                <img
                  src={entry.coverPath}
                  alt={entry.title}
                  class="w-full h-full object-cover"
                />
              {:else}
                <div
                  class="w-full h-full flex items-center justify-center text-muted-foreground/30"
                >
                  <BookOpen size={24} />
                </div>
              {/if}
            </button>

            <!-- Info -->
            <button
              class="flex-1 min-w-0 text-left"
              onclick={() =>
                goto(`/books/${entry.bookId}/read`, { replaceState: true })}
            >
              <p class="font-medium text-foreground line-clamp-2">
                {entry.title}
              </p>
              {#if entry.authors?.length}
                <p class="text-sm text-muted-foreground mt-0.5 line-clamp-1">
                  {entry.authors.join(", ")}
                </p>
              {/if}
              <p class="text-xs text-muted-foreground/70 mt-1">
                {formatSize(entry.fileSize)}
              </p>
            </button>

            <!-- Delete -->
            <button
              class="p-2 rounded-lg text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors shrink-0"
              title="Remove download"
              onclick={() => handleDelete(entry.bookId)}
            >
              <Trash2 size={18} />
            </button>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
