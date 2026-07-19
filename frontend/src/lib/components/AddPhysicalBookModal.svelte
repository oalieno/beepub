<script lang="ts">
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";
  import { ExternalLink, Search } from "@lucide/svelte";
  import Modal from "$lib/components/Modal.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Textarea } from "$lib/components/ui/textarea";
  import type { IsbnCoverCandidate, IsbnSourceResult } from "$lib/types";

  // One row in the candidate list. ISBN/URL lookups already fetched the
  // full record per source; title-search rows carry a (source, ref)
  // pick resolved on demand. Fine-tuning (other covers, per-field
  // sources) is the edit-metadata modal's job, not this form's.
  interface CandidateRow {
    key: string;
    source: string;
    label: string;
    title: string;
    authors: string[];
    url: string | null;
    ref?: string;
    record?: IsbnSourceResult;
  }

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

  let lookupQuery = $state("");
  let isbn = $state("");
  let title = $state("");
  let authors = $state("");
  let publisher = $state("");
  let publishedDate = $state("");
  let description = $state("");
  let candidates = $state<CandidateRow[]>([]);
  let selectedKey = $state<string | null>(null);
  let pendingKey = $state<string | null>(null);
  let coverUrl = $state<string | null>(null);
  let coverLabel = $state<string | null>(null);
  let lookingUp = $state(false);
  let saving = $state(false);
  // Cover-only degradations (books_tw/open_library) from an ISBN
  // fan-out: the fallback when the picked source has no cover.
  let lookupCovers: IsbnCoverCandidate[] = [];
  // The clues the candidates were searched with — a pick echoes them so
  // the source can rebuild its search-side context (google's merge).
  let queryTitle = "";
  let queryAuthor = "";

  function reset() {
    lookupQuery = "";
    isbn = "";
    title = "";
    authors = "";
    publisher = "";
    publishedDate = "";
    description = "";
    candidates = [];
    selectedKey = null;
    pendingKey = null;
    coverUrl = null;
    coverLabel = null;
    lookupCovers = [];
  }

  function applyRecord(row: CandidateRow, record: IsbnSourceResult) {
    selectedKey = row.key;
    title = record.title ?? "";
    authors = record.authors.join(", ");
    publisher = record.publisher ?? "";
    publishedDate = record.published_date ?? "";
    description = record.description ?? "";
    if (record.cover_url) {
      coverUrl = record.cover_url;
      coverLabel = row.label;
    } else if (lookupCovers.length > 0) {
      coverUrl = lookupCovers[0].url;
      coverLabel = lookupCovers[0].label;
    } else {
      coverUrl = null;
      coverLabel = null;
    }
  }

  function dropCover(url: string) {
    // A cover URL that 404s (e.g. the Open Library by-ISBN guess) falls
    // back to the next candidate instead of showing a broken image.
    lookupCovers = lookupCovers.filter((c) => c.url !== url);
    if (coverUrl === url) {
      if (lookupCovers.length > 0) {
        coverUrl = lookupCovers[0].url;
        coverLabel = lookupCovers[0].label;
      } else {
        coverUrl = null;
        coverLabel = null;
      }
    }
  }

  async function pick(row: CandidateRow) {
    if (pendingKey) return;
    if (row.record) {
      applyRecord(row, row.record);
      return;
    }
    pendingKey = row.key;
    try {
      const info = await booksApi.metadataLookup({
        source: row.source,
        ref: row.ref,
        ...(queryTitle ? { title: queryTitle } : {}),
        ...(queryAuthor ? { author: queryAuthor } : {}),
      });
      if (info.results.length > 0) {
        lookupCovers = info.covers.filter(
          (c) => c.url !== info.results[0].cover_url,
        );
        applyRecord(row, info.results[0]);
      } else {
        toastStore.info(m.physical_isbn_not_found());
      }
    } catch {
      toastStore.info(m.physical_isbn_not_found());
    } finally {
      pendingKey = null;
    }
  }

  async function handleLookup() {
    const raw = lookupQuery.trim();
    if (!raw || lookingUp) return;

    lookingUp = true;
    candidates = [];
    selectedKey = null;
    lookupCovers = [];
    queryTitle = "";
    queryAuthor = "";
    try {
      // One input, three clue kinds: URL, ISBN (10/13 digits, dashes
      // tolerated), or a title (the authors field joins as a hint).
      const compact = raw.replace(/[-\s]/g, "");
      if (/^https?:\/\//i.test(raw)) {
        await lookupDirect({ url: raw });
      } else if (/^(\d{13}|\d{9}[\dXx])$/.test(compact)) {
        isbn = compact;
        await lookupDirect({ isbn: compact });
      } else {
        queryTitle = raw;
        queryAuthor = authors.split(",")[0]?.trim() ?? "";
        const found = await booksApi.metadataSearch({
          title: queryTitle,
          ...(queryAuthor ? { author: queryAuthor } : {}),
        });
        candidates = found.candidates.map((c, i) => ({
          key: `${c.source}:${i}`,
          source: c.source,
          label: c.label,
          title: c.title,
          authors: c.authors,
          url: c.url,
          ref: c.ref,
        }));
        if (candidates.length === 0) {
          toastStore.info(m.physical_isbn_not_found());
        }
      }
    } catch {
      toastStore.info(m.physical_isbn_not_found());
    } finally {
      lookingUp = false;
    }
  }

  async function lookupDirect(params: { isbn?: string; url?: string }) {
    // Precise clues (ISBN, pasted URL) locate exactly — every source's
    // full record comes back in one call and rows carry it directly.
    const info = await booksApi.metadataLookup(params);
    const withTitle = info.results.filter((r) => r.title);
    lookupCovers = info.covers;
    candidates = withTitle.map((r, i) => ({
      key: `${r.source}:${i}`,
      source: r.source,
      label: r.label,
      title: r.title ?? "",
      authors: r.authors,
      url: null,
      record: r,
    }));
    if (candidates.length === 1) {
      pick(candidates[0]);
    } else if (candidates.length === 0) {
      toastStore.info(m.physical_isbn_not_found());
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
        <Label for="physical-lookup" class="text-sm font-medium">
          {m.physical_lookup_label()}
        </Label>
        <Input
          id="physical-lookup"
          bind:value={lookupQuery}
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
        disabled={lookingUp || !lookupQuery.trim()}
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

    {#if candidates.length > 0}
      <div class="space-y-1.5">
        <span class="text-sm font-medium">
          {m.physical_search_results({ count: candidates.length })}
        </span>
        <div class="max-h-56 space-y-0.5 overflow-y-auto rounded-md border p-1">
          {#each candidates as row (row.key)}
            <div class="flex items-center gap-1">
              <button
                type="button"
                class="min-w-0 flex-1 rounded-sm px-2.5 py-1.5 text-left transition-colors {selectedKey ===
                row.key
                  ? 'bg-primary/10'
                  : 'hover:bg-secondary'}"
                disabled={pendingKey !== null}
                onclick={() => pick(row)}
              >
                <div class="flex items-center gap-2">
                  <div class="min-w-0 flex-1">
                    <p class="truncate text-sm">{row.title}</p>
                    {#if row.authors.length > 0}
                      <p class="truncate text-xs text-muted-foreground">
                        {row.authors.join(", ")}
                      </p>
                    {/if}
                  </div>
                  {#if pendingKey === row.key}
                    <Spinner size="sm" />
                  {/if}
                  <span
                    class="shrink-0 rounded-full border px-2 py-0.5 text-xs text-muted-foreground"
                  >
                    {row.label}
                  </span>
                </div>
              </button>
              {#if row.url}
                <a
                  href={row.url}
                  target="_blank"
                  rel="noreferrer"
                  class="shrink-0 p-1.5 text-muted-foreground transition-colors hover:text-foreground"
                  title={row.url}
                >
                  <ExternalLink size={14} />
                </a>
              {/if}
            </div>
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
      <div class="space-y-1.5">
        <Label for="physical-isbn" class="text-sm font-medium">
          {m.metadata_label_isbn()}
        </Label>
        <Input
          id="physical-isbn"
          bind:value={isbn}
          inputmode="numeric"
          autocomplete="off"
          spellcheck={false}
        />
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
