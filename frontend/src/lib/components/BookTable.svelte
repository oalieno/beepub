<script lang="ts" module>
  import type { ReadingStatus } from "$lib/types";

  /** The fields a row edits in place. */
  export type RowField = "title" | "authors" | "series";

  export interface RowDraft {
    title: string;
    authors: string;
    series: string;
    index: string;
    /** The reader's own reading status; "" for none. */
    status: ReadingStatus | "";
  }
</script>

<script lang="ts">
  import { formatSize } from "$lib/format";
  import type { Snippet } from "svelte";
  import type { BookWithInteractionOut } from "$lib/types";
  import {
    ArrowDown,
    ArrowUp,
    ArrowUpRight,
    Bookmark,
    Check,
    Ellipsis,
    ExternalLink,
    TextCursorInput,
  } from "@lucide/svelte";
  import { goto } from "$app/navigation";
  import { tick } from "svelte";
  import { Input } from "$lib/components/ui/input";
  import * as Select from "$lib/components/ui/select";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import { getLocale } from "$lib/paraglide/runtime.js";
  import * as m from "$lib/paraglide/messages.js";
  import { editedBooks, withEdit } from "$lib/stores/editedBooks";
  import BookActionMenuItems from "$lib/components/book-actions/BookActionMenuItems.svelte";
  import type { BookAction } from "$lib/components/book-actions/BookActions.svelte";

  let {
    books,
    sortValue,
    onSort,
    selected,
    onRowClick,
    compact = false,
    sortDisabled = false,
    head,
    foot,
    canEdit = false,
    menuActions = [],
    onMenuOpen,
    editingId = null,
    editingField = "title",
    onEditStart,
    onEditDone,
    savedId = null,
  }: {
    books: BookWithInteractionOut[];
    sortValue: string;
    onSort: (value: string) => void;
    selected: Set<string>;
    /** A click on a row outside its title link: selects, never navigates. */
    onRowClick: (id: string, event: MouseEvent) => void;
    /** The side panel is open: the size column gives way. */
    compact?: boolean;
    sortDisabled?: boolean;
    /** Rows above and below the books: where more load. */
    head?: Snippet;
    foot?: Snippet;
    /** An admin's: a row edits in place. */
    canEdit?: boolean;
    /** The book's actions (BookActions), for the row whose ⋯ menu opened
     *  last — only one is open at a time. */
    menuActions?: BookAction[][];
    onMenuOpen?: (id: string) => void;
    /** The row being edited in place: its title, authors and series turn
     *  into fields. Done hands back what was typed, or null to back out. */
    editingId?: string | null;
    /** The field the edit starts in (the one double-clicked). */
    editingField?: RowField;
    onEditStart?: (id: string, field?: RowField) => void;
    onEditDone?: (id: string, draft: RowDraft | null) => void;
    /** A row just saved: its bar lingers, then fades. */
    savedId?: string | null;
  } = $props();

  let columns = $derived(compact ? 6 : 7);
  // Beside the side panel the title is what gets squeezed: on anything
  // but a wide screen the date column gives it its room (the sort menu
  // above still orders by date; the panel shows the book's).
  const narrowHidden = (display: "table-cell" | "table-column") =>
    compact
      ? display === "table-cell"
        ? "hidden 2xl:table-cell"
        : "hidden 2xl:table-column"
      : "";

  // A list restored on back predates an edit made on the book page.
  let rows = $derived(books.map((b) => withEdit(b, $editedBooks)));

  let draft = $state<RowDraft>({
    title: "",
    authors: "",
    series: "",
    index: "",
    status: "",
  });
  let draftFor: string | null = null;
  $effect(() => {
    const id = editingId;
    if (!id) {
      draftFor = null;
      return;
    }
    if (id === draftFor) return;
    const book = rows.find((b) => b.id === id);
    if (!book) return;
    draftFor = id;
    draft = {
      title: book.display_title ?? "",
      authors: (book.display_authors ?? []).join(", "),
      series: book.display_series ?? "",
      index:
        book.display_series_index != null
          ? String(book.display_series_index)
          : "",
      status: book.reading_status ?? "",
    };
    // The caret at the end of the field, nothing selected: fixing one
    // character should not start by wiping it. After the ⋯ menu has
    // closed: while open it keeps the focus to itself.
    tick().then(() =>
      setTimeout(() => {
        const input = document.getElementById(`row-edit-${editingField}`) as
          | HTMLInputElement
          | undefined;
        input?.focus();
        input?.setSelectionRange(input.value.length, input.value.length);
      }),
    );
  });

  function editKeydown(id: string, e: KeyboardEvent) {
    // Enter while picking characters in an IME is the pick, not a save.
    if (e.key === "Enter" && !e.isComposing) {
      e.preventDefault();
      onEditDone?.(id, { ...draft });
    } else if (e.key === "Escape") {
      e.preventDefault();
      onEditDone?.(id, null);
    }
  }

  // Leaving the row saves; moving between its fields does not.
  function editFocusout(id: string, e: FocusEvent) {
    if (editingId !== id) return;
    const into = e.relatedTarget as Element | null;
    if (into && (e.currentTarget as HTMLElement).contains(into)) return;
    // The ⋯ menu taking the focus back as it closes, or the status list
    // opening, is not leaving.
    if (into?.closest('[role="menu"], [role="listbox"]')) return;
    onEditDone?.(id, { ...draft });
  }

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

  // A row being edited still reads as the table: the same text in the same
  // places, each field marked only by an underline — 1px, darker on hover,
  // 2px in the accent while typed in (the margin takes up the extra pixel,
  // so nothing moves). Each stops short of its cell's end, so the
  // underlines stay apart.
  const cellInput =
    "box-content h-5 w-[calc(100%-1.25rem)] min-w-0 rounded-none border-0 border-b border-border -mb-px bg-transparent dark:bg-transparent p-0 text-sm leading-5 shadow-none placeholder:text-muted-foreground hover:border-muted-foreground/60 focus-visible:ring-0 focus-visible:border-b-2 focus-visible:border-primary focus-visible:-mb-[2px]";
  const STATUSES: { value: ReadingStatus; label: () => string }[] = [
    { value: "want_to_read", label: m.mybooks_tab_want_to_read },
    { value: "currently_reading", label: m.mybooks_tab_reading },
    { value: "read", label: m.mybooks_tab_read },
    { value: "did_not_finish", label: m.mybooks_tab_did_not_finish },
  ];

  // The cell a double-click began on. The first click picks the row and
  // opens the side panel, which narrows the columns: the second may land
  // on the next cell over.
  let pressedField: RowField | null = null;

  function rowClick(id: string, e: MouseEvent) {
    // The ⋯ menu and the fields of a row being edited are their own.
    if ((e.target as Element).closest("a, input, [data-row-menu]")) return;
    onRowClick(id, e);
  }
