<script lang="ts">
  /**
   * Book notes for a device-local book — the same editor the server book
   * page has, saved into the device record and synced (stamped, LWW) once
   * the book is linked to a server copy. A page of its own rather than a
   * sheet: a fixed sheet jumps when the native keyboard resizes the view.
   */
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import BackButton from "$lib/components/BackButton.svelte";
  import BookNotesEditor from "$lib/components/BookNotesEditor.svelte";
  import { readLocalInteraction, setLocalNotes } from "$lib/reading/local";
  import { getLocalBook } from "$lib/services/localLibrary";
  import * as m from "$lib/paraglide/messages.js";

  let bookId = $derived(page.params.id as string);
  let title = $state("");
  let notes = $state<string | null>(null);
  let startEditing = $state(false);

  onMount(async () => {
    const entry = await getLocalBook(bookId);
    if (!entry) {
      await goto("/local", { replaceState: true });
      return;
    }
    title = entry.title;
    notes = (await readLocalInteraction(bookId))?.notes ?? "";
    // Nothing written yet: open straight into the editor.
    startEditing = !notes.trim();
  });

  async function save(value: string | null) {
    await setLocalNotes(bookId, value);
    void import("$lib/services/readingSync").then(({ syncLocalBook }) =>
      syncLocalBook(bookId).catch(() => {}),
    );
  }
</script>

<svelte:head>
  <title>{title ? `${m.notes_title()} · ${title}` : m.notes_title()}</title>
</svelte:head>

<div class="max-w-3xl mx-auto px-6 sm:px-8 py-6 pb-24 md:pb-6">
  <div class="mb-6 -ml-1">
    <BackButton
      href="/local"
      label={m.common_back()}
      onclick={() => history.back()}
    />
  </div>

  {#if notes !== null}
    <p class="text-sm text-muted-foreground mb-2 line-clamp-2">{title}</p>
    <BookNotesEditor
      {bookId}
      initialNotes={notes}
      saveFn={save}
      bind:startEditing
    />
  {/if}
</div>
