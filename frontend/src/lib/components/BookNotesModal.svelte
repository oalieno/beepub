<script lang="ts">
  import Modal from "$lib/components/Modal.svelte";
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
      toastStore.success("Notes saved");
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      saving = false;
    }
  }
</script>

<Modal title="Notes" {open} onclose={() => (open = false)}>
  <div class="space-y-4">
    <div class="space-y-1">
      <label class="block text-sm text-muted-foreground" for="notes-text"
        >Markdown supported</label
      >
      <textarea
        id="notes-text"
        bind:value={notesText}
        rows={10}
        class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none font-mono text-sm"
        placeholder="Write your notes here..."
      ></textarea>
    </div>
    <div class="flex justify-end gap-2 pt-2">
      <button
        class="px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
        onclick={() => (open = false)}>Cancel</button
      >
      <button
        class="px-5 py-2.5 text-sm bg-primary hover:bg-primary/90 text-primary-foreground font-semibold rounded-xl disabled:opacity-50"
        onclick={handleSave}
        disabled={saving}
      >
        {saving ? "Saving..." : "Save"}
      </button>
    </div>
  </div>
</Modal>
