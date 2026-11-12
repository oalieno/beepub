<script lang="ts">
  /**
   * The library table's side panel: the book picked, or — several picked —
   * their shared series, authors and publisher to change at once, tags to
   * put on or take off, a find-and-replace over their titles, and delete. Fields the books disagree on start empty and are left alone
   * unless typed into; a field emptied goes back to each book's own value.
   */
  import { onDestroy } from "svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as Select from "$lib/components/ui/select";
  import GeneratedCover from "$lib/components/GeneratedCover.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { coverUrl } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import { sanitizeDescription } from "$lib/sanitize";
  import {
    replaceTitles,
    seriesNumbers,
    type Numbering,
  } from "$lib/services/tableSelection";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { X } from "@lucide/svelte";
  import type { BookOut, BookWithInteractionOut } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";
  import { getLocale } from "$lib/paraglide/runtime.js";

  let {
    books,
    canEdit,
    onapplied,
    ondeleted,
    onediting,
  }: {
    /** The books picked, in list order. */
    books: BookWithInteractionOut[];
    canEdit: boolean;
    onapplied: (updated: BookOut[]) => void;
    ondeleted: (ids: string[]) => void;
    /** Whether there are changes not yet applied. */
    onediting: (editing: boolean) => void;
  } = $props();

  type Field = "series" | "authors" | "publisher";
  const FIELDS: Field[] = ["series", "authors", "publisher"];
  const LABELS: Record<Field, () => string> = {
    series: m.metadata_field_series,
    authors: m.metadata_field_authors,
    publisher: m.metadata_field_publisher,
  };

  function shown(book: BookOut, field: Field): string {
    if (field === "series") return book.display_series ?? "";
    if (field === "authors") return (book.display_authors ?? []).join(", ");
    return book.publisher ?? book.epub_publisher ?? "";
  }

  /** The value every book shares, or null where they differ. */
  function common(field: Field): string | null {
    const values = new Set(books.map((b) => shown(b, field)));
    return values.size === 1 ? [...values][0] : null;
  }

  let edits = $state<Partial<Record<Field, string>>>({});
  let numbering = $state<Numbering>("title");
  let busy = $state(false);
  let updated = $state<number | null>(null);
  let confirming = $state(false);

  // Tags: each book keeps its own; these are put on all, or taken off.
  let tagAdds = $state<string[]>([]);
  let tagRemoves = $state<string[]>([]);
  let tagDraft = $state("");
  /** Every tag among the books, with how many of them carry it. */
  let tagCounts = $derived.by(() => {
    const counts = new Map<string, number>();
    for (const b of books)
      for (const t of b.display_tags ?? [])
        counts.set(t, (counts.get(t) ?? 0) + 1);
    return counts;
  });

  function addTags(text: string) {
    for (const tag of text.split(/[,，]/).map((t) => t.trim())) {
      if (!tag) continue;
      // Asked back for a tag marked to go: it simply stays.
      if (tagRemoves.includes(tag))
        tagRemoves = tagRemoves.filter((t) => t !== tag);
      else if (!tagAdds.includes(tag) && tagCounts.get(tag) !== books.length)
        tagAdds = [...tagAdds, tag];
    }
    tagDraft = "";
    updated = null;
  }
  function toggleRemove(tag: string) {
    tagRemoves = tagRemoves.includes(tag)
      ? tagRemoves.filter((t) => t !== tag)
      : [...tagRemoves, tag];
    updated = null;
  }

  // Titles: find and replace, each book's result shown before it is applied.
  let find = $state("");
  let replaceWith = $state("");
  let regex = $state(false);
  let replaced = $derived(
    replaceTitles(
      books.map((b) => b.display_title ?? ""),
      find,
      replaceWith,
      regex,
    ),
  );
  let titleChanges = $derived(
    books.flatMap((b, i) => {
      const next = replaced.results[i];
      return next == null
        ? []
        : [{ id: b.id, from: b.display_title ?? "", to: next }];
    }),
  );
  let titlesToWrite = $derived(titleChanges.filter((c) => c.to !== ""));

  function reset() {
    edits = {};
    tagAdds = [];
    tagRemoves = [];
    tagDraft = "";
    find = "";
    replaceWith = "";
  }

  let editing = $derived(
    Object.keys(edits).length > 0 ||
      tagAdds.length > 0 ||
      tagRemoves.length > 0 ||
      titlesToWrite.length > 0,
  );
  $effect(() => onediting(editing));
  onDestroy(() => onediting(false));

  // Calibre's data stays as it is: what is typed here is BeePub's own.
  let allCalibre = $derived(books.every((b) => b.calibre_id != null));
  let anyCalibre = $derived(books.some((b) => b.calibre_id != null));

  function type(field: Field, value: string) {
    const start = common(field);
    // Typed back to where it started: nothing to change.
    if (start === null ? value === "" : value === start) delete edits[field];
    else edits[field] = value;
    updated = null;
  }

  function status(field: Field): string | null {
    const value = edits[field];
    if (value === undefined) return null;
    if (value.trim()) return m.selection_will_update();
    return allCalibre
      ? m.selection_will_revert_calibre()
      : m.selection_will_revert();
  }

  let settingSeries = $derived(!!edits.series?.trim());
  let numbers = $derived(
    seriesNumbers(
      books.map((b) => b.display_title ?? ""),
      numbering,
    ),
  );
  const NUMBERING_LABELS: Record<Numbering, () => string> = {
    title: m.selection_numbering_title,
    order: () => m.selection_numbering_order({ count: String(books.length) }),
    keep: m.selection_numbering_keep,
  };

  async function apply() {
    if (busy || !editing) return;
    busy = true;
    try {
      const body: Parameters<typeof booksApi.updateMetadataBulk>[0] = {
        book_ids: books.map((b) => b.id),
      };
      if (edits.authors !== undefined)
        body.authors = edits.authors
          .split(",")
          .map((a) => a.trim())
          .filter(Boolean);
      if (edits.publisher !== undefined)
        body.publisher = edits.publisher.trim();
      if (edits.series !== undefined) {
        body.series = edits.series.trim();
        if (body.series && numbering !== "keep") {
          // A book whose title has no number keeps the one it shows.
          const indexes: Record<string, number> = {};
          books.forEach((b, i) => {
            const n = numbers[i];
            if (n != null) indexes[b.id] = n;
          });
          body.series_indexes = indexes;
        }
      }
      if (tagAdds.length) body.tags_add = tagAdds;
      if (tagRemoves.length) body.tags_remove = tagRemoves;
      if (titlesToWrite.length)
        body.titles = Object.fromEntries(
          titlesToWrite.map((c) => [c.id, c.to]),
        );
      const count = books.length;
      onapplied(await booksApi.updateMetadataBulk(body));
      reset();
      updated = count;
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      busy = false;
    }
  }

  async function remove() {
    if (busy) return;
    busy = true;
    const ids = books.map((b) => b.id);
    try {
      await booksApi.deleteMany(ids);
      toastStore.success(m.selection_deleted({ count: String(ids.length) }));
      ondeleted(ids);
    } catch (e) {
      toastStore.error((e as Error).message);
      busy = false;
    }
  }

  const dateFormat = new Intl.DateTimeFormat(getLocale(), {
    dateStyle: "medium",
  });
  function added(book: BookOut): string {
    // As the table's column: when Calibre added it, else when BeePub did.
    const d = new Date(book.calibre_added_at ?? book.created_at);
    return isNaN(d.getTime()) ? "" : dateFormat.format(d);
  }
  function size(bytes: number): string {
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
</script>

{#snippet cover(book: BookOut, cls: string)}
  {#if book.cover_path}
    <img
      use:authedSrc={coverUrl(book.id, book.updated_at)}
      alt="{book.display_title} cover"
      class="{cls} object-cover rounded-sm book-shadow"
    />
  {:else}
    <GeneratedCover
      title={book.display_title ?? m.common_untitled()}
      authors={book.display_authors ?? []}
      class="{cls} rounded-sm book-shadow"
    />
  {/if}
{/snippet}

<div
  class="bg-card card-soft rounded-xl p-5 space-y-5 text-sm min-h-full"
  data-testid="selection-panel"
>
  {#if books.length === 1}
    {@const book = books[0]}
    <!-- As wide as the panel, short enough to leave the details in view. -->
    <div class="flex justify-center">
      {@render cover(book, "w-full max-w-[calc(60vh*2/3)] aspect-[2/3]")}
    </div>
    <div>
      <h2 class="font-semibold text-lg leading-snug text-foreground">
        {book.display_title ?? m.common_untitled()}
      </h2>
    </div>

    <!-- Label and value, as Calibre's book details: what each line is,
         without reading it. -->
    <dl
      class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-1.5 border-t border-border pt-4 leading-7"
    >
      {#if book.display_authors?.length}
        <dt class="text-xs text-muted-foreground leading-7">
          {m.browser_col_authors()}
        </dt>
        <dd class="min-w-0 text-foreground">
          {book.display_authors.join(", ")}
        </dd>
      {/if}
      {#if book.display_series}
        <dt class="text-xs text-muted-foreground leading-7">
          {m.browser_col_series()}
        </dt>
        <dd class="min-w-0 text-foreground">
          {book.display_series}{book.display_series_index != null
            ? ` #${book.display_series_index}`
            : ""}
        </dd>
      {/if}
      {#if book.publisher ?? book.epub_publisher}
        <dt class="text-xs text-muted-foreground leading-7">
          {m.metadata_field_publisher()}
        </dt>
        <dd class="min-w-0 text-foreground">
          {book.publisher ?? book.epub_publisher}
        </dd>
      {/if}
      {#if book.display_tags?.length}
        <dt class="text-xs text-muted-foreground leading-7">
          {m.selection_tags()}
        </dt>
        <dd class="min-w-0 text-foreground">
          {book.display_tags.join("、")}
        </dd>
      {/if}
      <dt class="text-xs text-muted-foreground leading-7">
        {m.browser_col_added()}
      </dt>
      <dd class="min-w-0 text-foreground tabular-nums">{added(book)}</dd>
      {#if book.file_size != null}
        <dt class="text-xs text-muted-foreground leading-7">
          {m.browser_col_size()}
        </dt>
        <dd class="min-w-0 text-foreground tabular-nums">
          {size(book.file_size)}
        </dd>
        <dt class="text-xs text-muted-foreground leading-7">
          {m.book_format()}
        </dt>
        <dd class="min-w-0 text-foreground">{book.format.toUpperCase()}</dd>
      {/if}
    </dl>

    {#if book.description ?? book.epub_description}
      <div
        class="border-t border-border pt-4 text-muted-foreground leading-relaxed prose-description line-clamp-[12]"
      >
        {@html sanitizeDescription(book.description ?? book.epub_description)}
      </div>
    {/if}
  {:else}
    {@const shownCovers = books.slice(0, 3)}
    <div
      class="relative mx-auto h-64"
      style="width: {10 + (shownCovers.length - 1) * 4}rem"
      aria-hidden="true"
    >
      {#each shownCovers as book, i (book.id)}
        <div
          class="absolute top-0"
          style="left: {i * 4}rem; top: {i * 0.6}rem; z-index: {3 - i}"
        >
          {@render cover(book, "w-40 aspect-[2/3]")}
        </div>
      {/each}
    </div>
    <h2 class="font-semibold text-lg text-foreground">
      {m.browser_selected({ count: String(books.length) })}
    </h2>

    {#if canEdit}
      <form
        class="space-y-3"
        onsubmit={(e) => {
          e.preventDefault();
          apply();
        }}
      >
        <div class="space-y-1.5">
          <div class="flex items-center justify-between gap-2">
            <Label for="batch-find" class="text-sm text-muted-foreground">
              {m.selection_title_replace()}
            </Label>
            <label
              class="flex items-center gap-1.5 text-xs text-muted-foreground"
            >
              <Checkbox bind:checked={regex} disabled={busy} />
              {m.selection_regex()}
            </label>
          </div>
          <Input
            id="batch-find"
            bind:value={find}
            placeholder={m.selection_find()}
            aria-label={m.selection_find()}
            aria-invalid={replaced.error}
            disabled={busy}
            oninput={() => (updated = null)}
          />
          <Input
            bind:value={replaceWith}
            placeholder={m.selection_replace_with()}
            aria-label={m.selection_replace_with()}
            disabled={busy}
            oninput={() => (updated = null)}
          />
          {#if replaced.error}
            <p class="text-xs text-destructive" role="alert">
              {m.selection_regex_invalid()}
            </p>
          {:else if find && titleChanges.length === 0}
            <p class="text-xs text-muted-foreground">
              {m.selection_titles_none()}
            </p>
          {:else if titleChanges.length}
            <p class="text-xs text-primary">
              {m.selection_titles_changing({
                count: String(titlesToWrite.length),
              })}
            </p>
            <ol
              class="rounded-xl border border-border max-h-56 overflow-y-auto divide-y divide-border/60 text-xs"
              data-testid="title-preview"
            >
              {#each titleChanges as change (change.id)}
                <li class="px-3 py-1.5">
                  <span class="block truncate text-muted-foreground"
                    >{change.from}</span
                  >
                  {#if change.to}
                    <span class="block truncate text-foreground"
                      >{change.to}</span
                    >
                  {:else}
                    <span class="block text-destructive"
                      >{m.selection_title_blank()}</span
                    >
                  {/if}
                </li>
              {/each}
            </ol>
          {/if}
        </div>

        {#each FIELDS as field (field)}
          {@const start = common(field)}
          <div class="space-y-1.5">
            <div class="flex items-center justify-between gap-2">
              <Label for="batch-{field}" class="text-sm text-muted-foreground">
                {LABELS[field]()}
              </Label>
              {#if status(field)}
                <span class="text-xs text-primary">{status(field)}</span>
              {/if}
            </div>
            <Input
              id="batch-{field}"
              value={edits[field] ?? start ?? ""}
              placeholder={start === null ? m.selection_multiple() : ""}
              disabled={busy}
              oninput={(e) => type(field, e.currentTarget.value)}
            />
            {#if field === "series" && settingSeries}
              <Select.Root
                type="single"
                value={numbering}
                onValueChange={(v) => v && (numbering = v as Numbering)}
              >
                <Select.Trigger
                  class="w-full h-8 text-xs"
                  aria-label={m.selection_numbering_label()}
                >
                  {NUMBERING_LABELS[numbering]()}
                </Select.Trigger>
                <Select.Content>
                  {#each ["title", "order", "keep"] as const as option (option)}
                    <Select.Item value={option}
                      >{NUMBERING_LABELS[option]()}</Select.Item
                    >
                  {/each}
                </Select.Content>
              </Select.Root>
              {#if numbering !== "keep"}
                <ol
                  class="rounded-xl border border-border max-h-48 overflow-y-auto divide-y divide-border/60 text-xs"
                  aria-label={m.selection_numbering_label()}
                  data-testid="numbering-preview"
                >
                  {#each books as book, i (book.id)}
                    <li class="flex gap-2 px-3 py-1.5">
                      <span
                        class="w-7 shrink-0 text-right tabular-nums font-medium {numbers[
                          i
                        ] == null
                          ? 'text-destructive'
                          : 'text-primary'}">{numbers[i] ?? "?"}</span
                      >
                      <span class="truncate text-foreground"
                        >{book.display_title ?? m.common_untitled()}</span
                      >
                    </li>
                  {/each}
                </ol>
              {/if}
            {/if}
          </div>
        {/each}

        <div class="space-y-1.5">
          <Label for="batch-tag" class="text-sm text-muted-foreground">
            {m.selection_tags()}
          </Label>
          {#if tagCounts.size || tagAdds.length}
            <ul class="flex flex-wrap gap-1.5" data-testid="batch-tags">
              {#each tagCounts as [tag, count] (tag)}
                {@const going = tagRemoves.includes(tag)}
                <!-- A tag only some of the books carry is drawn dashed. -->
                <li
                  class="inline-flex items-center gap-1 rounded-full border pl-2.5 pr-1 py-0.5 text-xs {going
                    ? 'border-destructive/40 text-muted-foreground line-through'
                    : count < books.length
                      ? 'border-dashed border-border text-muted-foreground'
                      : 'border-border bg-secondary text-foreground'}"
                  title={count < books.length
                    ? m.selection_tag_some({
                        count: String(count),
                        total: String(books.length),
                      })
                    : undefined}
                >
                  {tag}
                  <button
                    type="button"
                    class="inline-flex h-4 w-4 items-center justify-center rounded-full hover:bg-destructive/10 hover:text-destructive"
                    disabled={busy}
                    aria-pressed={going}
                    aria-label={going
                      ? m.selection_tag_keep({ tag })
                      : m.selection_tag_remove({ tag })}
                    onclick={() => toggleRemove(tag)}><X size={11} /></button
                  >
                </li>
              {/each}
              {#each tagAdds as tag (tag)}
                <li
                  class="inline-flex items-center gap-1 rounded-full border border-primary/50 bg-primary/10 pl-2.5 pr-1 py-0.5 text-xs text-foreground"
                >
                  {tag}
                  <button
                    type="button"
                    class="inline-flex h-4 w-4 items-center justify-center rounded-full hover:bg-primary/20"
                    disabled={busy}
                    aria-label={m.selection_tag_remove({ tag })}
                    onclick={() => (tagAdds = tagAdds.filter((t) => t !== tag))}
                    ><X size={11} /></button
                  >
                </li>
              {/each}
            </ul>
          {/if}
          <Input
            id="batch-tag"
            bind:value={tagDraft}
            placeholder={m.selection_tag_add()}
            disabled={busy}
            onkeydown={(e) => {
              // Enter adds the tag; it must not apply the whole form.
              if (e.key === "Enter" && !e.isComposing && tagDraft.trim()) {
                e.preventDefault();
                addTags(tagDraft);
              }
            }}
            onblur={() => addTags(tagDraft)}
          />
        </div>

        <div class="flex items-center gap-2">
          <Button type="submit" class="rounded-xl" disabled={busy || !editing}>
            {#if busy}<Spinner size="sm" />{/if}
            {m.selection_apply({ count: String(books.length) })}
          </Button>
          {#if editing}
            <Button
              type="button"
              variant="ghost"
              class="rounded-xl"
              disabled={busy}
              onclick={reset}>{m.common_cancel()}</Button
            >
          {/if}
        </div>
        {#if updated != null}
          <p class="text-xs text-primary" role="status">
            {m.selection_updated({ count: String(updated) })}
          </p>
        {/if}
      </form>

      {#if !anyCalibre}
        <div class="border-t border-border pt-4">
          {#if confirming}
            <div
              class="rounded-xl border border-destructive/60 p-3 space-y-3"
              role="alert"
            >
              <p>
                {m.selection_delete_warning({ count: String(books.length) })}
              </p>
              <div class="flex gap-2">
                <Button
                  variant="destructive"
                  class="rounded-xl"
                  disabled={busy}
                  onclick={remove}
                  >{m.selection_delete_confirm({
                    count: String(books.length),
                  })}</Button
                >
                <Button
                  variant="ghost"
                  class="rounded-xl"
                  disabled={busy}
                  onclick={() => (confirming = false)}
                  >{m.common_cancel()}</Button
                >
              </div>
            </div>
          {:else}
            <Button
              variant="outline"
              class="rounded-xl border-destructive/30 text-destructive hover:bg-destructive/10 hover:text-destructive"
              onclick={() => (confirming = true)}
              >{m.selection_delete({ count: String(books.length) })}</Button
            >
          {/if}
        </div>
      {/if}
    {/if}
  {/if}
</div>
