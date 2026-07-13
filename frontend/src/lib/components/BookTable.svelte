<script lang="ts">
  import { goto } from "$app/navigation";
  import type { BookWithInteractionOut } from "$lib/types";
  import {
    ArrowDown,
    ArrowUp,
    Bookmark,
    BookOpen,
    Check,
  } from "@lucide/svelte";
  import { coverUrl } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import { getLocale } from "$lib/paraglide/runtime.js";
  import * as m from "$lib/paraglide/messages.js";

  let {
    books,
    sortValue,
    onSort,
  }: {
    books: BookWithInteractionOut[];
    sortValue: string;
    onSort: (value: string) => void;
  } = $props();

  let sortBy = $derived(sortValue.split(":")[0]);
  let sortOrder = $derived(sortValue.split(":")[1]);

  // Only columns the backend can order by get a sortable header; the
  // values are the same sort params the dropdown uses.
  function clickSort(col: string) {
    if (sortBy === col) {
      onSort(`${col}:${sortOrder === "asc" ? "desc" : "asc"}`);
    } else {
      onSort(`${col}:${col === "added_at" ? "desc" : "asc"}`);
    }
  }

  const dateFormat = new Intl.DateTimeFormat(getLocale(), {
    dateStyle: "medium",
  });

  function formatAdded(book: BookWithInteractionOut): string {
    // Mirrors the backend sort column: coalesce(calibre_added_at, created_at)
    const raw = book.calibre_added_at ?? book.created_at;
    const d = new Date(raw);
    return isNaN(d.getTime()) ? "" : dateFormat.format(d);
  }

  function formatSize(bytes: number): string {
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function open(id: string) {
    goto(`/books/${id}`);
  }
</script>

{#snippet sortableHeader(col: string, label: string)}
  <button
    class="inline-flex items-center gap-1 hover:text-foreground transition-colors"
    onclick={() => clickSort(col)}
  >
    {label}
    {#if sortBy === col}
      {#if sortOrder === "asc"}
        <ArrowUp size={12} />
      {:else}
        <ArrowDown size={12} />
      {/if}
    {/if}
  </button>
{/snippet}

<div class="bg-card card-soft rounded-xl overflow-x-auto scrollbar-thin">
  <table class="w-full text-sm">
    <thead>
      <tr
        class="border-b border-border text-left text-xs text-muted-foreground"
      >
        <th class="w-12 px-3 py-2.5"></th>
        <th class="px-3 py-2.5 font-medium">
          {@render sortableHeader("display_title", m.browser_col_title())}
        </th>
        <th class="px-3 py-2.5 font-medium">{m.browser_col_authors()}</th>
        <th class="px-3 py-2.5 font-medium">
          {@render sortableHeader("series_index", m.browser_col_series())}
        </th>
        <th class="px-3 py-2.5 font-medium">{m.browser_col_status()}</th>
        <th class="px-3 py-2.5 font-medium whitespace-nowrap">
          {m.browser_col_size()}
        </th>
        <th class="px-3 py-2.5 font-medium whitespace-nowrap">
          {@render sortableHeader("added_at", m.browser_col_added())}
        </th>
      </tr>
    </thead>
    <tbody>
      {#each books as book (book.id)}
        <tr
          class="border-b border-border/50 last:border-0 hover:bg-secondary/40 cursor-pointer transition-colors"
          role="link"
          tabindex="0"
          onclick={() => open(book.id)}
          onkeydown={(e) => e.key === "Enter" && open(book.id)}
        >
          <td class="px-3 py-2">
            <div
              class="w-8 h-12 rounded-sm overflow-hidden bg-secondary flex items-center justify-center"
            >
              {#if book.cover_path}
                <img
                  use:authedSrc={coverUrl(book.id, book.updated_at)}
                  alt=""
                  class="w-full h-full object-cover"
                  loading="lazy"
                />
              {:else}
                <BookOpen size={14} class="text-muted-foreground/30" />
              {/if}
            </div>
          </td>
          <td class="px-3 py-2 font-medium text-foreground">
            {book.display_title ?? m.common_untitled()}
          </td>
          <td class="px-3 py-2 text-muted-foreground">
            {(book.display_authors ?? []).join(", ")}
          </td>
          <td class="px-3 py-2 text-muted-foreground">
            {#if book.display_series}
              {book.display_series}{book.display_series_index != null
                ? ` #${book.display_series_index}`
                : ""}
            {/if}
          </td>
          <td class="px-3 py-2 whitespace-nowrap">
            {#if book.reading_status === "read"}
              <span
                class="inline-flex items-center gap-1 text-primary font-medium"
              >
                <Check size={12} strokeWidth={3} />{m.mybooks_tab_read()}
              </span>
            {:else if book.reading_status === "currently_reading"}
              <span class="text-muted-foreground">
                {#if book.reading_percentage != null && book.reading_percentage > 0}
                  {Math.round(book.reading_percentage)}%
                {:else}
                  {m.mybooks_tab_reading()}
                {/if}
              </span>
            {:else if book.reading_status === "want_to_read"}
              <span
                class="inline-flex items-center gap-1 text-muted-foreground"
              >
                <Bookmark size={12} />{m.mybooks_tab_want_to_read()}
              </span>
            {:else if book.reading_status === "did_not_finish"}
              <span class="text-muted-foreground">
                {m.mybooks_tab_did_not_finish()}
              </span>
            {/if}
          </td>
          <td class="px-3 py-2 text-muted-foreground whitespace-nowrap">
            {formatSize(book.file_size)}
          </td>
          <td class="px-3 py-2 text-muted-foreground whitespace-nowrap">
            {formatAdded(book)}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
