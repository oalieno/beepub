<script lang="ts">
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { onDestroy, onMount } from "svelte";
  import { booksApi } from "$lib/api/books";
  import { coverUrl } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import { getMetadataSources } from "$lib/stores/metadataSources";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";
  import { ExternalLink, ImageIcon, Layers } from "@lucide/svelte";
  import BackButton from "$lib/components/BackButton.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import GeneratedCover from "$lib/components/GeneratedCover.svelte";
  import FieldVersionsDialog, {
    type FieldVersion,
  } from "$lib/components/FieldVersionsDialog.svelte";
  import CoverVersionsDialog, {
    type CoverVersion,
  } from "$lib/components/CoverVersionsDialog.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Textarea } from "$lib/components/ui/textarea";
  import type {
    BookOut,
    IsbnSourceResult,
    MetadataRecord,
    MetadataSourceOut,
  } from "$lib/types";

  // Fine-tuning is per field: the form is the destination, and every
  // sourced field carries a versions entry — a dialog comparing the
  // EPUB original with what each source says (already-archived records
  // open instantly; searching adds more). Nothing lands in a field
  // except typing or an explicit pick, and nothing persists until 儲存.
  interface PoolEntry {
    source: string;
    label: string;
    record: MetadataRecord;
    url: string | null;
    // true = from the external_metadata archive; false = fetched this
    // session (picking from it stages a source rebinding on save).
    stored: boolean;
  }

  const bookId = $derived(page.params.id as string);
  let book = $state<BookOut | null>(null);
  let loading = $state(true);
  let saving = $state(false);

  let form = $state<Record<string, string>>({
    title: "",
    authors: "",
    publisher: "",
    published_date: "",
    series: "",
    series_index: "",
    tags: "",
    description: "",
  });
  let fieldSources = $state<Record<string, string>>({});
  let pool = $state<PoolEntry[]>([]);
  let sources = $state<MetadataSourceOut[]>([]);
  // Which versions dialog is open: a field key, "cover", or null.
  let openField = $state<string | null>(null);
  let pendingCover = $state<
    | { kind: "url"; url: string; source: string }
    | { kind: "file"; file: File; preview: string }
    | null
  >(null);
  // source → page URL, applied via the pinned-URL flow on save so the
  // archive follows the user's pick (ratings included).
  let pendingBindings = $state<Record<string, string>>({});

  const FIELD_LABELS: Record<string, () => string> = {
    title: m.metadata_field_title,
    authors: m.metadata_field_authors,
    publisher: m.metadata_field_publisher,
    published_date: m.metadata_field_published_date,
    tags: m.metadata_field_tags,
    description: m.metadata_field_description,
  };

  onMount(async () => {
    try {
      const [loaded, rows, sourceList] = await Promise.all([
        booksApi.get(bookId),
        booksApi.getExternal(bookId),
        getMetadataSources().catch(() => [] as MetadataSourceOut[]),
      ]);
      sources = sourceList;
      book = loaded;
      form = {
        title: loaded.title ?? "",
        authors: (loaded.authors ?? []).join(", "),
        publisher: loaded.publisher ?? "",
        published_date: loaded.published_date ?? "",
        series: loaded.series ?? "",
        series_index:
          loaded.series_index != null ? String(loaded.series_index) : "",
        tags: (loaded.tags ?? []).join(", "),
        description: loaded.description ?? "",
      };
      fieldSources = { ...(loaded.field_sources ?? {}) };
      pool = rows
        .filter((row) => row.record)
        .map((row) => ({
          source: row.source,
          label: labelFor(row.source),
          record: row.record!,
          url: pageUrl(row.source, row.record!.source_url ?? row.source_url),
          stored: true,
        }));
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  });

  onDestroy(() => {
    if (pendingCover?.kind === "file")
      URL.revokeObjectURL(pendingCover.preview);
  });

  function labelFor(source: string): string {
    return sources.find((s) => s.name === source)?.label ?? source;
  }

  function pageUrl(
    source: string,
    ref: string | null | undefined,
  ): string | null {
    if (!ref) return null;
    if (ref.startsWith("http")) return ref;
    const prefix = sources.find((s) => s.name === source)?.url_prefix;
    return prefix ? prefix + ref : null;
  }

  function epubValue(field: string): string {
    if (!book) return "";
    switch (field) {
      case "title":
        return book.epub_title ?? "";
      case "authors":
        return (book.epub_authors ?? []).join(", ");
      case "publisher":
        return book.epub_publisher ?? "";
      case "published_date":
        return book.epub_published_date ?? "";
      case "tags":
        return (book.epub_tags ?? []).join(", ");
      case "description":
        return book.epub_description ?? "";
      default:
        return "";
    }
  }

  function recordValue(record: MetadataRecord, field: string): string {
    switch (field) {
      case "title":
        return record.title ?? "";
      case "authors":
        return (record.authors ?? []).join(", ");
      case "publisher":
        return record.publisher ?? "";
      case "published_date":
        return record.published_date ?? "";
      case "tags":
        return (record.tags ?? []).join(", ");
      case "description":
        return record.description ?? "";
      default:
        return "";
    }
  }

  function currentValue(field: string): string {
    return form[field] || epubValue(field);
  }

  // EPUB descriptions often carry raw markup — cards and placeholders
  // show it stripped, while picks still fill the raw value.
  function stripHtml(value: string): string {
    return value
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<[^>]+>/g, "")
      .trim();
  }

  function displayValue(field: string, value: string): string {
    return field === "description" ? stripHtml(value) : value;
  }

  function versionsFor(field: string): FieldVersion[] {
    const list: FieldVersion[] = [];
    const epub = epubValue(field);
    if (epub) {
      list.push({
        key: "epub",
        source: null,
        label: m.metadata_version_epub(),
        value: epub,
        display: displayValue(field, epub),
        url: null,
      });
    }
    for (const entry of pool) {
      const value = recordValue(entry.record, field);
      if (value) {
        list.push({
          key: entry.source,
          source: entry.source,
          label: entry.label,
          value,
          display: displayValue(field, value),
          url: entry.url,
        });
      }
    }
    return list;
  }

  function versionCount(field: string): number {
    const current = currentValue(field);
    return versionsFor(field).filter((v) => v.value !== current).length;
  }

  // Typing is manual provenance; clearing a field drops back to the
  // EPUB original and loses its provenance key.
  function markManual(field: string) {
    if ((form[field] ?? "").trim()) {
      fieldSources[field] = "manual";
    } else {
      delete fieldSources[field];
    }
  }

  function stageBinding(source: string) {
    const entry = pool.find((p) => p.source === source);
    const declared = sources.find((s) => s.name === source);
    if (entry && !entry.stored && entry.url && declared?.url_prefix) {
      pendingBindings[source] = entry.url;
    }
  }

  function pickVersion(field: string, version: FieldVersion) {
    if (version.source === null) {
      form[field] = "";
      delete fieldSources[field];
    } else {
      form[field] = version.value;
      fieldSources[field] = version.source;
      stageBinding(version.source);
    }
    openField = null;
  }

  function addRecords(records: IsbnSourceResult[]) {
    for (const record of records) {
      const entry: PoolEntry = {
        source: record.source,
        label: record.label,
        record: {
          source_url: record.url,
          title: record.title,
          authors: record.authors,
          publisher: record.publisher,
          description: record.description,
          published_date: record.published_date,
          language: record.language,
          cover_url: record.cover_url,
          tags: record.tags,
        },
        url: record.url,
        stored: false,
      };
      const existing = pool.findIndex((p) => p.source === record.source);
      if (existing >= 0) {
        pool[existing] = entry;
      } else {
        pool.push(entry);
      }
    }
  }

  const coverVersions = $derived.by(() => {
    const seen = new Set<string>();
    const list: CoverVersion[] = [];
    for (const entry of pool) {
      const url = entry.record.cover_url;
      if (url && !seen.has(url)) {
        seen.add(url);
        list.push({ source: entry.source, label: entry.label, url });
      }
    }
    return list;
  });

  const coverPreviewSrc = $derived(
    pendingCover?.kind === "url"
      ? pendingCover.url
      : pendingCover?.kind === "file"
        ? pendingCover.preview
        : null,
  );

  function pickCover(version: CoverVersion) {
    if (pendingCover?.kind === "file")
      URL.revokeObjectURL(pendingCover.preview);
    pendingCover = { kind: "url", url: version.url, source: version.source };
    stageBinding(version.source);
    openField = null;
  }

  function stageCoverUpload(file: File) {
    if (pendingCover?.kind === "file")
      URL.revokeObjectURL(pendingCover.preview);
    pendingCover = { kind: "file", file, preview: URL.createObjectURL(file) };
    openField = null;
  }

  function coverSourceLabel(): string | null {
    if (pendingCover?.kind === "url") return labelFor(pendingCover.source);
    const source = fieldSources.cover;
    return source && source !== "manual" ? labelFor(source) : null;
  }

  async function handleSave() {
    if (saving || !book) return;
    saving = true;
    try {
      const provenance: Record<string, string> = {};
      for (const [field, source] of Object.entries(fieldSources)) {
        if (field === "cover" || (form[field] ?? "").trim()) {
          provenance[field] = source;
        }
      }
      if (pendingCover) {
        provenance.cover =
          pendingCover.kind === "url" ? pendingCover.source : "manual";
      }
      const parsedAuthors = form.authors
        .split(",")
        .map((a) => a.trim())
        .filter(Boolean);
      const parsedTags = form.tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const updated = await booksApi.updateMetadata(bookId, {
        title: form.title.trim() || null,
        authors: parsedAuthors.length > 0 ? parsedAuthors : null,
        publisher: form.publisher.trim() || null,
        description: form.description || null,
        published_date: form.published_date.trim() || null,
        series: form.series.trim() || null,
        series_index: form.series_index ? parseFloat(form.series_index) : null,
        tags: parsedTags.length > 0 ? parsedTags : null,
        field_sources: provenance,
      });
      book = updated;
      if (pendingCover?.kind === "url") {
        await booksApi.updateCover(bookId, pendingCover.url);
      } else if (pendingCover?.kind === "file") {
        await booksApi.uploadCover(bookId, pendingCover.file);
      }
      for (const [source, url] of Object.entries(pendingBindings)) {
        try {
          await booksApi.updateExternalUrl(bookId, source, url);
        } catch {
          // Best-effort: a failed rebinding never blocks the save.
        }
      }
      toastStore.success(m.metadata_updated());
      goto(`/books/${bookId}`);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      saving = false;
    }
  }
