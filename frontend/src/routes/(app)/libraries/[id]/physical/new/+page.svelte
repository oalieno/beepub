<script lang="ts">
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { onMount } from "svelte";
  import { booksApi } from "$lib/api/books";
  import { librariesApi } from "$lib/api/libraries";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";
  import { BookCopy, Search } from "@lucide/svelte";
  import BackButton from "$lib/components/BackButton.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Textarea } from "$lib/components/ui/textarea";
  import type { IsbnSourceResult } from "$lib/types";

  // The form is the destination; online sources are an autocomplete
  // that fills it. One row per search hit — ISBN/URL lookups already
  // fetched the full record per source, title-search rows carry a
  // (source, ref) pick resolved on click.
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

  const libraryId = $derived(page.params.id as string);
  let libraryName = $state("");

  let lookupQuery = $state("");
  let lookingUp = $state(false);
  let candidates = $state<CandidateRow[]>([]);
  let popoverOpen = $state(false);
  let pendingKey = $state<string | null>(null);
  let sourceFilter = $state<string | null>(null);
  let filledFrom = $state<string | null>(null);

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

  onMount(async () => {
    try {
      const library = await librariesApi.get(libraryId);
      libraryName = library.name;
    } catch {
      // Header just omits the library name; creating still works.
    }
  });

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

  function applyRecord(record: IsbnSourceResult, sourceLabel: string) {
    title = record.title ?? "";
    authors = record.authors.join(", ");
    publisher = record.publisher ?? "";
    publishedDate = record.published_date ?? "";
    description = record.description ?? "";
    // The picked source's cover or none — never another source's
    // (mixing sources is the edit-metadata feature's call).
    coverUrl = record.cover_url;
    filledFrom = sourceLabel;
    popoverOpen = false;
  }

  async function pick(row: CandidateRow) {
    if (pendingKey) return;
    if (row.record) {
      applyRecord(row.record, row.label);
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
        applyRecord(info.results[0], row.label);
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
        popoverOpen = candidates.length > 0;
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
      applyRecord(candidates[0].record!, candidates[0].label);
    } else if (candidates.length === 0) {
      toastStore.info(m.physical_isbn_not_found());
    } else {
      popoverOpen = true;
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
      goto(`/libraries/${libraryId}`);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      saving = false;
    }
  }
</script>

<svelte:head>
  <title>{m.physical_add()} - BeePub</title>
</svelte:head>

<div class="mx-auto max-w-3xl px-4 py-6 sm:px-6 sm:py-10 pb-24">
  <BackButton
    href="/libraries/{libraryId}"
    label={libraryName || m.nav_library()}
  />

  <div class="mt-4 mb-6">
    <h1 class="text-2xl font-bold text-foreground">{m.physical_add()}</h1>
    {#if libraryName}
      <p class="mt-1 text-sm text-muted-foreground">
        {m.physical_add_to_library({ name: libraryName })}
      </p>
    {/if}
  </div>

  <!-- Autofill bar: search fills the form below; the form never waits
       for it — manual entry is just typing. -->
  <div class="relative mb-6">
    <div class="flex gap-2">
      <Input
        id="physical-lookup"
        bind:value={lookupQuery}
        placeholder={m.physical_autofill_hint()}
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

    {#if popoverOpen && candidates.length > 0}
      <!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
      <div
        class="fixed inset-0 z-10"
        onclick={() => (popoverOpen = false)}
      ></div>
      <div
        class="absolute inset-x-0 top-full z-20 mt-2 overflow-hidden rounded-md border bg-background shadow-lg"
      >
        {#if sourcePills.length > 1}
          <div class="flex flex-wrap gap-1.5 border-b p-2">
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
        <!-- max-h deliberately cuts a row mid-height: the partial row
             is the scroll cue. -->
        <div class="max-h-80 space-y-0.5 overflow-y-auto p-1">
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
      </div>
    {/if}

    {#if filledFrom}
      <p class="mt-2 text-xs text-muted-foreground">
        {m.physical_filled_from({ source: filledFrom })}
      </p>
    {/if}
  </div>

  <form
    class="space-y-5"
    onsubmit={(e) => {
      e.preventDefault();
      handleSubmit();
    }}
  >
    <div class="flex flex-col gap-6 sm:flex-row">
      {#if coverUrl}
        <img
          src={coverUrl}
          alt=""
          class="w-40 self-center rounded-sm book-shadow sm:self-start"
          onerror={() => (coverUrl = null)}
        />
      {:else}
        <div
          class="flex aspect-[2/3] w-40 shrink-0 items-center justify-center self-center rounded-md border-2 border-dashed border-border sm:self-start"
        >
          <BookCopy size={32} class="text-muted-foreground/40" />
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
      <Textarea id="physical-description" bind:value={description} rows={5} />
    </div>

    <div class="flex justify-end gap-2 pt-2">
      <Button
        type="button"
        variant="ghost"
        onclick={() => goto(`/libraries/${libraryId}`)}
      >
        {m.common_cancel()}
      </Button>
      <Button type="submit" disabled={saving || !title.trim()}>
        {saving ? m.physical_creating() : m.physical_add()}
      </Button>
    </div>
  </form>
</div>
