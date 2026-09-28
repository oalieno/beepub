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
  import { uploadLocalBooks } from "$lib/services/uploadQueue";
  import * as m from "$lib/paraglide/messages.js";

  let {
    open,
    libraryId,
    onclose,
  }: {
    open: boolean;
    libraryId: string;
    onclose: () => void;
  } = $props();

  let entries = $state<LocalBookEntry[] | null>(null);
  let selected = $state<Record<string, boolean>>({});
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
    onclose();
  }

  // Runs in the background; the transfer panel reports each book and the
  // library page refreshes when they land.
  function upload() {
    if (chosen.length === 0) return;
    uploadLocalBooks(chosen, libraryId);
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
              <Checkbox bind:checked={selected[entry.id]} />
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
      <Button
        class="rounded-xl"
        disabled={chosen.length === 0}
        onclick={upload}
      >
        {m.library_upload_confirm({ count: String(chosen.length) })}
      </Button>
    </div>
  </div>
</Modal>