</script>

<svelte:head>
  <title>{m.metadata_edit_title()} - BeePub</title>
</svelte:head>

<div class="mx-auto max-w-5xl px-4 py-6 sm:px-6 sm:py-10 pb-24">
  <BackButton
    href="/books/{bookId}"
    label={book?.display_title ?? m.common_back()}
  />

  <div class="mt-4 mb-6">
    <h1 class="text-2xl font-bold text-foreground">
      {m.metadata_edit_title()}
    </h1>
  </div>

  {#if loading}
    <div class="flex justify-center py-16"><Spinner /></div>
  {:else if book}
    <form
      class="space-y-5"
      onsubmit={(e) => {
        e.preventDefault();
        handleSave();
      }}
    >
      <div class="flex flex-col gap-6 sm:flex-row">
        <div class="shrink-0 self-center sm:self-start">
          <button
            type="button"
            class="group relative block aspect-[2/3] w-40 overflow-hidden rounded-md sm:w-[249px]"
            onclick={() => (openField = "cover")}
          >
            {#if coverPreviewSrc}
              <img
                src={coverPreviewSrc}
                alt=""
                class="h-full w-full rounded-sm object-cover book-shadow"
              />
            {:else if book.cover_path}
              <img
                use:authedSrc={coverUrl(book.id, book.updated_at)}
                alt=""
                class="h-full w-full rounded-sm object-cover book-shadow"
              />
            {:else}
              <GeneratedCover
                title={book.display_title ?? ""}
                authors={book.display_authors ?? []}
                class="h-full w-full"
              />
            {/if}
            <div
              class="absolute inset-0 flex items-center justify-center rounded-sm bg-black/0 opacity-0 transition group-hover:bg-black/40 group-hover:opacity-100"
            >
              <span
                class="flex items-center gap-1.5 text-xs font-medium text-white"
              >
                <ImageIcon size={14} />
                {m.metadata_change_cover()}
              </span>
            </div>
            <!-- Touch screens have no hover — a persistent corner badge
                 says the cover is tappable. -->
            <div
              class="absolute right-1.5 bottom-1.5 rounded-full bg-black/55 p-1.5 text-white sm:hidden"
            >
              <ImageIcon size={14} />
            </div>
          </button>
          {#if coverSourceLabel()}
            <p class="mt-1.5 text-center text-xs text-muted-foreground">
              {m.metadata_filled_from({ label: coverSourceLabel()! })}
            </p>
          {/if}
        </div>

        <div class="min-w-0 flex-1 space-y-4">
          {#each ["title", "authors"] as field (field)}
            <div class="space-y-1.5">
              <div class="flex items-center justify-between">
                <Label for="edit-{field}" class="text-sm font-medium">
                  {FIELD_LABELS[field]()}
                </Label>
                {@render versionsButton(field)}
              </div>
              <Input
                id="edit-{field}"
                bind:value={form[field]}
                placeholder={epubValue(field)}
                oninput={() => markManual(field)}
              />
              {@render filledFrom(field)}
            </div>
          {/each}

          <div class="grid grid-cols-2 gap-3">
            {#each ["publisher", "published_date"] as field (field)}
              <div class="space-y-1.5">
                <div class="flex items-center justify-between">
                  <Label for="edit-{field}" class="text-sm font-medium">
                    {FIELD_LABELS[field]()}
                  </Label>
                  {@render versionsButton(field)}
                </div>
                <Input
                  id="edit-{field}"
                  bind:value={form[field]}
                  placeholder={epubValue(field)}
                  oninput={() => markManual(field)}
                />
                {@render filledFrom(field)}
              </div>
            {/each}
          </div>

          <div class="space-y-1.5">
            <Label for="edit-series" class="text-sm font-medium">
              {m.metadata_field_series()}
            </Label>
            <div class="flex gap-2">
              <Input
                id="edit-series"
                bind:value={form.series}
                placeholder={book.epub_series ?? ""}
                class="flex-1"
                oninput={() => markManual("series")}
              />
              <Input
                id="edit-series-index"
                bind:value={form.series_index}
                placeholder={book.epub_series_index != null
                  ? String(book.epub_series_index)
                  : "#"}
                type="number"
                step="0.1"
                class="w-20"
              />
            </div>
          </div>

          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <Label for="edit-tags" class="text-sm font-medium">
                {m.metadata_field_tags()}
              </Label>
              {@render versionsButton("tags")}
            </div>
            <Input
              id="edit-tags"
              bind:value={form.tags}
              placeholder={epubValue("tags")}
              oninput={() => markManual("tags")}
            />
            {@render filledFrom("tags")}
          </div>
        </div>
      </div>

      <div class="space-y-1.5">
        <div class="flex items-center justify-between">
          <Label for="edit-description" class="text-sm font-medium">
            {m.metadata_field_description()}
          </Label>
          {@render versionsButton("description")}
        </div>
        <Textarea
          id="edit-description"
          bind:value={form.description}
          placeholder={stripHtml(epubValue("description"))}
          rows={6}
          class="max-h-72"
          oninput={() => markManual("description")}
        />
        {@render filledFrom("description")}
      </div>

      <div class="flex justify-end gap-2 pt-2">
        <Button
          type="button"
          variant="ghost"
          onclick={() => goto(`/books/${bookId}`)}
        >
          {m.common_cancel()}
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? m.common_saving() : m.common_save()}
        </Button>
      </div>
    </form>
  {/if}
</div>

{#snippet versionsButton(field: string)}
  {@const count = versionCount(field)}
  <button
    type="button"
    class="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
    title={m.metadata_versions()}
    onclick={() => (openField = field)}
  >
    <Layers size={13} />
    {#if count > 0}<span>{count}</span>{/if}
  </button>
{/snippet}

{#snippet filledFrom(field: string)}
  {@const source = fieldSources[field]}
  {#if source && source !== "manual"}
    {@const entry = pool.find((p) => p.source === source)}
    <p class="flex items-center gap-1 text-xs text-muted-foreground">
      {m.metadata_filled_from({ label: labelFor(source) })}
      {#if entry?.url}
        <a
          href={entry.url}
          target="_blank"
          rel="noreferrer"
          class="text-primary hover:underline"
          aria-label={labelFor(source)}
        >
          <ExternalLink size={11} />
        </a>
      {/if}
    </p>
  {/if}
{/snippet}

{#key openField}
  {#if openField !== null && openField !== "cover"}
    <FieldVersionsDialog
      open={true}
      onclose={() => (openField = null)}
      fieldLabel={FIELD_LABELS[openField]()}
      currentValue={currentValue(openField)}
      currentDisplay={displayValue(openField, currentValue(openField))}
      versions={versionsFor(openField)}
      multiline={openField === "description"}
      searchQuery={currentValue("title")}
      onPick={(v) => pickVersion(openField!, v)}
      onRecords={addRecords}
    />
  {:else if openField === "cover"}
    <CoverVersionsDialog
      open={true}
      onclose={() => (openField = null)}
      current={coverPreviewSrc
        ? { src: coverPreviewSrc, authed: false }
        : book?.cover_path
          ? { src: coverUrl(book.id, book.updated_at), authed: true }
          : null}
      selectedUrl={pendingCover?.kind === "url" ? pendingCover.url : null}
      versions={coverVersions}
      searchQuery={currentValue("title")}
      onPick={pickCover}
      onUpload={stageCoverUpload}
      onRecords={addRecords}
    />
  {/if}
{/key}
