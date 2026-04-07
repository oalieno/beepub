<script lang="ts">
  import Modal from "$lib/components/Modal.svelte";
  import * as m from "$lib/paraglide/messages.js";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";

  let {
    bookId,
    initialNotes = "",
    open = $bindable(false),
    onsaved,
  }: {
    bookId: string;
    initialNotes: string;
    open: boolean;
    onsaved: (notes: string | null) => void;
  } = $props();

  let notesText = $state("");
  let saving = $state(false);

  $effect(() => {
    if (open) {
      notesText = initialNotes;
    }
  });

  async function handleSave() {
    saving = true;
    try {
      await booksApi.updateNotes(bookId, notesText || null);
      open = false;
      onsaved(notesText || null);
      toastStore.success(m.notes_saved());
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      saving = false;
    }
  }
</script>

<Modal title={m.notes_title()} {open} onclose={() => (open = false)}>
  <div class="space-y-4">
    <div class="space-y-1">
      <label class="block text-sm text-muted-foreground" for="notes-text"
        >{m.notes_markdown()}</label
      >
      <textarea
        id="notes-text"
        bind:value={notesText}
        rows={10}
        class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none font-mono text-sm"
        placeholder={m.notes_placeholder()}
      ></textarea>
    </div>
    <div class="flex justify-end gap-2 pt-2">
      <button
        class="px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
        onclick={() => (open = false)}>{m.common_cancel()}</button
      >
      <button
        class="px-5 py-2.5 text-sm bg-primary hover:bg-primary/90 text-primary-foreground font-semibold rounded-xl disabled:opacity-50"
        onclick={handleSave}
        disabled={saving}
      >
        {saving ? m.notes_saving() : m.common_save()}
      </button>
    </div>
  </div>
</Modal>
