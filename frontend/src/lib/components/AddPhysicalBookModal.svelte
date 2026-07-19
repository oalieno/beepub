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
  import type { IsbnSourceResult } from "$lib/types";

  // One row in the candidate list. ISBN/URL lookups already fetched the
  // full record per source; title-search rows carry a (source, ref)
  // pick resolved on click. Fine-tuning (other covers, per-field
  // sources) is the edit-metadata modal's job.
  interface CandidateRow {
    key: string;
    source: string;
    label: string;
    title: string;
    authors: string[];
    publisher: string | null;
    publishedDate: string | null;
    coverUrl: string | null;
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

  let step = $state<1 | 2>(1);
  let lookupQuery = $state("");
  let lookingUp = $state(false);
  let candidates = $state<CandidateRow[]>([]);
  let pendingKey = $state<string | null>(null);
  let sourceFilter = $state<string | null>(null);

  let isbn = $state("");
  let title = $state("");
  let authors = $state("");
  let publisher = $state("");
  let publishedDate = $state("");
  let description = $state("");
  let coverUrl = $state<string | null>(null);
  let saving = $state(false);

  // The clue the candidates were searched with — a pick echoes it so
  // the source can rebuild its search-side context (google's merge).
  let queryTitle = "";

  const sourcePills = $derived.by(() => {
    const counts = new Map<string, { label: string; count: number }>();
    for (const row of candidates) {
      const entry = counts.get(row.source);
      if (entry) {
        entry.count += 1;
      } else {
        counts.set(row.source, { label: row.label, count: 1 });
      }
    }
    return [...counts.entries()].map(([source, v]) => ({ source, ...v }));
  });
  const visibleCandidates = $derived(
    sourceFilter
      ? candidates.filter((row) => row.source === sourceFilter)
      : candidates,
  );

  function reset() {
    step = 1;
    lookupQuery = "";
    candidates = [];
    pendingKey = null;
    sourceFilter = null;
    isbn = "";
    title = "";
    authors = "";
    publisher = "";
    publishedDate = "";
    description = "";
    coverUrl = null;
    queryTitle = "";
  }

  // Closing the modal (X, cancel, backdrop) always starts over — a
  // reopened form stuck mid-flow reads as a bug, not a convenience.
  function handleClose() {
    reset();
    onclose();
  }

  function metaLine(row: CandidateRow): string {
    // Self-published rows repeat the author as publisher — say it once.
    const publisher =
      row.publisher && !row.authors.includes(row.publisher)
        ? row.publisher
        : null;
    return [publisher, row.publishedDate?.slice(0, 4), row.label]
      .filter(Boolean)
      .join(" · ");
  }

  function applyRecord(record: IsbnSourceResult) {
    title = record.title ?? "";
    authors = record.authors.join(", ");
    publisher = record.publisher ?? "";
    publishedDate = record.published_date ?? "";
    description = record.description ?? "";
    // The picked source's cover or none — never another source's
    // (mixing sources silently is the edit-metadata feature's call).
    coverUrl = record.cover_url;
    step = 2;
  }

  async function pick(row: CandidateRow) {
    if (pendingKey) return;
    if (row.record) {
      applyRecord(row.record);
      return;
    }
    pendingKey = row.key;
    try {
      const info = await booksApi.metadataLookup({
        source: row.source,
        ref: row.ref,
        ...(queryTitle ? { title: queryTitle } : {}),
      });
      if (info.results.length > 0) {
        applyRecord(info.results[0]);
      } else {
        toastStore.info(m.physical_isbn_not_found());
      }
    } catch {
      toastStore.info(m.physical_isbn_not_found());
    } finally {
      pendingKey = null;
    }
  }

  function manualEntry() {
    // Carry over what the search box already told us.
    if (queryTitle && !title.trim()) title = queryTitle;
    step = 2;
  }

  async function handleLookup() {
    const raw = lookupQuery.trim();
    if (!raw || lookingUp) return;

    lookingUp = true;
    candidates = [];
    sourceFilter = null;
    queryTitle = "";
    try {
      // One input, three clue kinds: URL, ISBN (10/13 digits, dashes
      // tolerated), or a title.
      const compact = raw.replace(/[-\s]/g, "");
      if (/^https?:\/\//i.test(raw)) {
        await lookupDirect({ url: raw });
      } else if (/^(\d{13}|\d{9}[\dXx])$/.test(compact)) {
        isbn = compact;
        await lookupDirect({ isbn: compact });
      } else {
        queryTitle = raw;
        const found = await booksApi.metadataSearch({ title: raw });
        candidates = found.candidates.map((c, i) => ({
          key: `${c.source}:${i}`,
          source: c.source,
          label: c.label,
          title: c.title,
          authors: c.authors,
          publisher: c.publisher,
          publishedDate: c.published_date,
          coverUrl: c.cover_url,
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
    candidates = withTitle.map((r, i) => ({
      key: `${r.source}:${i}`,
      source: r.source,
      label: r.label,
      title: r.title ?? "",
      authors: r.authors,
      publisher: r.publisher,
      publishedDate: r.published_date,
      coverUrl: r.cover_url,
      record: r,
    }));
    if (candidates.length === 1) {
      applyRecord(candidates[0].record!);
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

<Modal title={m.physical_add()} {open} onclose={handleClose}>
  {#if step === 1}
    <div class="space-y-4">
      <p class="text-sm text-muted-foreground">
        {m.physical_step_search()}
        {#if libraryName}
          · {m.physical_add_to_library({ name: libraryName })}
        {/if}
      </p>

      <div class="flex gap-2">
        <Input
          id="physical-lookup"
          bind:value={lookupQuery}
          placeholder={m.physical_lookup_label()}
          autocomplete="off"
          spellcheck={false}
          class="flex-1"
          onkeydown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleLookup();
            }
          }}
        />
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
        {#if sourcePills.length > 1}
          <div class="flex flex-wrap gap-1.5">
            <button
              type="button"
              class="rounded-full border px-2.5 py-1 text-xs transition-colors {sourceFilter ===
              null
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border text-muted-foreground hover:bg-secondary'}"
              onclick={() => (sourceFilter = null)}
            >
              {m.physical_filter_all({ count: candidates.length })}
            </button>
            {#each sourcePills as pill (pill.source)}
              <button
                type="button"
                class="rounded-full border px-2.5 py-1 text-xs transition-colors {sourceFilter ===
                pill.source
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border text-muted-foreground hover:bg-secondary'}"
                onclick={() => (sourceFilter = pill.source)}
              >
                {m.physical_source_count({
                  label: pill.label,
                  count: pill.count,
                })}
              </button>
            {/each}
          </div>
        {/if}

        <!-- max-h deliberately cuts a row mid-height: the partial row is
             the scroll cue (a clean 4-row fit reads as "that's all"). -->
        <div class="max-h-80 space-y-0.5 overflow-y-auto rounded-md border p-1">
          {#each visibleCandidates as row (row.key)}
            <button
              type="button"
              class="w-full rounded-sm px-2 py-1.5 text-left transition-colors {pendingKey ===
              row.key
                ? 'bg-primary/10'
                : 'hover:bg-secondary'}"
              title={row.title}
              disabled={pendingKey !== null}
              onclick={() => pick(row)}
            >
              <div class="flex items-center gap-2.5">
                <div
                  class="h-14 w-9 shrink-0 overflow-hidden rounded-sm bg-muted"
                >
                  {#if row.coverUrl}
                    <img
                      src={row.coverUrl}
                      alt=""
                      loading="lazy"
                      class="h-full w-full object-cover"
                      onerror={(e) =>
                        ((e.currentTarget as HTMLImageElement).style.display =
                          "none")}
                    />
                  {/if}
                </div>
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm text-foreground">{row.title}</p>
                  {#if row.authors.length > 0}
                    <p class="truncate text-xs text-muted-foreground">
                      {row.authors.join(", ")}
                    </p>
                  {/if}
                  {#if metaLine(row)}
                    <p class="truncate text-xs text-muted-foreground">
                      {metaLine(row)}
                    </p>
                  {/if}
                </div>
                {#if pendingKey === row.key}
                  <Spinner size="sm" />
                {/if}
              </div>
            </button>
          {/each}
        </div>
      {/if}

      <div class="pt-1">
        <button
          type="button"
          class="text-sm text-primary hover:underline"
          onclick={manualEntry}
        >
          {m.physical_manual_entry()} →
        </button>
      </div>
    </div>
  {:else}
    <form
      class="space-y-4"
      onsubmit={(e) => {
        e.preventDefault();
        handleSubmit();
      }}
    >
      <p class="text-sm text-muted-foreground">{m.physical_step_confirm()}</p>

      <div class="flex gap-5">
        {#if coverUrl}
          <img
            src={coverUrl}
            alt=""
            class="w-36 self-start rounded-sm book-shadow"
            onerror={() => (coverUrl = null)}
          />
        {/if}
        <div class="min-w-0 flex-1 space-y-4">
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
              <Input
                id="physical-date"
                bind:value={publishedDate}
                placeholder="YYYY-MM-DD"
              />
            </div>
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
              placeholder="9789571234567"
              class="max-w-56"
            />
          </div>
        </div>
      </div>

      <div class="space-y-1.5">
        <Label for="physical-description" class="text-sm font-medium">
          {m.metadata_field_description()}
        </Label>
        <Textarea id="physical-description" bind:value={description} rows={4} />
      </div>

      <div class="flex items-center justify-between gap-2 pt-1">
        <button
          type="button"
          class="text-sm text-primary hover:underline"
          onclick={() => (step = 1)}
        >
          ← {m.physical_reselect()}
        </button>
        <div class="flex gap-2">
          <Button type="button" variant="ghost" onclick={handleClose}>
            {m.common_cancel()}
          </Button>
          <Button type="submit" disabled={saving || !title.trim()}>
            {saving ? m.physical_creating() : m.physical_add()}
          </Button>
        </div>
      </div>
    </form>
  {/if}
</Modal>
