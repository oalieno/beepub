<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { isNative } from "$lib/platform";
  import { toastStore } from "$lib/stores/toast";
  import { BookOpen, Trash2, Download } from "@lucide/svelte";
  import { BookGridSkeleton } from "$lib/components/skeletons";
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

  async function handleDelete(e: MouseEvent, bookId: string, title: string) {
    e.stopPropagation();
    e.preventDefault();
    if (!confirm(`Delete "${title}"?`)) return;
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

<div class="px-6 sm:px-8 py-6">
  {#if loading}
    <BookGridSkeleton count={6} />
  {:else if !isNative()}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      <Download class="mx-auto mb-4 text-muted-foreground/30" size={48} />
      <p class="text-muted-foreground text-lg">
        Downloads are available in the mobile app
      </p>
    </div>
  {:else if entries.length === 0}
    <div class="flex flex-col items-center justify-center py-24 text-center">
      <div class="mb-4 p-3 bg-primary/10 rounded-xl">
        <Download class="text-primary/50" size={28} />
      </div>
      <p class="text-foreground text-lg font-medium mb-2">No downloads yet</p>
      <p class="text-muted-foreground text-sm max-w-xs mb-6">
        Download books from their detail page to read them offline.
      </p>
    </div>
  {:else}
    <div
      class="grid gap-4"
      style="grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));"
    >
      {#each entries as entry (entry.bookId)}
        <div
          role="button"
          tabindex="0"
          class="text-left w-full group cursor-pointer"
          style="-webkit-tap-highlight-color: transparent;"
          onclick={() =>
            goto(`/books/${entry.bookId}/read`, { replaceState: true })}
          onkeydown={(e) =>
            e.key === "Enter" &&
            goto(`/books/${entry.bookId}/read`, { replaceState: true })}
        >
          <!-- Cover -->
          <div class="h-56 sm:h-64 mb-3 flex items-end justify-center">
            <div
              class="relative inline-flex book-shadow-hover transition-all duration-300"
            >
              {#if entry.coverPath}
                <img
                  src={entry.coverPath}
                  alt={entry.title}
                  class="max-h-56 sm:max-h-64 w-auto max-w-full rounded-sm book-shadow"
                  loading="lazy"
                />
              {:else}
                <div
                  class="h-56 sm:h-64 aspect-[2/3] bg-secondary rounded-sm flex flex-col items-center justify-center gap-2 p-4 book-shadow"
                >
                  <BookOpen class="text-muted-foreground/30" size={36} />
                  <span
                    class="text-muted-foreground/60 text-xs text-center line-clamp-3"
                    >{entry.title}</span
                  >
                </div>
              {/if}

              <!-- Delete button overlay -->
              <button
                class="absolute top-2 right-2 p-1.5 rounded-full bg-black/50 text-white/80 hover:bg-destructive hover:text-white transition-all duration-200
                  opacity-70 can-hover:opacity-0 can-hover:group-hover:opacity-100"
                style="-webkit-tap-highlight-color: transparent; touch-action: manipulation;"
                title="Remove download"
                onclick={(e) => handleDelete(e, entry.bookId, entry.title)}
              >
                <Trash2 size={14} />
              </button>

              <!-- File size badge -->
              <span
                class="absolute bottom-1.5 left-1.5 text-[10px] font-medium bg-black/50 text-white/90 px-1.5 py-0.5 rounded-full"
              >
                {formatSize(entry.fileSize)}
              </span>
            </div>
          </div>

          <!-- Info below cover -->
          <div class="min-h-[3rem]">
            <h3
              class="font-medium text-sm line-clamp-2 leading-snug text-foreground group-hover:text-primary transition-colors"
            >
              {entry.title}
            </h3>
            {#if entry.authors?.length}
              <p class="text-muted-foreground text-xs mt-0.5 line-clamp-1">
                {entry.authors.join(", ")}
              </p>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
