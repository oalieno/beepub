<script lang="ts">
  /**
   * Upload books from the local library into this server library (app
   * only): the device's books that aren't on the server yet, picked and
   * sent together. A file the server already has is linked, not sent.
   */
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import Modal from "$lib/components/Modal.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import type { LocalBookEntry } from "$lib/services/localLibrary";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";

  let {
    open,
    libraryId,
    onclose,
    ondone,
  }: {
    open: boolean;
    libraryId: string;
    onclose: () => void;
    /** After at least one book reached the server. */
    ondone: () => void;
  } = $props();

  let entries = $state<LocalBookEntry[] | null>(null);
  let selected = $state<Record<string, boolean>>({});
  let uploading = $state(false);
  let done = $state(0);
  let chosen = $derived(entries?.filter((e) => selected[e.id]) ?? []);

  $effect(() => {
    if (!open) return;
    entries = null;
    selected = {};
    import("$lib/services/uploadLocal")
      .then(({ unlinkedLocalBooks }) => unlinkedLocalBooks())
      .then((list) => {
        // Every row bound from the start: a bindable prop can't bind to
        // an undefined entry.
        selected = Object.fromEntries(list.map((e) => [e.id, false]));
        entries = list;
      })
      .catch((e) => {
        entries = [];
        toastStore.error((e as Error).message);
      });
  });

  function close() {
    if (!uploading) onclose();
  }

  async function upload() {
    if (chosen.length === 0 || uploading) return;
    uploading = true;
    done = 0;
    let uploaded = 0;
    let linked = 0;
    const { uploadLocalBook } = await import("$lib/services/uploadLocal");
    for (const entry of chosen) {
      try {
        if ((await uploadLocalBook(entry, libraryId)) === "linked") linked++;
        else uploaded++;
      } catch (e) {
        toastStore.error(`${entry.title}: ${(e as Error).message}`);
      }
      done++;
    }
    uploading = false;
    if (uploaded > 0)
      toastStore.success(m.library_uploaded({ count: String(uploaded) }));
    if (linked > 0)
      toastStore.info(m.local_upload_linked({ count: String(linked) }));
    if (uploaded + linked > 0) ondone();
    onclose();
  }
</script>

<Modal title={m.local_upload_source_title()} {open} onclose={close}>
  <div class="space-y-4">
    {#if entries === null}
      <div class="flex justify-center py-8"><Spinner /></div>
    {:else if entries.length === 0}
      <p class="text-muted-foreground text-sm py-6 text-center">
        {m.local_upload_source_empty()}
      </p>
    {:else}
      <p class="text-muted-foreground text-sm">
        {m.local_upload_source_hint()}
      </p>
      <ul
        class="divide-y divide-border rounded-xl border border-border max-h-[50dvh] overflow-y-auto"
      >
        {#each entries as entry (entry.id)}
          <li>
            <label
              class="flex items-center gap-3 px-3 py-2.5 text-sm cursor-pointer"
            >
              <Checkbox
                bind:checked={selected[entry.id]}
                disabled={uploading}
              />
              <span class="flex-1 min-w-0">
                <span class="block truncate text-foreground">{entry.title}</span
                >
                {#if entry.authors.length}
                  <span class="block truncate text-muted-foreground text-xs"
                    >{entry.authors.join(", ")}</span
                  >
                {/if}
              </span>
            </label>
          </li>
        {/each}
      </ul>
    {/if}
    <div class="flex items-center justify-end gap-3">
      {#if uploading}
        <span class="flex items-center gap-2 text-primary text-sm">
          <Spinner size="sm" />
          {m.library_uploading_progress({
            done: String(done),
            total: String(chosen.length),
          })}
        </span>
      {/if}
      <Button
        class="rounded-xl"
        disabled={chosen.length === 0 || uploading}
        onclick={upload}
      >
        {m.library_upload_confirm({ count: String(chosen.length) })}
      </Button>
    </div>
  </div>
</Modal>
