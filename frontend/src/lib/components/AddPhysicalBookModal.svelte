<script lang="ts">
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";
  import {
    Check,
    ChevronDown,
    ChevronRight,
    ExternalLink,
    Search,
  } from "@lucide/svelte";
  import Modal from "$lib/components/Modal.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Textarea } from "$lib/components/ui/textarea";
  import type { IsbnCoverCandidate, IsbnSourceResult } from "$lib/types";

  // One row in the candidate list. ISBN/URL lookups already fetched the
  // full record per source; title-search rows carry a (source, ref)
  // pick resolved when the user commits with 下一步. Fine-tuning (other
  // covers, per-field sources) is the edit-metadata modal's job.
  interface CandidateRow {
    key: string;
    source: string;
    label: string;
    title: string;
    authors: string[];
    publisher: string | null;
    publishedDate: string | null;
    coverUrl: string | null;
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

  let step = $state<1 | 2>(1);
  let lookupQuery = $state("");
  let lookingUp = $state(false);
  let candidates = $state<CandidateRow[]>([]);
  let selectedKey = $state<string | null>(null);
  let pendingNext = $state(false);
  let sourceFilter = $state<string | null>(null);

  let isbn = $state("");
  let title = $state("");
  let authors = $state("");
  let publisher = $state("");
  let publishedDate = $state("");
  let description = $state("");
  let coverUrl = $state<string | null>(null);
  let coverLabel = $state<string | null>(null);
  let moreOpen = $state(false);
  let saving = $state(false);

  // Cover-only degradations (books_tw/open_library) from an ISBN
  // fan-out: the fallback when the picked source has no cover.
  let lookupCovers: IsbnCoverCandidate[] = [];
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
  const selectedRow = $derived(
    candidates.find((row) => row.key === selectedKey) ?? null,
  );

  function reset() {
    step = 1;
    lookupQuery = "";
    candidates = [];
    selectedKey = null;
    sourceFilter = null;
    isbn = "";
    title = "";
    authors = "";
    publisher = "";
    publishedDate = "";
    description = "";
    coverUrl = null;
    coverLabel = null;
    moreOpen = false;
    lookupCovers = [];
    queryTitle = "";
  }

  function metaLine(row: CandidateRow): string {
    return [row.publisher, row.publishedDate?.slice(0, 4), row.label]
      .filter(Boolean)
      .join(" · ");
  }

  function applyRecord(row: CandidateRow, record: IsbnSourceResult) {
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
    moreOpen = Boolean(description.trim() || isbn.trim());
    step = 2;
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

  async function goNext() {
    const row = selectedRow;
    if (!row || pendingNext) return;
    if (row.record) {
      applyRecord(row, row.record);
      return;
    }
    pendingNext = true;
    try {
      const info = await booksApi.metadataLookup({
        source: row.source,
        ref: row.ref,
        ...(queryTitle ? { title: queryTitle } : {}),
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
      pendingNext = false;
    }
  }

  function manualEntry() {
    // Carry over what the search box already told us.
    if (queryTitle && !title.trim()) title = queryTitle;
    selectedKey = null;
    step = 2;
    moreOpen = true;
  }

  async function handleLookup() {
    const raw = lookupQuery.trim();
    if (!raw || lookingUp) return;

    lookingUp = true;
    candidates = [];
    selectedKey = null;
    sourceFilter = null;
    lookupCovers = [];
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
          url: c.url,
          ref: c.ref,
        }));
        if (candidates.length === 0) {
          toastStore.info(m.physical_isbn_not_found());
        } else {
          selectedKey = candidates[0].key;
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
      publisher: r.publisher,
      publishedDate: r.published_date,
      coverUrl: r.cover_url,
      url: null,
      record: r,
    }));
    if (candidates.length === 1) {
      selectedKey = candidates[0].key;
      applyRecord(candidates[0], candidates[0].record!);
    } else if (candidates.length === 0) {
      toastStore.info(m.physical_isbn_not_found());
    } else {
      selectedKey = candidates[0].key;
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
              {m.physical_filter_all()}（{candidates.length}）
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
                {pill.label}（{pill.count}）
              </button>
            {/each}
          </div>
        {/if}

        <div class="max-h-72 space-y-0.5 overflow-y-auto rounded-md border p-1">
          {#each visibleCandidates as row (row.key)}
            <div class="flex items-center gap-1">
              <button
                type="button"
                class="min-w-0 flex-1 rounded-sm px-2 py-1.5 text-left transition-colors {selectedKey ===
                row.key
                  ? 'bg-primary/10'
                  : 'hover:bg-secondary'}"
                onclick={() => (selectedKey = row.key)}
                ondblclick={goNext}
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
                      <p class="truncate text-xs text-muted-foreground/80">
                        {metaLine(row)}
                      </p>
                    {/if}
                  </div>
                  {#if selectedKey === row.key}
                    <Check size={16} class="shrink-0 text-primary" />
                  {/if}
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
      {/if}

      <div class="flex items-center justify-between gap-2 pt-1">
        <button
          type="button"
          class="text-sm text-primary hover:underline"
          onclick={manualEntry}
        >
          {m.physical_manual_entry()} →
        </button>
        {#if candidates.length > 0}
          <Button
            type="button"
            disabled={!selectedRow || pendingNext}
            onclick={goNext}
          >
            {#if pendingNext}
              <Spinner size="sm" />
            {/if}
            {m.physical_next()}
          </Button>
        {/if}
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

      <div class="flex gap-4">
        {#if coverUrl}
          <div class="shrink-0 space-y-1 self-start">
            <img
              src={coverUrl}
              alt=""
              class="w-24 rounded-sm book-shadow"
              onerror={() => dropCover(coverUrl!)}
            />
            {#if coverLabel}
              <p class="w-24 text-center text-xs text-muted-foreground">
                {m.physical_cover_from({ source: coverLabel })}
              </p>
            {/if}
          </div>
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
              <Input id="physical-date" bind:value={publishedDate} />
            </div>
          </div>
        </div>
      </div>

      <button
        type="button"
        class="flex items-center gap-1 text-sm font-medium text-foreground"
        onclick={() => (moreOpen = !moreOpen)}
      >
        {#if moreOpen}
          <ChevronDown size={14} />
        {:else}
          <ChevronRight size={14} />
        {/if}
        {m.physical_more_fields()}
      </button>

      {#if moreOpen}
        <div class="space-y-4">
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
              class="max-w-56"
            />
          </div>
          <div class="space-y-1.5">
            <Label for="physical-description" class="text-sm font-medium">
              {m.metadata_field_description()}
            </Label>
            <Textarea
              id="physical-description"
              bind:value={description}
              rows={3}
            />
          </div>
        </div>
      {/if}

      <div class="flex items-center justify-between gap-2 pt-1">
        <button
          type="button"
          class="text-sm text-primary hover:underline"
          onclick={() => (step = 1)}
        >
          ← {m.physical_reselect()}
        </button>
        <div class="flex gap-2">
          <Button type="button" variant="ghost" onclick={onclose}>
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
