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
  import type { IsbnCoverCandidate, IsbnSourceResult } from "$lib/types";

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
  let results = $state<IsbnSourceResult[]>([]);
  let covers = $state<IsbnCoverCandidate[]>([]);
  let selectedSource = $state<string | null>(null);
  let coverUrl = $state<string | null>(null);
  let coverLabel = $state<string | null>(null);
  let lookingUp = $state(false);
  let saving = $state(false);

  function reset() {
    isbn = "";
    title = "";
    authors = "";
    publisher = "";
    publishedDate = "";
    description = "";
    results = [];
    covers = [];
    selectedSource = null;
    coverUrl = null;
    coverLabel = null;
  }

  function applySource(result: IsbnSourceResult) {
    selectedSource = result.source;
    title = result.title ?? "";
    authors = result.authors.join(", ");
    publisher = result.publisher ?? "";
    publishedDate = result.published_date ?? "";
    description = result.description ?? "";
  }

  function selectCover(candidate: IsbnCoverCandidate) {
    coverUrl = candidate.url;
    coverLabel = candidate.label;
  }

  function dropCover(url: string) {
    // A candidate URL that 404s (e.g. the Open Library by-ISBN guess)
    // is removed instead of showing a broken image.
    covers = covers.filter((c) => c.url !== url);
    if (coverUrl === url) {
      if (covers.length > 0) {
        selectCover(covers[0]);
      } else {
        coverUrl = null;
        coverLabel = null;
      }
    }
  }

  async function handleLookup() {
    const query = isbn.trim();
    if (!query || lookingUp) return;
    lookingUp = true;
    try {
      const info = await booksApi.isbnLookup(query);
      results = info.results;
      covers = info.covers;
      selectedSource = null;
      coverUrl = null;
      coverLabel = null;
      if (info.results.length > 0) applySource(info.results[0]);
      if (info.covers.length > 0) selectCover(info.covers[0]);
      if (info.results.length === 0 && info.covers.length === 0) {
        toastStore.info(m.physical_isbn_not_found());
      }
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

    {#if results.length > 1}
      <div class="space-y-1.5">
        <span class="text-sm font-medium">{m.physical_lookup_source()}</span>
        <div class="flex flex-wrap gap-1.5">
          {#each results as result (result.source)}
            <button
              type="button"
              class="rounded-full border px-2.5 py-1 text-xs transition-colors {selectedSource ===
              result.source
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border text-muted-foreground hover:bg-secondary'}"
              onclick={() => applySource(result)}
            >
              {result.label}
            </button>
          {/each}
        </div>
      </div>
    {/if}

    {#if covers.length > 1}
      <div class="space-y-1.5">
        <span class="text-sm font-medium">{m.physical_cover_pick()}</span>
        <div class="flex flex-wrap gap-2">
          {#each covers as candidate (candidate.url)}
            <button
              type="button"
              class="overflow-hidden rounded-sm transition-opacity {coverUrl ===
              candidate.url
                ? 'ring-2 ring-primary'
                : 'opacity-60 hover:opacity-100'}"
              title={candidate.label}
              onclick={() => selectCover(candidate)}
            >
              <img
                src={candidate.url}
                alt={candidate.label}
                class="h-20 w-auto"
                onerror={() => dropCover(candidate.url)}
              />
            </button>
          {/each}
        </div>
      </div>
    {/if}

    <div class="flex gap-4">
      {#if coverUrl}
        <div class="shrink-0 space-y-1 self-start">
          <img
            src={coverUrl}
            alt=""
            class="w-20 rounded-sm book-shadow"
            onerror={() => dropCover(coverUrl!)}
          />
          {#if coverLabel}
            <p class="w-20 text-center text-xs text-muted-foreground">
              {m.physical_cover_from({ source: coverLabel })}
            </p>
          {/if}
        </div>
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
