<script lang="ts">
  /**
   * Books handed to the app by iOS ("Open in BeePub" from Files, the
   * share sheet, AirDrop). The device library takes them straight in;
   * from the server side the reader picks the library: this device's or
   * a server one. Either way the work runs in the transfer panel.
   */
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { isNative } from "$lib/platform";
  import { isLocalMode } from "$lib/api/client";
  import { librariesApi } from "$lib/api/libraries";
  import { authStore } from "$lib/stores/auth";
  import { activeLibrary } from "$lib/stores/activeLibrary";
  import { uploadFiles } from "$lib/services/uploadQueue";
  import {
    DEVICE_FORMATS,
    OPENED_FILE_EVENT,
    SERVER_FORMATS,
    hasFormat,
    importToDevice,
    takeOpenedFiles,
  } from "$lib/services/openedFiles";
  import { getLocale } from "$lib/paraglide/runtime.js";
  import Modal from "$lib/components/Modal.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import ZhConversionToggle from "$lib/components/ZhConversionToggle.svelte";
  import { Button } from "$lib/components/ui/button";
  import * as Select from "$lib/components/ui/select";
  import { UserRole, type LibraryOut, type UserOut } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";

  // Mode switches are a full page load; one read is enough.
  const localMode = isLocalMode();

  let files = $state<File[]>([]);
  let open = $state(false);
  // null while loading.
  let targets = $state<LibraryOut[] | null>(null);
  let target = $state<string | null>(null);
  let showZhToggle = $state(false);

  let deviceOk = $derived(
    files.length > 0 && files.every((f) => hasFormat(f, DEVICE_FORMATS)),
  );
  let hasTxt = $derived(
    files.some((f) => f.name.toLowerCase().endsWith(".txt")),
  );

  function fmtSize(bytes: number): string {
    if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }

  async function loadTargets() {
    targets = null;
    // The store can trail the layout data by a tick on a cold start.
    const user = $authStore.user ?? (page.data.user as UserOut | null);
    const canUpload = user?.role === UserRole.Admin || !!user?.can_upload;
    let list: LibraryOut[] = [];
    if (canUpload) {
      try {
        // Calibre libraries are read-only.
        list = (await librariesApi.list()).filter((l) => !l.calibre_path);
      } catch {
        list = [];
      }
    }
    const ids = list.map((l) => l.id);
    target = ids.includes($activeLibrary) ? $activeLibrary : (ids[0] ?? null);
    targets = list;
  }

  async function check() {
    const arrived = (await takeOpenedFiles()).filter((f) =>
      hasFormat(f, SERVER_FORMATS),
    );
    if (arrived.length === 0) return;
    if (localMode) {
      // One library, nothing to choose.
      importToDevice(arrived);
      return;
    }
    const wasOpen = open;
    files = [...files, ...arrived];
    if (!wasOpen) {
      // Decided when the dialog opens, like the upload dialog: switching
      // it off keeps the row until the dialog closes.
      showZhToggle =
        getLocale() === "zh-Hant" || !!$authStore.user?.upload_zh_conversion;
      open = true;
      void loadTargets();
    }
  }

  function close() {
    open = false;
    files = [];
  }

  function toDevice() {
    importToDevice([...files]);
    close();
  }

  function toServer() {
    if (!target) return;
    uploadFiles([...files], target);
    close();
  }

  onMount(() => {
    if (!isNative()) return;
    void check();
    const onEvent = () => void check();
    const onVisible = () => {
      if (document.visibilityState === "visible") void check();
    };
    window.addEventListener(OPENED_FILE_EVENT, onEvent);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener(OPENED_FILE_EVENT, onEvent);
      document.removeEventListener("visibilitychange", onVisible);
    };
  });
</script>

<Modal title={m.opened_file_title()} {open} onclose={close}>
  <div class="space-y-4">
    <ul class="divide-y divide-border rounded-xl border border-border">
      {#each files as file, i (i)}
        <li class="flex items-center gap-3 px-3 py-2 text-sm">
          <span class="flex-1 truncate" title={file.name}>{file.name}</span>
          <span class="text-muted-foreground tabular-nums shrink-0"
            >{fmtSize(file.size)}</span
          >
        </li>
      {/each}
    </ul>

    {#if targets === null}
      <div class="flex justify-center py-2"><Spinner /></div>
    {:else if targets.length === 0}
      <p class="text-muted-foreground text-sm">
        {m.opened_file_no_upload()}
      </p>
    {:else}
      {#if targets.length > 1}
        <div class="flex items-center gap-2 text-sm text-muted-foreground">
          <span class="shrink-0">{m.opened_file_library()}</span>
          <Select.Root
            type="single"
            value={target ?? undefined}
            onValueChange={(v) => v && (target = v)}
          >
            <Select.Trigger
              class="flex-1 min-w-0"
              aria-label={m.opened_file_library()}
            >
              <span class="truncate">
                {targets.find((l) => l.id === target)?.name ?? ""}
              </span>
            </Select.Trigger>
            <Select.Content>
              {#each targets as library (library.id)}
                <Select.Item value={library.id}>{library.name}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        </div>
      {/if}
      {#if showZhToggle && hasTxt}
        <ZhConversionToggle />
      {/if}
    {/if}

    <p class="text-muted-foreground text-xs">
      {deviceOk
        ? m.opened_file_device_hint()
        : m.opened_file_device_epub_only()}
    </p>

    <div class="flex flex-wrap items-center justify-end gap-3">
      {#if deviceOk}
        <Button variant="outline" class="rounded-xl" onclick={toDevice}>
          {m.opened_file_to_device()}
        </Button>
      {/if}
      {#if targets && targets.length > 0}
        <Button class="rounded-xl" disabled={!target} onclick={toServer}>
          {m.opened_file_to_server()}
        </Button>
      {/if}
    </div>
  </div>
</Modal>
