<script lang="ts">
  import * as m from "$lib/paraglide/messages.js";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import { Search } from "@lucide/svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { Input } from "$lib/components/ui/input";
  import { Button } from "$lib/components/ui/button";
  import type { IsbnSourceResult } from "$lib/types";

  // The search half of a versions dialog: one input, three clue kinds
  // (URL / ISBN / title). Fetched records are handed to the parent —
  // they become version cards there; nothing fills a field from here.
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
  }

  let {
    initialQuery = "",
    onRecords,
  }: {
    initialQuery?: string;
    onRecords: (records: IsbnSourceResult[]) => void;
  } = $props();

  // The dialog remounts per field ({#key}), so the initial value is
  // exactly what we want captured here.
  // svelte-ignore state_referenced_locally
  let query = $state(initialQuery);
  let searching = $state(false);
  let candidates = $state<CandidateRow[]>([]);
  let pendingKey = $state<string | null>(null);

  // The clue the candidates were searched with — a pick echoes it so
  // the source can rebuild its search-side context (google's merge).
  let queryTitle = "";

  function metaLine(row: CandidateRow): string {
    const publisher =
      row.publisher && !row.authors.includes(row.publisher)
        ? row.publisher
        : null;
    return [publisher, row.publishedDate?.slice(0, 4), row.label]
      .filter(Boolean)
      .join(" · ");
  }

  async function handleSearch() {
    const raw = query.trim();
    if (!raw || searching) return;
    searching = true;
    candidates = [];
    queryTitle = "";
    try {
      const compact = raw.replace(/[-\s]/g, "");
      if (/^https?:\/\//i.test(raw)) {
        await lookupDirect({ url: raw });
      } else if (/^(\d{13}|\d{9}[\dXx])$/.test(compact)) {
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
      searching = false;
    }
  }

  async function lookupDirect(params: { isbn?: string; url?: string }) {
    // Precise clues locate exactly — every source's full record arrives
    // in one call and all of them become versions at once.
    const info = await booksApi.metadataLookup(params);
    const withTitle = info.results.filter((r) => r.title);
    if (withTitle.length === 0) {
      toastStore.info(m.physical_isbn_not_found());
      return;
    }
    onRecords(withTitle);
  }

  async function pickCandidate(row: CandidateRow) {
    if (pendingKey) return;
    pendingKey = row.key;
    try {
      const info = await booksApi.metadataLookup({
        source: row.source,
        ref: row.ref,
        ...(queryTitle ? { title: queryTitle } : {}),
      });
      if (info.results.length > 0) {
        onRecords(info.results);
      } else {
        toastStore.info(m.physical_isbn_not_found());
      }
    } catch {
      toastStore.info(m.physical_isbn_not_found());
    } finally {
      pendingKey = null;
    }
  }
</script>

<div class="space-y-2">
  <div class="flex gap-2">
    <Input
      bind:value={query}
      placeholder={m.physical_autofill_hint()}
      autocomplete="off"
      spellcheck={false}
      class="flex-1"
      onkeydown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          handleSearch();
        }
      }}
    />
    <Button
      type="button"
      variant="outline"
      class="shrink-0"
      disabled={searching || !query.trim()}
      onclick={handleSearch}
    >
      {#if searching}
        <Spinner size="sm" />
      {:else}
        <Search size={14} />
      {/if}
      {m.physical_isbn_lookup()}
    </Button>
  </div>

  {#if candidates.length > 0}
    <!-- max-h deliberately cuts a row mid-height: the partial row is
         the scroll cue. -->
    <div class="max-h-56 space-y-0.5 overflow-y-auto rounded-md border p-1">
      {#each candidates as row (row.key)}
        <button
          type="button"
          class="w-full rounded-sm px-2 py-1.5 text-left transition-colors {pendingKey ===
          row.key
            ? 'bg-primary/10'
            : 'hover:bg-secondary'}"
          title={row.title}
          disabled={pendingKey !== null}
          onclick={() => pickCandidate(row)}
        >
          <div class="flex items-center gap-2.5">
            <div class="h-12 w-8 shrink-0 overflow-hidden rounded-sm bg-muted">
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
</div>
