<script lang="ts">
  import { onMount } from "svelte";
  import { adminApi } from "$lib/api/admin";
  import { toastStore } from "$lib/stores/toast";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import type {
    CalibreCopyPreview,
    CalibreLibraryInfo,
    CalibreLibraryStatus,
    CalibreSyncStatus,
  } from "$lib/types";
  import {
    HardDrive,
    HardDriveDownload,
    RefreshCw,
    Link,
    LoaderCircle,
  } from "@lucide/svelte";
  import Modal from "$lib/components/Modal.svelte";
  import BackButton from "$lib/components/BackButton.svelte";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import * as m from "$lib/paraglide/messages.js";

  let libraries = $state<CalibreLibraryInfo[]>([]);
  let loading = $state(true);
  let linkingPath = $state<string | null>(null);
  let linkName = $state("");
  let linkMode = $state<"sync" | "copy">("sync");
  // Copying a linked library in: the confirmation, then (files that
  // cannot be read) the choice to go ahead without them.
  let copyTarget = $state<{
    id: string;
    name: string;
    preview: CalibreCopyPreview;
  } | null>(null);
  let unreadable = $state<{
    id: string;
    name: string;
    titles: string[];
    count: number;
  } | null>(null);
  let copyBusy = $state(false);
  let syncStatuses = $state<Record<string, CalibreLibraryStatus>>({});
  let pollingIntervals = $state<Record<string, ReturnType<typeof setInterval>>>(
    {},
  );
  let calibreBaseDir = $state("/calibre");

  let linkedLibraries = $derived(libraries.filter((l) => l.linked));
  let unlinkedLibraries = $derived(libraries.filter((l) => !l.linked));
  let anySyncing = $derived(
    linkedLibraries.some((l) => {
      const s = l.library_id ? syncStatuses[l.library_id] : null;
      return s?.sync?.status === "running";
    }),
  );

  onMount(() => {
    void loadData();
    return () => {
      Object.values(pollingIntervals).forEach(clearInterval);
    };
  });

  async function loadData() {
    loading = true;
    try {
      const [libs, settings] = await Promise.all([
        adminApi.getCalibreLibraries(),
        adminApi.getSettings().catch(() => null),
      ]);
      libraries = libs;
      if (settings) {
        calibreBaseDir = settings.calibre_base_dir || "/calibre";
      }
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
      if (status.sync?.status === "running") {
        startPolling(libraryId);
      }
    } catch {
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
          if (status.sync?.mode === "copy")
            copyEnded(libraryId, status.library_name, status.sync);
          await loadData();
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
        mode: linkMode,
      });
      toastStore.success(m.admin_calibre_linked({ name }));
      linkingPath = null;
      linkName = "";
      linkMode = "sync";
      await loadData();
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
      startPolling(libraryId);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function formatBytes(bytes: number): string {
    if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(0)} MB`;
    return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  }

  // What the server leaves free after a copy (calibre.COPY_FREE_MARGIN).
  const FREE_MARGIN = 256 * 1024 * 1024;
  let copyFits = $derived(
    !copyTarget ||
      copyTarget.preview.bytes_needed + FREE_MARGIN <=
        copyTarget.preview.bytes_free,
  );

  async function openCopy(lib: CalibreLibraryInfo) {
    if (!lib.library_id) return;
    try {
      copyTarget = {
        id: lib.library_id,
        name: lib.library_name || lib.name,
        preview: await adminApi.previewCalibreCopy(lib.library_id),
      };
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function startCopy(id: string, skipUnreadable = false) {
    if (copyBusy) return;
    copyBusy = true;
    try {
      await adminApi.copyCalibreLibrary(id, skipUnreadable);
      copyTarget = null;
      unreadable = null;
      await loadStatus(id);
      startPolling(id);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      copyBusy = false;
    }
  }

  function copyEnded(id: string, name: string, sync: CalibreSyncStatus) {
    if (sync.status === "completed") {
      toastStore.success(m.admin_calibre_copied({ name }));
    } else if (sync.reason === "unreadable") {
      unreadable = {
        id,
        name,
        titles: sync.unreadable ?? [],
        count: sync.unreadable_count ?? 0,
      };
    } else {
      toastStore.error(copyFailure(sync));
    }
  }

  function copyFailure(sync: CalibreSyncStatus): string {
    if (sync.reason === "space")
      return m.admin_calibre_copy_no_space({
        size: formatBytes(sync.bytes_needed ?? 0),
        free: formatBytes(sync.bytes_free ?? 0),
      });
    if (sync.reason === "unreadable")
      return m.admin_calibre_unreadable_title({
        count: String(sync.unreadable_count ?? 0),
      });
    return m.admin_calibre_copy_failed({
      msg: sync.errors[0] ?? "Unknown error",
    });
  }

  async function handleSyncAll() {
    const targets = linkedLibraries.filter((l) => {
      const s = l.library_id ? syncStatuses[l.library_id] : null;
      return s?.sync?.status !== "running";
    });
    if (targets.length === 0) return;
    try {
      await Promise.all(
        targets.map((lib) => {
          const id = lib.library_id!;
          startPolling(id);
          return adminApi.syncCalibreLibrary(id);
        }),
      );
      toastStore.success(`Syncing ${targets.length} libraries`);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleToggleAutoSync(lib: CalibreLibraryInfo) {
    if (!lib.library_id) return;
    const newValue = !lib.auto_sync;
    lib.auto_sync = newValue;
    libraries = [...libraries];
    try {
      await adminApi.updateCalibreLibrary(lib.library_id, {
        auto_sync: newValue,
      });
    } catch (e) {
      lib.auto_sync = !newValue;
      libraries = [...libraries];
      toastStore.error((e as Error).message);
    }
  }

  function formatRelativeTime(isoString: string | null): string {
    if (!isoString) return "—";
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return m.admin_calibre_just_now();
    if (diffMin < 60)
      return m.admin_calibre_minutes_ago({ minutes: String(diffMin) });
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24)
      return m.admin_calibre_hours_ago({ hours: String(diffHours) });
    const diffDays = Math.floor(diffHours / 24);
    return m.admin_calibre_days_ago({ days: String(diffDays) });
  }

  function formatNumber(n: number | null): string {
    if (n === null) return "—";
    return n.toLocaleString();
  }

  function syncTooltip(
    syncInfo: import("$lib/types").CalibreSyncStatus | null | undefined,
  ): string | null {
    if (!syncInfo) return null;
    if (syncInfo.status === "completed") {
      let text: string = m.admin_calibre_sync_result({
        added: String(syncInfo.added),
        updated: String(syncInfo.updated),
        unchanged: String(syncInfo.unchanged),
      });
      if (syncInfo.skipped > 0)
        text += m.admin_calibre_sync_skipped({
          skipped: String(syncInfo.skipped),
        });
      return text;
    }
    if (syncInfo.status === "failed" && syncInfo.mode === "copy")
      return copyFailure(syncInfo);
    if (syncInfo.status === "failed") {
      const msg =
        syncInfo.errors.length > 0 ? syncInfo.errors[0] : "Unknown error";
      return m.admin_calibre_sync_failed({ msg });
    }
    return null;
  }
</script>

{#snippet copyButton(lib: CalibreLibraryInfo, running: boolean)}
  <button
    class="text-muted-foreground hover:text-foreground transition-colors disabled:opacity-30"
    disabled={running}
    onclick={() => openCopy(lib)}
    aria-label={m.admin_calibre_copy_action()}
    title={m.admin_calibre_copy_action()}
  >
    <HardDriveDownload size={16} />
  </button>
{/snippet}

<svelte:head>
  <title>{m.admin_calibre_title()}</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
  <div class="mb-8">
    <div class="mb-1">
      <BackButton href="/admin" label={m.nav_admin()} />
    </div>
    <h1 class="text-3xl font-bold text-foreground">
      {m.admin_calibre_heading()}
    </h1>
    <p class="text-muted-foreground mt-1">
      {m.admin_calibre_subtitle()}
    </p>
  </div>

  {#if loading}
    <div role="status" aria-label="Loading">
      <div class="bg-card card-soft rounded-2xl p-5">
        <div class="space-y-4">
          {#each Array(5) as _}
            <div class="flex items-center gap-4">
              <Skeleton class="h-5 w-28" />
              <Skeleton class="h-5 w-40 hidden sm:block" />
              <Skeleton class="h-5 w-16 ml-auto" />
              <Skeleton class="h-6 w-11 rounded-full" />
              <Skeleton class="h-5 w-5" />
            </div>
          {/each}
        </div>
      </div>
    </div>
  {:else if libraries.length === 0}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      <HardDrive class="mx-auto text-muted-foreground/40 mb-3" size={48} />
      <p class="text-muted-foreground text-lg">{m.admin_calibre_empty()}</p>
      <p class="text-muted-foreground/70 text-sm mt-1">
        {m.admin_calibre_empty_subtitle({ path: calibreBaseDir })}
      </p>
    </div>
  {:else}
    <!-- Header bar -->
    {#if linkedLibraries.length > 0}
      <div class="flex items-center justify-end gap-3 mb-5">
        <button
          class="text-sm font-medium text-primary hover:text-primary/80 transition-colors disabled:opacity-40 whitespace-nowrap"
          onclick={handleSyncAll}
          disabled={anySyncing}
        >
          {m.admin_calibre_sync_all()}
        </button>
      </div>
    {/if}

    <!-- Table -->
    <div class="bg-card card-soft rounded-2xl overflow-hidden">
      <!-- Desktop table header -->
      <div
        class="hidden sm:grid sm:grid-cols-[1fr_1fr_5rem_3.5rem_4.5rem_4rem] gap-x-4 items-center px-5 py-3 border-b border-border/50 text-xs font-medium text-muted-foreground uppercase tracking-wider"
      >
        <span>{m.admin_calibre_col_library()}</span>
        <span>{m.admin_calibre_col_path()}</span>
        <span class="text-right">{m.admin_calibre_col_books()}</span>
        <span class="text-center">{m.admin_calibre_col_auto()}</span>
        <span class="text-center">{m.admin_calibre_col_synced()}</span>
        <span></span>
      </div>

      <!-- Linked libraries -->
      {#each linkedLibraries as lib}
        {@const status = lib.library_id ? syncStatuses[lib.library_id] : null}
        {@const syncInfo = status?.sync}
        {@const tip = syncTooltip(syncInfo)}
        <div class="border-b border-border/30 last:border-b-0">
          <!-- Desktop row -->
          <div
            class="hidden sm:grid sm:grid-cols-[1fr_1fr_5rem_3.5rem_4.5rem_4rem] gap-x-4 items-center px-5 py-3.5"
          >
            <span class="text-sm font-medium text-foreground truncate">
              {lib.library_name || lib.name}
            </span>
            <span class="text-sm text-muted-foreground truncate">
              {lib.path}
            </span>
            <span class="text-sm text-foreground tabular-nums text-right">
              {formatNumber(lib.calibre_book_count)}
            </span>
            <div class="flex justify-center">
              <button
                class="relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors {lib.auto_sync
                  ? 'bg-primary'
                  : 'bg-secondary'}"
                onclick={() => handleToggleAutoSync(lib)}
                aria-label="Toggle auto-sync for {lib.library_name || lib.name}"
              >
                <span
                  class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform {lib.auto_sync
                    ? 'translate-x-6'
                    : 'translate-x-1'}"
                ></span>
              </button>
            </div>
            <span
              class="text-xs text-muted-foreground text-center whitespace-nowrap {syncInfo?.status ===
              'failed'
                ? 'text-destructive'
                : ''}"
              title={tip || undefined}
            >
              {formatRelativeTime(lib.last_synced_at)}
            </span>
            <div class="flex justify-end gap-3">
              {@render copyButton(lib, syncInfo?.status === "running")}
              <button
                class="text-muted-foreground hover:text-foreground transition-colors disabled:opacity-30"
                disabled={syncInfo?.status === "running"}
                onclick={() => handleSync(lib.library_id!)}
                aria-label="Sync {lib.library_name || lib.name}"
              >
                <RefreshCw
                  size={16}
                  class={syncInfo?.status === "running" ? "animate-spin" : ""}
                />
              </button>
            </div>
          </div>

          <!-- Mobile row -->
          <div
            class="sm:hidden flex items-center justify-between gap-3 px-5 py-3.5"
          >
            <div class="min-w-0">
              <p class="text-sm font-medium text-foreground truncate">
                {lib.library_name || lib.name}
              </p>
              <p class="text-xs text-muted-foreground">
                {formatNumber(lib.calibre_book_count)} books{#if lib.last_synced_at}
                  &middot; {formatRelativeTime(lib.last_synced_at)}{/if}
              </p>
            </div>
            <div class="flex items-center gap-3 shrink-0">
              <button
                class="relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors {lib.auto_sync
                  ? 'bg-primary'
                  : 'bg-secondary'}"
                onclick={() => handleToggleAutoSync(lib)}
                aria-label="Toggle auto-sync for {lib.library_name || lib.name}"
              >
                <span
                  class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform {lib.auto_sync
                    ? 'translate-x-6'
                    : 'translate-x-1'}"
                ></span>
              </button>
              {@render copyButton(lib, syncInfo?.status === "running")}
              <button
                class="text-muted-foreground hover:text-foreground transition-colors disabled:opacity-30"
                disabled={syncInfo?.status === "running"}
                onclick={() => handleSync(lib.library_id!)}
                aria-label="Sync {lib.library_name || lib.name}"
              >
                <RefreshCw
                  size={16}
                  class={syncInfo?.status === "running" ? "animate-spin" : ""}
                />
              </button>
            </div>
          </div>

          <!-- Sync progress bar (only when running) -->
          {#if syncInfo?.status === "running"}
            <div class="px-5 pb-3.5 -mt-1">
              <div
                class="flex items-center gap-2 text-xs text-muted-foreground mb-1.5"
              >
                <LoaderCircle size={12} class="animate-spin" />
                {(syncInfo.mode === "copy"
                  ? m.admin_calibre_copying
                  : m.admin_calibre_syncing)({
                  processed: String(syncInfo.processed),
                  total: String(syncInfo.total),
                })}
              </div>
              <div class="w-full bg-secondary rounded-full h-1.5">
                <div
                  class="bg-primary h-1.5 rounded-full transition-all duration-300"
                  style="width: {syncInfo.total > 0
                    ? (syncInfo.processed / syncInfo.total) * 100
                    : 0}%"
                ></div>
              </div>
            </div>
          {/if}
        </div>
      {/each}

      <!-- Unlinked libraries -->
      {#each unlinkedLibraries as lib}
        <div class="border-b border-border/30 last:border-b-0">
          <!-- Desktop -->
          <div
            class="hidden sm:grid sm:grid-cols-[1fr_1fr_5rem_3.5rem_4.5rem_4rem] gap-x-4 items-center px-5 py-3.5"
          >
            <span class="text-sm text-muted-foreground truncate"
              >{lib.name}</span
            >
            <span class="text-sm text-muted-foreground/60 truncate"
              >{lib.path}</span
            >
            <span class="text-sm text-muted-foreground tabular-nums text-right">
              {formatNumber(lib.calibre_book_count)}
            </span>
            <div></div>
            <div></div>
            <div class="flex justify-center">
              <button
                class="text-muted-foreground hover:text-primary transition-colors"
                onclick={() => {
                  linkingPath = lib.path;
                  linkName = lib.name;
                }}
                aria-label="Link {lib.name}"
              >
                <Link size={16} />
              </button>
            </div>
          </div>
          <!-- Mobile -->
          <div
            class="sm:hidden flex items-center justify-between gap-3 px-5 py-3.5"
          >
            <div class="min-w-0">
              <p class="text-sm text-muted-foreground truncate">{lib.name}</p>
              <p class="text-xs text-muted-foreground/60">
                {formatNumber(lib.calibre_book_count)} books
              </p>
            </div>
            <Button
              size="sm"
              variant="outline"
              class="rounded-xl shrink-0"
              onclick={() => {
                linkingPath = lib.path;
                linkName = lib.name;
              }}
            >
              <Link size={14} />
              Link
            </Button>
          </div>
        </div>
      {/each}
    </div>

    {#if linkedLibraries.length > 0}
      <p class="text-xs text-muted-foreground mt-3">
        {m.admin_calibre_unchanged_note()}
      </p>
    {/if}
  {/if}
</div>

<!-- Link dialog -->
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
        {m.admin_calibre_link_title()}
      </h2>
      <p class="text-sm text-muted-foreground mb-4">{linkingPath}</p>
      <div class="space-y-3">
        <div class="space-y-1">
          <label
            class="block text-sm font-medium text-foreground"
            for="lib-name">{m.admin_calibre_link_name()}</label
          >
          <Input id="lib-name" bind:value={linkName} class="rounded-xl" />
        </div>
        <div class="space-y-2" role="radiogroup">
          {#each [["sync", m.admin_calibre_mode_sync, m.admin_calibre_mode_sync_hint], ["copy", m.admin_calibre_mode_copy, m.admin_calibre_mode_copy_hint]] as const as [mode, label, hint] (mode)}
            <button
              type="button"
              role="radio"
              aria-checked={linkMode === mode}
              class="w-full text-left rounded-xl border px-3.5 py-2.5 transition-colors {linkMode ===
              mode
                ? 'border-primary bg-primary/5'
                : 'border-border hover:bg-secondary/60'}"
              onclick={() => (linkMode = mode)}
            >
              <span class="block text-sm font-medium text-foreground"
                >{label()}</span
              >
              <span class="block text-xs text-muted-foreground mt-0.5"
                >{hint()}</span
              >
            </button>
          {/each}
        </div>
        <div class="flex justify-end gap-2 pt-2">
          <Button
            variant="ghost"
            class="rounded-xl"
            onclick={() => {
              linkingPath = null;
              linkName = "";
            }}>{m.common_cancel()}</Button
          >
          <Button
            class="rounded-xl"
            disabled={!linkName}
            onclick={() => handleLink(linkingPath!)}
            >{linkMode === "copy"
              ? m.admin_calibre_link_copy()
              : m.admin_calibre_link_sync()}</Button
          >
        </div>
      </div>
    </div>
  </div>
{/if}

<Modal
  title={copyTarget
    ? m.admin_calibre_copy_title({ name: copyTarget.name })
    : ""}
  open={copyTarget != null}
  onclose={() => (copyTarget = null)}
>
  {#if copyTarget}
    {@const preview = copyTarget.preview}
    <div class="space-y-4 text-sm">
      <p class="text-foreground leading-relaxed">
        {m.admin_calibre_copy_body({
          count: String(preview.book_count),
          size: formatBytes(preview.bytes_needed),
          free: formatBytes(preview.bytes_free),
        })}
      </p>
      {#if !copyFits}
        <p class="text-destructive" role="alert">
          {m.admin_calibre_copy_no_space({
            size: formatBytes(preview.bytes_needed),
            free: formatBytes(preview.bytes_free),
          })}
        </p>
      {/if}
      <div class="flex justify-end gap-2">
        <Button
          variant="ghost"
          class="rounded-xl"
          onclick={() => (copyTarget = null)}>{m.common_cancel()}</Button
        >
        <Button
          class="rounded-xl"
          disabled={copyBusy || !copyFits || preview.book_count === 0}
          onclick={() => startCopy(copyTarget!.id)}
          >{m.admin_calibre_copy_confirm({
            count: String(preview.book_count),
          })}</Button
        >
      </div>
    </div>
  {/if}
</Modal>

<Modal
  title={unreadable
    ? m.admin_calibre_unreadable_title({ count: String(unreadable.count) })
    : ""}
  open={unreadable != null}
  onclose={() => (unreadable = null)}
>
  {#if unreadable}
    <div class="space-y-4 text-sm">
      <p class="text-foreground leading-relaxed">
        {m.admin_calibre_unreadable_body()}
      </p>
      <ul
        class="rounded-xl border border-border max-h-56 overflow-y-auto divide-y divide-border/60"
      >
        {#each unreadable.titles as title, i (i)}
          <li class="px-3 py-1.5 truncate text-foreground">{title}</li>
        {/each}
        {#if unreadable.count > unreadable.titles.length}
          <li class="px-3 py-1.5 text-muted-foreground">
            {m.admin_calibre_unreadable_more({
              count: String(unreadable.count - unreadable.titles.length),
            })}
          </li>
        {/if}
      </ul>
      <div class="flex justify-end gap-2">
        <Button
          variant="ghost"
          class="rounded-xl"
          onclick={() => (unreadable = null)}>{m.common_cancel()}</Button
        >
        <Button
          variant="destructive"
          class="rounded-xl"
          disabled={copyBusy}
          onclick={() => startCopy(unreadable!.id, true)}
          >{m.admin_calibre_unreadable_skip()}</Button
        >
      </div>
    </div>
  {/if}
</Modal>
