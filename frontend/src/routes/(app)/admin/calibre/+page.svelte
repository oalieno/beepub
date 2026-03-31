<script lang="ts">
  import { onMount } from "svelte";
  import { adminApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import type { CalibreLibraryInfo, CalibreLibraryStatus } from "$lib/types";
  import {
    HardDrive,
    RefreshCw,
    Link,
    CircleCheck,
    CircleAlert,
    LoaderCircle,
  } from "@lucide/svelte";
  import { Skeleton } from "$lib/components/ui/skeleton";

  let libraries = $state<CalibreLibraryInfo[]>([]);
  let loading = $state(true);
  let linkingPath = $state<string | null>(null);
  let linkName = $state("");
  let syncStatuses = $state<Record<string, CalibreLibraryStatus>>({});
  let pollingIntervals = $state<Record<string, ReturnType<typeof setInterval>>>(
    {},
  );

  onMount(() => {
    void loadLibraries();

    return () => {
      // Cleanup polling intervals
      Object.values(pollingIntervals).forEach(clearInterval);
    };
  });

  async function loadLibraries() {
    loading = true;
    try {
      libraries = await adminApi.getCalibreLibraries();
      // Load status for linked libraries
      for (const lib of libraries) {
        if (lib.linked && lib.library_id) {
          await loadStatus(lib.library_id);
        }
      }
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function loadStatus(libraryId: string) {
    try {
      const status = await adminApi.getCalibreLibraryStatus(libraryId);
      syncStatuses[libraryId] = status;
      // If sync is running, start polling
      if (status.sync?.status === "running") {
        startPolling(libraryId);
      }
    } catch (e) {
      // ignore
    }
  }

  function startPolling(libraryId: string) {
    if (pollingIntervals[libraryId]) return;
    pollingIntervals[libraryId] = setInterval(async () => {
      try {
        const status = await adminApi.getCalibreLibraryStatus(libraryId);
        syncStatuses[libraryId] = status;
        if (status.sync?.status !== "running") {
          clearInterval(pollingIntervals[libraryId]);
          delete pollingIntervals[libraryId];
          // Refresh library list to update counts
          await loadLibraries();
        }
      } catch {
        clearInterval(pollingIntervals[libraryId]);
        delete pollingIntervals[libraryId];
      }
    }, 2000);
  }

  async function handleLink(path: string) {
    const name = linkName || path.split("/").pop() || "Calibre";
    try {
      const result = await adminApi.linkCalibreLibrary({
        calibre_path: path,
        name,
      });
      toastStore.success(`Library "${name}" linked and sync started`);
      linkingPath = null;
      linkName = "";
      await loadLibraries();
      if (result.library_id) {
        startPolling(result.library_id);
      }
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleSync(libraryId: string) {
    try {
      await adminApi.syncCalibreLibrary(libraryId);
      toastStore.success("Sync started");
      startPolling(libraryId);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>Calibre Import - Admin - BeePub</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
  <div class="mb-8">
    <a
      href="/admin"
      class="text-muted-foreground hover:text-foreground text-sm mb-1 inline-block"
    >
      ← Admin
    </a>
    <h1 class="text-3xl font-bold text-foreground">Calibre Import</h1>
    <p class="text-muted-foreground mt-1">
      Link and sync Calibre libraries (read-only)
    </p>
  </div>

  {#if loading}
    <div role="status" aria-label="Loading" class="space-y-3">
      {#each Array(6) as _}
        <div class="bg-card card-soft rounded-2xl p-5">
          <div class="flex items-center gap-4">
            <Skeleton class="w-10 h-10 rounded-xl shrink-0" />
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-1">
                <Skeleton class="h-5 w-32" />
                <Skeleton class="h-5 w-14 rounded-full" />
              </div>
              <Skeleton class="h-4 w-3/4" />
            </div>
          </div>
        </div>
      {/each}
    </div>
  {:else if libraries.length === 0}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      <HardDrive class="mx-auto text-muted-foreground/40 mb-3" size={48} />
      <p class="text-muted-foreground text-lg">No Calibre libraries found</p>
      <p class="text-muted-foreground/70 text-sm mt-1">
        Mount a Calibre library to <code>/calibre/</code> in the backend container.
      </p>
    </div>
  {:else}
    <div class="space-y-4">
      {#each libraries as lib}
        {@const status = lib.library_id ? syncStatuses[lib.library_id] : null}
        {@const syncInfo = status?.sync}
        <div class="bg-card card-soft rounded-2xl p-5">
          <div
            class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4"
          >
            <div class="flex items-center gap-3.5 min-w-0 w-full sm:w-auto">
              <div
                class="w-10 h-10 rounded-xl flex-shrink-0 flex items-center justify-center {lib.linked
                  ? 'bg-primary/15 text-primary'
                  : 'bg-secondary text-muted-foreground'}"
              >
                <HardDrive size={18} />
              </div>
              <div class="min-w-0">
                <p class="font-semibold text-foreground">
                  {lib.library_name || lib.name}
                  {#if lib.linked}
                    <span
                      class="ml-2 text-xs bg-primary/10 text-primary px-2 py-0.5 rounded-full"
                    >
                      Linked
                    </span>
                  {/if}
                </p>
                <p class="text-muted-foreground text-sm break-words">
                  {lib.path}
                  {#if lib.calibre_book_count !== null}
                    &middot; {lib.calibre_book_count} EPUBs in Calibre
                  {/if}
                  {#if status}
                    &middot; {status.imported_book_count} imported
                  {/if}
                </p>
              </div>
            </div>

            <div
              class="flex items-center gap-2 w-full sm:w-auto sm:justify-end"
            >
              {#if lib.linked && lib.library_id}
                <Button
                  variant="outline"
                  size="sm"
                  class="rounded-xl whitespace-nowrap"
                  disabled={syncInfo?.status === "running"}
                  onclick={() => handleSync(lib.library_id!)}
                >
                  <RefreshCw
                    size={14}
                    class={syncInfo?.status === "running" ? "animate-spin" : ""}
                  />
                  Re-sync
                </Button>
              {:else}
                <Button
                  size="sm"
                  class="rounded-xl whitespace-nowrap"
                  onclick={() => {
                    linkingPath = lib.path;
                    linkName = lib.name;
                  }}
                >
                  <Link size={14} />
                  Link
                </Button>
              {/if}
            </div>
          </div>

          <!-- Sync progress -->
          {#if syncInfo}
            <div class="mt-4 pt-4 border-t border-border">
              {#if syncInfo.status === "running"}
                <div
                  class="flex items-center gap-2 text-sm text-muted-foreground mb-2"
                >
                  <LoaderCircle size={14} class="animate-spin" />
                  Syncing... {syncInfo.processed} / {syncInfo.total}
                </div>
                <div class="w-full bg-secondary rounded-full h-2">
                  <div
                    class="bg-primary h-2 rounded-full transition-all duration-300"
                    style="width: {syncInfo.total > 0
                      ? (syncInfo.processed / syncInfo.total) * 100
                      : 0}%"
                  ></div>
                </div>
              {:else if syncInfo.status === "completed"}
                <div class="flex items-center gap-2 text-sm text-green-600">
                  <CircleCheck size={14} />
                  Sync completed: {syncInfo.added} added, {syncInfo.updated} updated,
                  {syncInfo.unchanged} unchanged
                  {#if syncInfo.skipped > 0}
                    , {syncInfo.skipped} skipped
                  {/if}
                </div>
              {:else if syncInfo.status === "failed"}
                <div class="flex items-center gap-2 text-sm text-destructive">
                  <CircleAlert size={14} />
                  Sync failed
                </div>
              {/if}
              {#if syncInfo.errors.length > 0}
                <div class="mt-2 space-y-1">
                  {#each syncInfo.errors as error}
                    <p class="text-xs text-destructive/80">{error}</p>
                  {/each}
                </div>
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<!-- Link dialog (inline) -->
{#if linkingPath}
  <div
    class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
    role="dialog"
    tabindex="-1"
    aria-modal="true"
    onclick={(e) => {
      if (e.target === e.currentTarget) {
        linkingPath = null;
        linkName = "";
      }
    }}
    onkeydown={(e) => {
      if (e.key === "Escape") {
        linkingPath = null;
        linkName = "";
      }
    }}
  >
    <div class="bg-card rounded-2xl p-6 w-full max-w-md shadow-xl">
      <h2 class="text-lg font-semibold text-foreground mb-4">
        Link Calibre Library
      </h2>
      <p class="text-sm text-muted-foreground mb-4">{linkingPath}</p>
      <div class="space-y-3">
        <div class="space-y-1">
          <label
            class="block text-sm font-medium text-foreground"
            for="lib-name">Library Name</label
          >
          <Input id="lib-name" bind:value={linkName} class="rounded-xl" />
        </div>
        <div class="flex justify-end gap-2 pt-2">
          <Button
            variant="ghost"
            class="rounded-xl"
            onclick={() => {
              linkingPath = null;
              linkName = "";
            }}>Cancel</Button
          >
          <Button
            class="rounded-xl"
            disabled={!linkName}
            onclick={() => handleLink(linkingPath!)}>Link & Sync</Button
          >
        </div>
      </div>
    </div>
  </div>
{/if}