</script>

{#snippet sortableHeader(col: string, label: string)}
  <!-- The whole cell is the button, not just its word. -->
  <button
    class="flex w-full items-center gap-1 px-3 py-2.5 hover:text-foreground transition-colors disabled:opacity-50 disabled:pointer-events-none"
    disabled={sortDisabled}
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

<!-- Inside the pane that scrolls (BookBrowser): the header stays at its
     top, so the order changes from wherever the list was scrolled to. -->
<!-- Fixed layout, one line per cell: every row the same height, long
     values cut with an ellipsis (the whole value on hover). The title takes
     what the other columns leave. -->
<table class="w-full text-sm table-fixed">
  <colgroup>
    <col />
    <col class="w-[22%]" />
    <col class="w-[18%]" />
    <col class="w-24" />
    {#if !compact}<col class="w-24" />{/if}
    <col class="w-36 {narrowHidden('table-column')}" />
    <col class="w-12" />
  </colgroup>
  <thead class="sticky top-0 z-10">
    <!-- The rule is drawn by each cell (collapsed-border cells take no
           border or shadow that sticks with them). -->
    <tr
      class="text-left text-xs text-muted-foreground [&>th]:relative [&>th]:bg-card [&>th]:after:absolute [&>th]:after:inset-x-0 [&>th]:after:bottom-0 [&>th]:after:h-px [&>th]:after:bg-border [&>th]:after:content-['']"
    >
      <th class="p-0 font-medium whitespace-nowrap">
        {@render sortableHeader("display_title", m.browser_col_title())}
      </th>
      <th class="px-3 py-2.5 font-medium whitespace-nowrap"
        >{m.browser_col_authors()}</th
      >
      <th class="p-0 font-medium whitespace-nowrap">
        {@render sortableHeader("series_index", m.browser_col_series())}
      </th>
      <th class="px-3 py-2.5 font-medium whitespace-nowrap"
        >{m.browser_col_status()}</th
      >
      {#if !compact}
        <th class="px-3 py-2.5 font-medium whitespace-nowrap">
          {m.browser_col_size()}
        </th>
      {/if}
      <th
        class="p-0 font-medium whitespace-nowrap {narrowHidden('table-cell')}"
      >
        {@render sortableHeader("added_at", m.browser_col_added())}
      </th>
      <th><span class="sr-only">{m.book_more_actions()}</span></th>
    </tr>
  </thead>
  <tbody>
    {#if head}
      <tr><td colspan={columns}>{@render head()}</td></tr>
    {/if}
    {#each rows as book (book.id)}
      {@const isSelected = selected.has(book.id)}
      {@const editing = editingId === book.id}
      {@const authors = (book.display_authors ?? []).join(", ")}
      {@const series = book.display_series
        ? `${book.display_series}${book.display_series_index != null ? ` #${book.display_series_index}` : ""}`
        : ""}
      <!-- Selecting and editing are for the mouse (Shift, ⌘, double-click)
           and its keys (F2, Enter to open — see BookBrowser); the ⋯ menu is
           the row's tab stop. -->
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
      <tr
        class="group border-b border-border/50 last:border-0 transition-colors {editing
          ? 'bg-primary/[0.07]'
          : isSelected
            ? 'bg-primary/15'
            : 'hover:bg-secondary/40'}"
        aria-selected={isSelected}
        data-book-row={book.id}
        onclick={(e) => rowClick(book.id, e)}
        onmousedown={(e) => {
          // Shift+click picks a run of rows, a double-click edits a cell:
          // neither selects text.
          if (e.shiftKey || e.detail > 1) e.preventDefault();
          if (e.detail === 1)
            pressedField = ((e.target as Element)
              .closest("[data-field]")
              ?.getAttribute("data-field") ?? null) as RowField | null;
        }}
        ondblclick={(e) => {
          // A double-click edits the cell it lands on (admins).
          if (!canEdit || editingId === book.id || !pressedField) return;
          onEditStart?.(book.id, pressedField);
        }}
        onauxclick={(e) => {
          // The middle button opens the book in a new tab, as a link would.
          if (
            e.button === 1 &&
            editingId !== book.id &&
            !(e.target as Element).closest("a")
          )
            window.open(`/books/${book.id}`, "_blank");
        }}
        onfocusout={(e) => editFocusout(book.id, e)}
      >
        <!-- Editing keeps the cells: each holds a bare field set where its
             text was, the row's height unchanged; the field being typed in
             shows a ring. -->
        <td
          class="px-3 py-2.5 font-medium text-foreground truncate transition-shadow duration-500 {editing ||
          savedId === book.id
            ? 'shadow-[inset_3px_0_0_var(--primary)]'
            : ''}"
          data-field="title"
        >
          {#if editing}
            <Input
              id="row-edit-title"
              bind:value={draft.title}
              class={cellInput}
              aria-label={m.browser_col_title()}
              onkeydown={(e) => editKeydown(book.id, e)}
            />
          {:else}
            <!-- The way into the book: an ↗ after the title, on hover or
                 when picked — the title itself edits on a double-click. A
                 real link, so the middle button and ⌘ open a new tab. -->
            <span class="flex min-w-0 items-center gap-1.5">
              <span class="truncate">
                {book.display_title ?? m.common_untitled()}
              </span>
              <a
                href="/books/{book.id}"
                class="shrink-0 inline-flex h-5 w-5 items-center justify-center rounded text-muted-foreground hover:text-primary hover:bg-secondary transition-opacity focus-visible:opacity-100 {isSelected
                  ? 'opacity-100'
                  : 'opacity-0 group-hover:opacity-100'}"
                aria-label={m.selection_open()}
                title={m.selection_open()}
              >
                <ArrowUpRight size={14} />
              </a>
            </span>
          {/if}
        </td>
        <td
          class="px-3 py-2.5 truncate text-muted-foreground"
          title={editing ? undefined : authors}
          data-field="authors"
        >
          {#if editing}
            <Input
              id="row-edit-authors"
              bind:value={draft.authors}
              class={cellInput}
              aria-label={m.browser_col_authors()}
              onkeydown={(e) => editKeydown(book.id, e)}
            />
          {:else}
            {authors}
          {/if}
        </td>
        <td
          class="px-3 py-2.5 text-muted-foreground"
          title={editing ? undefined : series}
          data-field="series"
        >
          {#if editing}
            <span class="flex min-w-0 items-center pr-5">
              <Input
                id="row-edit-series"
                bind:value={draft.series}
                class="{cellInput} w-auto flex-1"
                placeholder={m.row_series_placeholder()}
                aria-label={m.browser_col_series()}
                onkeydown={(e) => editKeydown(book.id, e)}
              />
              <span class="shrink-0 mx-1.5">#</span>
              <Input
                bind:value={draft.index}
                class="{cellInput} w-8 shrink-0 text-center"
                inputmode="decimal"
                placeholder="–"
                aria-label="#"
                onkeydown={(e) => editKeydown(book.id, e)}
              />
            </span>
          {:else if book.display_series}
            <!-- A long name gives way; the number never does. -->
            <span class="flex min-w-0">
              <span class="truncate">{book.display_series}</span>
              {#if book.display_series_index != null}
                <span class="shrink-0 whitespace-nowrap ml-1"
                  >#{book.display_series_index}</span
                >
              {/if}
            </span>
          {/if}
        </td>
        <td class="px-3 py-2.5 truncate">
          {#if editing}
            <Select.Root
              type="single"
              value={draft.status}
              onValueChange={(v) =>
                (draft.status = (v ?? "") as ReadingStatus | "")}
            >
              <Select.Trigger
                class="box-content h-5 data-[size=default]:h-5 w-full gap-1 rounded-none border-0 border-b border-border -mb-px bg-transparent dark:bg-transparent dark:hover:bg-transparent px-0 py-0 text-sm shadow-none hover:border-muted-foreground/60 focus-visible:ring-0 focus-visible:border-b-2 focus-visible:border-primary focus-visible:-mb-[2px]"
                aria-label={m.browser_col_status()}
                onkeydown={(e) => {
                  // Closed, Escape backs out of the row as in its fields.
                  if (
                    e.key === "Escape" &&
                    e.currentTarget.getAttribute("aria-expanded") !== "true"
                  ) {
                    e.preventDefault();
                    onEditDone?.(book.id, null);
                  }
                }}
              >
                <span
                  class="truncate {draft.status ? '' : 'text-muted-foreground'}"
                  >{STATUSES.find((o) => o.value === draft.status)?.label() ??
                    m.row_status_none()}</span
                >
              </Select.Trigger>
              <Select.Content>
                {#each STATUSES as option (option.value)}
                  <Select.Item value={option.value}
                    >{option.label()}</Select.Item
                  >
                {/each}
                <Select.Item value="">{m.row_status_clear()}</Select.Item>
              </Select.Content>
            </Select.Root>
          {:else if book.reading_status === "read"}
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
            <span class="inline-flex items-center gap-1 text-muted-foreground">
              <Bookmark size={12} />{m.mybooks_tab_want_to_read()}
            </span>
          {:else if book.reading_status === "did_not_finish"}
            <span class="text-muted-foreground">
              {m.mybooks_tab_did_not_finish()}
            </span>
          {/if}
        </td>
        {#if !compact}
          <td class="px-3 py-2.5 text-muted-foreground truncate">
            {book.file_size != null ? formatSize(book.file_size) : "—"}
          </td>
        {/if}
        <td
          class="px-3 py-2.5 text-muted-foreground truncate {narrowHidden(
            'table-cell',
          )}"
        >
          {formatAdded(book)}
        </td>
        <!-- Spotify-like: the row's actions, shown on hover or when picked. -->
        <td class="pr-2 text-right" data-row-menu>
          <DropdownMenu.Root
            onOpenChange={(open) => open && onMenuOpen?.(book.id)}
          >
            <DropdownMenu.Trigger>
              {#snippet child({ props })}
                <button
                  {...props}
                  class="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-opacity focus-visible:opacity-100 data-[state=open]:opacity-100 {isSelected
                    ? 'opacity-100'
                    : 'opacity-0 group-hover:opacity-100'}"
                  aria-label={m.book_more_actions()}
                  title={m.book_more_actions()}
                >
                  <Ellipsis size={16} />
                </button>
              {/snippet}
            </DropdownMenu.Trigger>
            <!-- Editing in place keeps the focus in its field, not back on ⋯. -->
            <DropdownMenu.Content
              align="end"
              onCloseAutoFocus={(e) => {
                if (editingId === book.id) e.preventDefault();
              }}
            >
              <DropdownMenu.Item onclick={() => goto(`/books/${book.id}`)}>
                <ExternalLink size={14} />
                {m.selection_open()}
              </DropdownMenu.Item>
              {#if canEdit}
                <DropdownMenu.Item onclick={() => onEditStart?.(book.id)}>
                  <TextCursorInput size={14} />
                  {m.selection_edit_row()}
                </DropdownMenu.Item>
              {/if}
              <!-- The rest as on the book's page. -->
              <BookActionMenuItems groups={menuActions} separated />
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        </td>
      </tr>
    {/each}
    {#if foot}
      <tr><td colspan={columns}>{@render foot()}</td></tr>
    {/if}
  </tbody>
</table>
