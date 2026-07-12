<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { isNative } from "$lib/platform";
  import { isLocalMode } from "$lib/api/client";
  import { toastStore } from "$lib/stores/toast";
  import { confirmDialog } from "$lib/stores/confirm";
  import { Button } from "$lib/components/ui/button";
  import {
    BookOpen,
    Cloud,
    Trash2,
    HardDrive,
    Plus,
    Loader2,
    RefreshCw,
    Rss,
    Server,
  } from "@lucide/svelte";
  import KosyncSettingsDialog from "$lib/components/KosyncSettingsDialog.svelte";
  import { BookGridSkeleton } from "$lib/components/skeletons";
  import * as m from "$lib/paraglide/messages.js";
  import type { LocalBookEntry } from "$lib/services/localLibrary";

  // In serverless local mode the (app) layout renders no chrome (there is
  // no authenticated user), so this page provides its own header.
  const localMode = isLocalMode();

  // Cover URIs are re-derived per mount, so keep them beside the entry
  // instead of mutating the manifest shape.
  type ShelfEntry = LocalBookEntry & {
    coverSrc: string | null;
    linked: boolean;
  };

  let entries = $state<ShelfEntry[]>([]);
  let totalSize = $state(0);
  let loading = $state(true);
  let importing = $state(false);
  let fileInput = $state<HTMLInputElement | null>(null);
  let kosyncOpen = $state(false);

  function formatSize(bytes: number): string {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  async function withCover(
    entry: LocalBookEntry,
    links: Record<string, string>,
  ): Promise<ShelfEntry> {
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

  async function handleDelete(e: MouseEvent, entry: ShelfEntry) {
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

<div
  class="px-6 sm:px-8 py-6"
  style={localMode
    ? "padding-top: calc(env(safe-area-inset-top, 0px) + 1.5rem);"
    : ""}
>
  {#if localMode}
    <div class="flex items-center gap-2 mb-6">
      <HardDrive size={20} class="text-primary" />
      <h1 class="text-xl font-bold" style="font-family: var(--font-heading)">
        {m.nav_local_books()}
      </h1>
      <!-- The only entry points to OPDS catalogs and kosync settings in
           serverless mode (no app chrome). -->
      <div class="ml-auto flex items-center gap-1">
        <Button variant="ghost" size="sm" onclick={() => goto("/catalogs")}>
          <Rss size={16} />
          {m.nav_catalogs()}
        </Button>
        <Button variant="ghost" size="sm" onclick={() => (kosyncOpen = true)}>
          <RefreshCw size={16} />
          {m.kosync_title()}
        </Button>
      </div>
    </div>
  {/if}
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
      <Button size="sm" disabled={importing} onclick={() => fileInput?.click()}>
        {#if importing}
          <Loader2 class="animate-spin" size={16} />
          {m.local_importing()}
        {:else}
          <Plus size={16} />
          {m.local_import()}
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
          <div
            role="button"
            tabindex="0"
            class="text-left w-full group cursor-pointer"
            style="-webkit-tap-highlight-color: transparent;"
            onclick={() => goto(`/books/${entry.id}/read`)}
            onkeydown={(e) =>
              e.key === "Enter" && goto(`/books/${entry.id}/read`)}
          >
            <!-- Cover -->
            <div class="h-56 sm:h-64 mb-3 flex items-end justify-center">
              <div
                class="relative inline-flex book-shadow-hover transition-all duration-300"
              >
                {#if entry.coverSrc}
                  <img
                    src={entry.coverSrc}
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
                  title={m.local_delete()}
                  onclick={(e) => handleDelete(e, entry)}
                >
                  <Trash2 size={14} />
                </button>

                <!-- File size badge -->
                <span
                  class="absolute bottom-1.5 left-1.5 text-[10px] font-medium bg-black/50 text-white/90 px-1.5 py-0.5 rounded-full"
                >
                  {formatSize(entry.fileSize)}
                </span>

                {#if entry.linked}
                  <!-- Linked to a server book: reading state syncs -->
                  <span
                    class="absolute bottom-1.5 right-1.5 bg-black/50 text-white/90 p-1 rounded-full"
                    title={m.local_linked_badge()}
                  >
                    <Cloud size={12} />
                  </span>
                {/if}
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

    {#if localMode}
      <div class="mt-12 pb-8 text-center">
        <Button
          variant="outline"
          class="rounded-xl"
          onclick={() => goto("/setup")}
        >
          <Server size={16} />
          {m.local_connect_server()}
        </Button>
      </div>
    {/if}
  {/if}
</div>

<KosyncSettingsDialog bind:open={kosyncOpen} />
