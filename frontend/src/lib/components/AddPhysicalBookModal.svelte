<script lang="ts">
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";
  import { Search } from "@lucide/svelte";
  import Modal from "$lib/components/Modal.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Textarea } from "$lib/components/ui/textarea";

  let {
    open,
    libraryId,
    libraryName = "",
    onclose,
    oncreated,
  }: {
    open: boolean;
    libraryId: string;
    libraryName?: string;
    onclose: () => void;
    oncreated: () => void;
  } = $props();

  let isbn = $state("");
  let title = $state("");
  let authors = $state("");
  let publisher = $state("");
  let publishedDate = $state("");
  let description = $state("");
  let coverUrl = $state<string | null>(null);
  let lookingUp = $state(false);
  let saving = $state(false);

  function reset() {
    isbn = "";
    title = "";
    authors = "";
    publisher = "";
    publishedDate = "";
    description = "";
    coverUrl = null;
  }

  async function handleLookup() {
    const query = isbn.trim();
    if (!query || lookingUp) return;
    lookingUp = true;
    try {
      const info = await booksApi.isbnLookup(query);
      title = info.title ?? title;
      authors = info.authors.length ? info.authors.join(", ") : authors;
      publisher = info.publisher ?? publisher;
      publishedDate = info.published_date ?? publishedDate;
      description = info.description ?? description;
      coverUrl = info.cover_url;
    } catch {
      toastStore.info(m.physical_isbn_not_found());
    } finally {
      lookingUp = false;
    }
  }

  async function handleSubmit() {
    if (!title.trim() || saving) return;
    saving = true;
    try {
      await booksApi.createPhysical({
        library_id: libraryId,
        title: title.trim(),
        authors: authors
          .split(",")
          .map((a) => a.trim())
          .filter(Boolean),
        publisher: publisher.trim() || null,
        published_date: publishedDate.trim() || null,
        description: description.trim() || null,
        isbn: isbn.trim() || null,
        cover_url: coverUrl,
      });
      toastStore.success(m.physical_created());
      reset();
      oncreated();
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      saving = false;
    }
  }
</script>

<Modal title={m.physical_add()} {open} {onclose}>
  <form
    class="space-y-4"
    onsubmit={(e) => {
      e.preventDefault();
      handleSubmit();
    }}
  >
    <p class="text-sm text-muted-foreground">
      {m.physical_add_hint()}
      {#if libraryName}
        {m.physical_add_to_library({ name: libraryName })}
      {/if}
    </p>

    <div class="flex items-end gap-2">
      <div class="flex-1 space-y-1.5">
        <Label for="physical-isbn" class="text-sm font-medium">
          {m.physical_isbn_placeholder()}
        </Label>
        <Input
          id="physical-isbn"
          bind:value={isbn}
          inputmode="numeric"
          autocomplete="off"
          spellcheck={false}
          onkeydown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleLookup();
            }
          }}
        />
      </div>
      <Button
        type="button"
        variant="outline"
        class="shrink-0"
        disabled={lookingUp || !isbn.trim()}
        onclick={handleLookup}
      >
        {#if lookingUp}
          <Spinner size="sm" />
        {:else}
          <Search size={14} />
        {/if}
        {m.physical_isbn_lookup()}
      </Button>
    </div>

    <div class="flex gap-4">
      {#if coverUrl}
        <!-- The by-ISBN Open Library cover URL 404s when no cover exists;
             drop the preview instead of showing a broken image. -->
        <img
          src={coverUrl}
          alt=""
          class="w-20 self-start rounded-sm book-shadow shrink-0"
          onerror={() => (coverUrl = null)}
        />
      {/if}
      <div class="flex-1 space-y-4 min-w-0">
        <div class="space-y-1.5">
          <Label for="physical-title" class="text-sm font-medium">
            {m.metadata_field_title()}
          </Label>
          <Input id="physical-title" bind:value={title} required />
        </div>
        <div class="space-y-1.5">
          <Label for="physical-authors" class="text-sm font-medium">
            {m.metadata_field_authors()}
          </Label>
          <Input id="physical-authors" bind:value={authors} />
        </div>
      </div>
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div class="space-y-1.5">
        <Label for="physical-publisher" class="text-sm font-medium">
          {m.metadata_field_publisher()}
        </Label>
        <Input id="physical-publisher" bind:value={publisher} />
      </div>
      <div class="space-y-1.5">
        <Label for="physical-date" class="text-sm font-medium">
          {m.metadata_field_published_date()}
        </Label>
        <Input id="physical-date" bind:value={publishedDate} />
      </div>
    </div>

    <div class="space-y-1.5">
      <Label for="physical-description" class="text-sm font-medium">
        {m.metadata_field_description()}
      </Label>
      <Textarea id="physical-description" bind:value={description} rows={3} />
    </div>

    <div class="flex justify-end gap-2 pt-1">
      <Button type="button" variant="ghost" onclick={onclose}>
        {m.common_cancel()}
      </Button>
      <Button type="submit" disabled={saving || !title.trim()}>
        {saving ? m.physical_creating() : m.physical_add()}
      </Button>
    </div>
  </form>
</Modal>
