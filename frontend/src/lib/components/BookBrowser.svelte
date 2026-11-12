<script lang="ts">
  import {
    Search,
    X,
    ArrowUpDown,
    SlidersHorizontal,
    Layers,
    BookOpen,
    BookX,
    LayoutGrid,
    List,
  } from "@lucide/svelte";
  import * as Select from "$lib/components/ui/select";
  import * as m from "$lib/paraglide/messages.js";
  import BookGrid from "$lib/components/BookGrid.svelte";
  import BookTable, {
    type RowDraft,
    type RowField,
  } from "$lib/components/BookTable.svelte";
  import { goto } from "$app/navigation";
  import BookCard from "$lib/components/BookCard.svelte";
  import SeriesCard from "$lib/components/SeriesCard.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import LibrarySelectionPanel from "$lib/components/LibrarySelectionPanel.svelte";
  import BookActions from "$lib/components/book-actions/BookActions.svelte";
  import { BookTableSkeleton } from "$lib/components/skeletons";
  import { tick, untrack } from "svelte";
  import { localizedTagLabel } from "$lib/tags";
  import { authStore } from "$lib/stores/auth";
  import { editedBooks, withEdit } from "$lib/stores/editedBooks";
  import {
    applyClick,
    NO_SELECTION,
    only,
    type TableSelection,
  } from "$lib/services/tableSelection";
  import type {
    BookOut,
    BookWithInteractionOut,
    GroupedItem,
    PaginatedBooksWithInteraction,
    PaginatedGrouped,
  } from "$lib/types";
  import { toastStore } from "$lib/stores/toast";
  import { booksApi } from "$lib/api/books";
  import { UserRole } from "$lib/types";

  // "Most relevant" exists only while there is a query to be relevant to.
  const RELEVANCE = "relevance:asc";

  const PAGE_SIZE = 60;

  interface FetchParams {
    search?: string;
    author?: string;
    tag?: string;
    series?: string;
    format?: string;
    sort?: string;
    order?: string;
    limit?: number;
    offset?: number;
    around?: string;
  }

  type FetchBooksFn = (
    params: FetchParams,
  ) => Promise<PaginatedBooksWithInteraction>;
  type FetchGroupedFn = (params: FetchParams) => Promise<PaginatedGrouped>;

  let {
    fetchBooks,
    fetchGrouped,
    collapsible = false,
    initialSearch = "",
    initialTag = "",
    initialAuthor = "",
    initialSeries = "",
    initialFormat = "",
    initialSort = "added_at:desc",
    initialCollapse = false,
    emptyMessage = "",
    searchPlaceholder = "",
    restoreData,
    onStateChange,
    searchEverywhereHref,
    onpane,
    library,
  }: {
    fetchBooks: FetchBooksFn;
    fetchGrouped?: FetchGroupedFn;
    collapsible?: boolean;
    initialSearch?: string;
    initialTag?: string;
    initialAuthor?: string;
    initialSeries?: string;
    initialFormat?: string;
    initialSort?: string;
    initialCollapse?: boolean;
    emptyMessage?: string;
    searchPlaceholder?: string;
    restoreData?: BookBrowserState | null;
    onStateChange?: (state: BookBrowserState) => void;
    // Where the same search runs over every library — given by a list that
    // is only one of them; an empty result then offers it.
    searchEverywhereHref?: (query: string) => string;
    /** Told whether the table shows: it is a pane that scrolls on its own,
     *  so the page around it stops scrolling (the library page). */
    onpane?: (pane: boolean) => void;
    /** The library listed (none: every library) — a book moved out of it
     *  leaves the list. */
    library?: string;
  } = $props();

  export interface BookBrowserState {
    books: BookWithInteractionOut[];
    // The grouped list's items. The key keeps its old name: this object is
    // the page snapshot SvelteKit stores in sessionStorage, and a snapshot
    // taken before the rename must still restore.
    feedItems: GroupedItem[];
    totalBooks: number;
    searchQuery: string;
    filterAuthor: string;
    filterTag: string;
    filterSeries: string;
    // Optional for snapshot compatibility (snapshots predating the field).
    filterFormat?: string;
    sortValue: string;
    collapse: boolean;
    // The table's place and selection (optional: older snapshots lack them).
    // `books` starts at `windowStart` in the whole list.
    windowStart?: number;
    selectedIds?: string[];
    focusId?: string | null;
    // The table pane's own scroll (the page does not scroll in table view).
    tableScrollTop?: number;
  }

  // Desktop-only table view (calibre-style, #70) — carries the metadata
  // the cover cards deliberately dropped. The preference persists per
  // browser; phones always render the grid.
  const VIEW_KEY = "library-view";
  let viewMode = $state<"grid" | "table">(
    typeof localStorage !== "undefined" &&
      localStorage.getItem(VIEW_KEY) === "table"
      ? "table"
      : "grid",
  );
  let isDesktop = $state(false);

  $effect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    isDesktop = mq.matches;
    const onChange = (e: MediaQueryListEvent) => (isDesktop = e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  });

  let tableView = $derived(viewMode === "table" && isDesktop);
  $effect(() => onpane?.(tableView));

  // The table scrolls in its own pane; the grid scrolls the page.
  let tableScroller = $state<HTMLElement>();

  // Compute all initial values once from restoreData or initial* props.
  // These props are intentionally captured once at creation time.
  // svelte-ignore state_referenced_locally
  const isRestoring = !!restoreData;
  // svelte-ignore state_referenced_locally
  const init: BookBrowserState = restoreData ?? {
    books: [],
    feedItems: [],
    totalBooks: 0,
    searchQuery: initialSearch,
    filterAuthor: initialAuthor,
    filterTag: initialTag,
    filterSeries: initialSeries,
    filterFormat: initialFormat,
    // Arriving with a search already typed (the search window's Enter)
    // is starting a search: most relevant first, as when it is typed here.
    sortValue:
      initialSort !== "added_at:desc"
        ? initialSort
        : initialSeries
          ? "series_index:asc"
          : initialSearch.trim()
            ? RELEVANCE
            : initialSort,
    // The table is flat — series live in their own column.
    // svelte-ignore state_referenced_locally
    collapse: collapsible && initialCollapse && viewMode !== "table",
  };

  let books = $state<BookWithInteractionOut[]>(init.books);
  // The list is a stretch of the whole: it can open in the middle (on the
  // book picked, when the order changes) and grow both ways as it scrolls.
  let windowStart = $state(init.windowStart ?? 0);
  let groupedItems = $state<GroupedItem[]>(init.feedItems);
  let totalBooks = $state(init.totalBooks);
  let collapse = $state(init.collapse);
  let filterFormat = $state(init.filterFormat ?? "");
  // The grouped list groups by series; a format filter needs the flat list, so it
  // overrides collapse the same way the table view does.
  let flatForced = $derived(!!filterFormat);
  let shownCount = $derived(
    collapse && !flatForced ? groupedItems.length : books.length,
  );
  let hasMore = $derived(
    (collapse && !flatForced ? 0 : windowStart) + shownCount < totalBooks,
  );
  let hasBefore = $derived(!(collapse && !flatForced) && windowStart > 0);

  // Series the grouped list holds more than once — the same name kept in
  // two libraries. Those cards say which library each is.
  let sharedSeriesKeys = $derived.by(() => {
    const seen = new Set<string>();
    const shared = new Set<string>();
    for (const item of groupedItems) {
      if (item.type !== "series") continue;
      const key = item.series.series_key;
      if (seen.has(key)) shared.add(key);
      seen.add(key);
    }
    return shared;
  });
  let loading = $state(!isRestoring);
  let loadingMore = $state(false);
  let loadingBefore = $state(false);
  // Which end failed to load, offering a retry there.
  let loadFailed = $state<"before" | "after" | null>(null);
  // Loading on scroll waits until the list sits where it belongs: a
  // snapshot's scroll restored, or the picked book scrolled into view.
  // Before that the top edge may be in view and pull in rows for nothing.
  let positioned = $state(false);

  // Selection (the table only). Kept by book id; the panel shows `focus`.
  let selection = $state<TableSelection>(
    init.selectedIds?.length
      ? {
          selected: new Set(init.selectedIds),
          anchor: init.focusId ?? null,
          focus: init.focusId ?? null,
        }
      : NO_SELECTION,
  );
  // The panel holds changes not yet applied: order and filters wait.
  let editing = $state(false);
  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);
  let selectedBooks = $derived(
    books
      .filter((b) => selection.selected.has(b.id))
      .map((b) => withEdit(b, $editedBooks)),
  );

  function clearSelection() {
    selection = NO_SELECTION;
    editing = false;
  }
  let searchQuery = $state(init.searchQuery);
  let filterAuthor = $state(init.filterAuthor);
  let filterTag = $state(init.filterTag);
  let filterSeries = $state(init.filterSeries);
  // Zero results means two different things: nothing matched the active
  // filters (search semantics, "not found") vs. the collection is
  // simply still empty (no failure at all).
  let hasActiveFilters = $derived(
    !!(
      searchQuery.trim() ||
      filterAuthor ||
      filterTag ||
      filterSeries ||
      filterFormat
    ),
  );
  let sortValue = $state(
    init.sortValue === RELEVANCE && !init.searchQuery.trim()
      ? "added_at:desc"
      : init.sortValue,
  );
  // Starting a search switches to relevance; clearing it goes back to
  // the order the user was browsing in (unless they picked another
  // order meanwhile — then that pick stands).
  let searching = !!init.searchQuery.trim();
  // svelte-ignore state_referenced_locally
  let sortBeforeSearch = sortValue === RELEVANCE ? "added_at:desc" : sortValue;

  function syncSortToSearch() {
    const active = !!searchQuery.trim();
    if (active && !searching && sortValue !== RELEVANCE) {
      sortBeforeSearch = sortValue;
      sortValue = RELEVANCE;
    } else if (!active && searching && sortValue === RELEVANCE) {
      sortValue = sortBeforeSearch;
    }
    searching = active;
  }
  let sortBy = $derived(sortValue.split(":")[0]);
  let sortOrder = $derived(sortValue.split(":")[1]);
  // series_index sort is meaningless once series collapse into one card, so it
  // is dropped from the menu while collapsed.
  const SORT_OPTIONS = $derived(
    [
      ...(searchQuery.trim()
        ? [{ value: RELEVANCE, label: m.browser_sort_relevance() }]
        : []),
      { value: "added_at:desc", label: m.browser_sort_newest() },
      { value: "added_at:asc", label: m.browser_sort_oldest() },
      { value: "display_title:asc", label: m.browser_sort_title_asc() },
      { value: "display_title:desc", label: m.browser_sort_title_desc() },
      { value: "series_index:asc", label: m.browser_sort_series_asc() },
      { value: "series_index:desc", label: m.browser_sort_series_desc() },
      {
        value: "popularity_score:desc",
        label: m.browser_sort_popularity_desc(),
      },
      { value: "popularity_score:asc", label: m.browser_sort_popularity_asc() },
    ].filter((o) => !(collapse && o.value.startsWith("series_index"))),
  );

  let sortLabel = $derived(
    SORT_OPTIONS.find((o) => o.value === sortValue)?.label ??
      m.browser_sort_newest(),
  );

  // Filter panel
  let showFilters = $state(false);
  let filterAuthorInput = $state(init.filterAuthor);
  let filterTagInput = $state(init.filterTag);
  let filterSeriesInput = $state(init.filterSeries);

  // Debounce timer for search input
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  function notifyStateChange() {
    onStateChange?.({
      books,
      feedItems: groupedItems,
      totalBooks,
      searchQuery,
      filterAuthor,
      filterTag,
      filterSeries,
      filterFormat,
      sortValue,
      collapse,
      windowStart,
      selectedIds: [...selection.selected],
      focusId: selection.focus,
      tableScrollTop: tableScroller?.scrollTop ?? 0,
    });
  }

  function queryParams(
    offset: number,
    extra: { limit?: number; around?: string } = {},
  ): FetchParams {
    return {
      search: searchQuery || undefined,
      author: filterAuthor || undefined,
      tag: filterTag || undefined,
      series: filterSeries || undefined,
      format: filterFormat || undefined,
      sort: sortBy,
      order: sortOrder,
      limit: extra.limit ?? PAGE_SIZE,
      offset,
      around: extra.around,
    };
  }

  // Rapid filter/search changes keep several fetches in flight; only the
  // newest may write state. An older response finishing last would
  // otherwise clear `loading` early (flashing "no books" while the newer
  // fetch runs) or overwrite the newer results.
  let loadGen = 0;

  // `around`: open the list on this book, keeping it picked — the order
  // changed under it. The old rows stay up until the new arrive, so the
  // page keeps its height and the book can be scrolled to.
  async function loadData(around?: string) {
    const gen = ++loadGen;
    if (!around) loading = true;
    positioned = false;
    loadingMore = false;
    loadingBefore = false;
    loadFailed = null;
    try {
      if (collapse && !flatForced && fetchGrouped) {
        const result = await fetchGrouped(queryParams(0));
        if (gen !== loadGen) return;
        groupedItems = result.items;
        totalBooks = result.total;
        windowStart = 0;
      } else {
        const result = await fetchBooks(queryParams(0, { around }));
        if (gen !== loadGen) return;
        books = result.items;
        totalBooks = result.total;
        windowStart = result.offset ?? 0;
        if (around) {
          selection = result.around_index != null ? only(around) : NO_SELECTION;
        }
      }
      notifyStateChange();
    } catch (e) {
      if (gen !== loadGen) return;
      toastStore.error((e as Error).message);
    } finally {
      if (gen === loadGen) {
        loading = false;
        await tick();
        if (around && selection.focus === around) scrollToRow(around);
        positioned = true;
      }
    }
  }

  // The picked book a third of the way down the pane.
  function scrollToRow(id: string) {
    const row = document.querySelector(`[data-book-row="${id}"]`);
    const pane = tableScroller;
    if (!row || !pane) return;
    const top =
      row.getBoundingClientRect().top -
      pane.getBoundingClientRect().top +
      pane.scrollTop;
    pane.scrollTop = Math.max(0, top - pane.clientHeight / 3);
  }

  // Rows already listed are not listed again: after a batch edit the
  // server's order may have moved, so the next page can overlap this one.
  function fresh<T>(items: T[], key: (item: T) => string, have: T[]): T[] {
    const seen = new Set(have.map(key));
    return items.filter((item) => !seen.has(key(item)));
  }

  async function loadMore() {
    if (loadingMore || loadingBefore || !hasMore) return;
    const gen = loadGen;
    loadingMore = true;
    loadFailed = null;
    try {
      if (collapse && !flatForced && fetchGrouped) {
        const result = await fetchGrouped(queryParams(groupedItems.length));
        if (gen !== loadGen) return;
        groupedItems = [
          ...groupedItems,
          ...fresh(result.items, groupedKey, groupedItems),
        ];
        totalBooks = result.total;
      } else {
        const result = await fetchBooks(
          queryParams(windowStart + books.length),
        );
        if (gen !== loadGen) return;
        books = [...books, ...fresh(result.items, (b) => b.id, books)];
        totalBooks = result.total;
      }
      notifyStateChange();
    } catch {
      if (gen === loadGen) loadFailed = "after";
    } finally {
      if (gen === loadGen) {
        loadingMore = false;
      }
    }
  }

  // Rows above the first: the screen stays on the row it showed. Done by
  // hand — Safari has no scroll anchoring, and Chrome's is switched off on
  // the list (overflow-anchor) so both behave the same.
  async function loadBefore() {
    if (loadingMore || loadingBefore || !hasBefore) return;
    const gen = loadGen;
    loadingBefore = true;
    loadFailed = null;
    const start = Math.max(0, windowStart - PAGE_SIZE);
    try {
      const result = await fetchBooks(
        queryParams(start, { limit: windowStart - start }),
      );
      if (gen !== loadGen) return;
      // The rows go in above the first one: it moves down by exactly
      // their height, which the pane scrolls back.
      const anchor = document.querySelector("[data-book-row]");
      const before = anchor?.getBoundingClientRect().top ?? 0;
      books = [...fresh(result.items, (b) => b.id, books), ...books];
      windowStart = start;
      totalBooks = result.total;
      await tick();
      if (anchor && tableScroller)
        tableScroller.scrollTop += anchor.getBoundingClientRect().top - before;
      notifyStateChange();
    } catch {
      if (gen === loadGen) loadFailed = "before";
    } finally {
      if (gen === loadGen) {
        loadingBefore = false;
      }
    }
  }

  function groupedKey(item: GroupedItem): string {
    return item.type === "series"
      ? `s:${item.series.library_id}:${item.series.series_key}`
      : `b:${item.book.id}`;
  }

  // Load on scroll: an edge coming within reach of the screen loads the
  // next rows that way — once. More loads only when the reader scrolls
  // again: the observer reports an edge coming into reach, not one that
  // stays there, so a scroll looks at the edges afresh (onScroll).
  let topEdge = $state<HTMLElement>();
  let bottomEdge = $state<HTMLElement>();
  let edgeObserver: IntersectionObserver | null = null;

  $effect(() => {
    if (!positioned) return;
    const top = topEdge;
    const bottom = bottomEdge;
    // The table's edges are in its pane; the grid's in the page.
    const root = tableView ? (tableScroller ?? null) : null;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          if (entry.target === top) loadBefore();
          else loadMore();
        }
      },
      { root, rootMargin: "600px 0px" },
    );
    if (top) observer.observe(top);
    if (bottom) observer.observe(bottom);
    edgeObserver = observer;
    return () => {
      observer.disconnect();
      edgeObserver = null;
    };
  });

  function recheckEdges() {
    for (const edge of [topEdge, bottomEdge]) {
      if (!edge || !edgeObserver) continue;
      edgeObserver.unobserve(edge);
      edgeObserver.observe(edge);
    }
  }

  let scrollCheck: ReturnType<typeof setTimeout> | undefined;
  function onScroll() {
    if (scrollCheck) return;
    scrollCheck = setTimeout(() => {
      scrollCheck = undefined;
      recheckEdges();
    }, 200);
  }

  // A snapshot restored: the page scrolls back first, then loading on
  // scroll starts (see the library page). The table's pane scrolls back
  // itself, once it is there.
  let pendingTableScroll: number | null = isRestoring
    ? (init.tableScrollTop ?? null)
    : null;
  export function scrollRestored() {
    if (pendingTableScroll == null) positioned = true;
  }
  $effect(() => {
    const pane = tableScroller;
    if (!pane || pendingTableScroll == null) return;
    pane.scrollTop = pendingTableScroll;
    pendingTableScroll = null;
    positioned = true;
  });

  function changeSort(value: string) {
    sortValue = value;
    // The book picked stays picked, and the list opens on it.
    const focus = tableView ? selection.focus : null;
    selection = focus ? only(focus) : NO_SELECTION;
    loadData(focus ?? undefined);
    notifyStateChange();
  }

  function onRowClick(id: string, e: MouseEvent) {
    selection = applyClick(
      selection,
      id,
      { shift: e.shiftKey, toggle: e.metaKey || e.ctrlKey },
      books.map((b) => b.id),
    );
  }

  function applied(updated: BookOut[]) {
    // The rows keep what the edit response does not carry (reading status).
    const byId = new Map(updated.map((b) => [b.id, b]));
    books = books.map((b) => {
      const edit = byId.get(b.id);
      return edit ? { ...b, ...edit } : b;
    });
    notifyStateChange();
  }

  function deleted(ids: string[]) {
    const gone = new Set(ids);
    books = books.filter((b) => !gone.has(b.id));
    totalBooks = Math.max(0, totalBooks - ids.length);
    // Rows still picked stay picked.
    const kept = [...selection.selected].filter((id) => !gone.has(id));
    if (kept.length === selection.selected.size) {
      // Nothing picked went.
    } else if (kept.length) {
      const focus = kept.includes(selection.focus ?? "")
        ? selection.focus
        : kept.at(-1)!;
      selection = { selected: new Set(kept), anchor: focus, focus };
    } else {
      clearSelection();
    }
    notifyStateChange();
  }

  // The row's ⋯ menu (BookTable): the book page's actions, for the row
  // whose menu opened last.
  let rowActions = $state<BookActions>();
  let menuBookId = $state<string | null>(null);
  let menuBook = $derived.by(() => {
    const book = books.find((b) => b.id === menuBookId);
    return book && withEdit(book, $editedBooks);
  });

  function patchRow(id: string, patch: Partial<BookWithInteractionOut>) {
    books = books.map((b) => (b.id === id ? { ...b, ...patch } : b));
    notifyStateChange();
  }

  function movedRow(id: string, libraryId: string) {
    if (library && libraryId !== library) deleted([id]);
    else patchRow(id, { library_id: libraryId });
  }

  async function convertedRow(id: string) {
    // The title is converted too, and the file now has an original.
    try {
      applied([await booksApi.get(id)]);
    } catch {
      // The row stays as it was until the list loads again.
    }
  }

  // A row edited in place (the ⋯ menu's 直接編輯, or F2 as in Calibre):
  // its title, authors and series, saved together through the batch call.
  let editingId = $state<string | null>(null);
  let editingField = $state<RowField>("title");
  let savingRow = false;
  // The row just saved keeps its bar a moment — the "saved" (BookTable).
  let savedId = $state<string | null>(null);
  let savedTimer: ReturnType<typeof setTimeout> | undefined;

  function startRowEdit(id: string, field: RowField = "title") {
    if (!isAdmin) return;
    selection = only(id);
    editingField = field;
    editingId = id;
  }

  async function finishRowEdit(id: string, draft: RowDraft | null) {
    if (editingId !== id || savingRow) return;
    const book = books.find((b) => b.id === id);
    if (!draft || !book) {
      editingId = null;
      return;
    }
    const body: Parameters<typeof booksApi.updateMetadataBulk>[0] = {
      book_ids: [id],
    };
    const title = draft.title.trim();
    if (title !== (book.display_title ?? "")) body.title = title;
    const authors = draft.authors
      .split(",")
      .map((a) => a.trim())
      .filter(Boolean);
    if (authors.join(", ") !== (book.display_authors ?? []).join(", "))
      body.authors = authors;
    const series = draft.series.trim();
    const index = draft.index.trim();
    const shownIndex =
      book.display_series_index != null
        ? String(book.display_series_index)
        : "";
    if (series !== (book.display_series ?? "") || index !== shownIndex) {
      body.series = series;
      if (series) {
        const n = parseFloat(index);
        body.series_indexes = { [id]: Number.isFinite(n) ? n : null };
      }
    }
    // The reading status is the reader's own, saved apart; none clears
    // its dates too, as on the book page.
    const status = draft.status || null;
    const statusChanged = status !== (book.reading_status ?? null);
    if (Object.keys(body).length === 1 && !statusChanged) {
      editingId = null;
      return;
    }
    savingRow = true;
    try {
      if (Object.keys(body).length > 1)
        applied(await booksApi.updateMetadataBulk(body));
      if (statusChanged) {
        await booksApi.updateReadingStatus(
          id,
          status
            ? { reading_status: status }
            : { reading_status: null, started_at: null, finished_at: null },
        );
        books = books.map((b) =>
          b.id === id ? { ...b, reading_status: status } : b,
        );
      }
      editingId = null;
      savedId = id;
      clearTimeout(savedTimer);
      savedTimer = setTimeout(() => (savedId = null), 600);
    } catch (e) {
      // The row stays open with what was typed.
      toastStore.error((e as Error).message);
    } finally {
      savingRow = false;
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (
      e.key === "F2" &&
      tableView &&
      selection.selected.size === 1 &&
      selection.focus &&
      isAdmin &&
      !editingId
    ) {
      e.preventDefault();
      startRowEdit(selection.focus);
      return;
    }
    // Enter opens the picked book, as in Calibre.
    if (
      e.key === "Enter" &&
      tableView &&
      selection.selected.size === 1 &&
      selection.focus &&
      !editingId &&
      !(e.target as HTMLElement | null)?.closest(
        "input, textarea, select, button, a, [contenteditable], [role=menu]",
      )
    ) {
      e.preventDefault();
      goto(`/books/${selection.focus}`);
      return;
    }
    if (e.key !== "Escape" || e.defaultPrevented || editing || editingId)
      return;
    if (!selection.selected.size) return;
    const target = e.target as HTMLElement | null;
    if (target?.closest("input, textarea, select, [contenteditable]")) return;
    clearSelection();
  }

  function toggleCollapse() {
    collapse = !collapse;
    // series_index ordering has no meaning collapsed; fall back to newest.
    if (collapse && sortValue.startsWith("series_index")) {
      sortValue = "added_at:desc";
    }
    handleImmediateChange();
  }

  function setViewMode(mode: "grid" | "table") {
    if (mode === viewMode) return;
    viewMode = mode;
    localStorage.setItem(VIEW_KEY, mode);
    clearSelection();
    if (mode === "table" && collapse) {
      collapse = false;
      handleImmediateChange();
    } else if (windowStart > 0) {
      // The grid only grows downward: it starts from the top.
      handleImmediateChange();
    }
  }

  // The table gone (a narrower window): so is what it held. Only a table
  // that was showing counts — `isDesktop` starts false until measured.
  let wasTable = false;
  $effect(() => {
    if (tableView) {
      wasTable = true;
      return;
    }
    if (!wasTable) return;
    wasTable = false;
    untrack(() => {
      if (selection.selected.size) clearSelection();
      if (windowStart > 0 && !loading) handleImmediateChange();
    });
  });

  function handleSearchInput() {
    clearTimeout(searchTimer);
    clearSelection();
    syncSortToSearch();
    // Show the loading state right away. Otherwise, during the debounce
    // window (and a slow request), `loading` stays false while the old/empty
    // results render — briefly flashing "no books found" before the fetch.
    loading = true;
    searchTimer = setTimeout(() => {
      loadData();
      notifyStateChange();
    }, 300);
  }

  // A new filter or search: a new list, nothing picked in it.
  function handleImmediateChange() {
    clearSelection();
    loadData();
    notifyStateChange();
  }

  function applyFilterInput(type: "author" | "tag" | "series") {
    if (type === "author") filterAuthor = filterAuthorInput.trim();
    else if (type === "tag") filterTag = filterTagInput.trim();
    else filterSeries = filterSeriesInput.trim();
    handleImmediateChange();
  }

  function clearFilter(type: "author" | "tag" | "series" | "format") {
    if (type === "author") {
      filterAuthor = "";
      filterAuthorInput = "";
    } else if (type === "tag") {
      filterTag = "";
      filterTagInput = "";
    } else if (type === "format") {
      filterFormat = "";
    } else {
      filterSeries = "";
      filterSeriesInput = "";
    }
    handleImmediateChange();
  }

  // Expose state for parent snapshot/URL sync
  export function getState(): BookBrowserState {
    return {
      books,
      feedItems: groupedItems,
      totalBooks,
      searchQuery,
      filterAuthor,
      filterTag,
      filterSeries,
      filterFormat,
      sortValue,
      collapse,
      windowStart,
      selectedIds: [...selection.selected],
      focusId: selection.focus,
      tableScrollTop: tableScroller?.scrollTop ?? 0,
    };
  }

  // Initial load (skip if restoring from snapshot)
  if (!isRestoring) {
    loadData();
  } else {
    // The page says when its scroll is back (scrollRestored); should it
    // not, loading on scroll still starts.
    setTimeout(() => (positioned = true), 1500);
  }
</script>

<!-- Search & toolbar -->
<div class="mb-6 space-y-4 shrink-0">
  <!-- Search -->
  <div class="relative">
    <Search
      class="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground"
      size={16}
    />
    <input
      type="text"
      bind:value={searchQuery}
      oninput={handleSearchInput}
      disabled={editing}
      placeholder={searchPlaceholder || m.browser_search_all()}
      class="w-full bg-card card-soft rounded-xl pl-10 pr-10 py-3 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
    />
    {#if searchQuery}
      <button
        aria-label={m.common_clear()}
        class="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        onclick={() => {
          searchQuery = "";
          clearTimeout(searchTimer);
          syncSortToSearch();
          handleImmediateChange();
        }}
      >
        <X size={16} />
      </button>
    {/if}
  </div>

  <!-- Sort & filters -->
  <div class="flex flex-wrap items-center gap-2">
    <Select.Root
      type="single"
      value={sortValue}
      disabled={editing}
      onValueChange={(v) => {
        if (v) changeSort(v);
      }}
    >
      <Select.Trigger
        class="!h-8 inline-flex items-center gap-1.5 text-xs px-2.5 rounded-full bg-secondary text-muted-foreground font-medium hover:bg-secondary/80 transition-colors border-none shadow-none"
      >
        <ArrowUpDown size={12} />
        {sortLabel}
      </Select.Trigger>
      <Select.Content>
        {#each SORT_OPTIONS as opt}
          <Select.Item value={opt.value}>{opt.label}</Select.Item>
        {/each}
      </Select.Content>
    </Select.Root>

    <button
      class="inline-flex items-center gap-1.5 h-8 text-xs px-2.5 rounded-full font-medium transition-colors {showFilters
        ? 'bg-primary/15 text-primary'
        : 'bg-secondary text-muted-foreground hover:bg-secondary/80'}"
      onclick={() => (showFilters = !showFilters)}
      disabled={editing}
    >
      <SlidersHorizontal size={12} />
      {m.browser_filters()}
    </button>

    {#if collapsible && !tableView}
      <button
        class="inline-flex items-center gap-1.5 h-8 text-xs px-2.5 rounded-full font-medium transition-colors {collapse
          ? 'bg-primary/15 text-primary'
          : 'bg-secondary text-muted-foreground hover:bg-secondary/80'}"
        onclick={toggleCollapse}
        aria-pressed={collapse}
      >
        <Layers size={12} />
        {m.browser_collapse_series()}
      </button>
    {/if}

    {#if filterAuthor}
      <button
        class="inline-flex items-center gap-1 h-8 text-xs px-3 rounded-full bg-primary/15 text-primary font-medium hover:bg-primary/25 transition-colors"
        onclick={() => clearFilter("author")}
      >
        {m.browser_filter_author({ author: filterAuthor })}
        <X size={12} />
      </button>
    {/if}
    {#if filterSeries}
      <button
        class="inline-flex items-center gap-1 h-8 text-xs px-3 rounded-full bg-primary/15 text-primary font-medium hover:bg-primary/25 transition-colors"
        onclick={() => clearFilter("series")}
      >
        {m.browser_filter_series({ series: filterSeries })}
        <X size={12} />
      </button>
    {/if}
    {#if filterTag}
      <button
        class="inline-flex items-center gap-1 h-8 text-xs px-3 rounded-full bg-primary/15 text-primary font-medium hover:bg-primary/25 transition-colors"
        onclick={() => clearFilter("tag")}
      >
        {m.browser_filter_tag({ tag: localizedTagLabel(filterTag) })}
        <X size={12} />
      </button>
    {/if}
    {#if filterFormat}
      <button
        class="inline-flex items-center gap-1 h-8 text-xs px-3 rounded-full bg-primary/15 text-primary font-medium hover:bg-primary/25 transition-colors"
        onclick={() => clearFilter("format")}
      >
        {filterFormat === "physical"
          ? m.physical_badge()
          : ["txt", "mobi", "azw3", "cbz"].includes(filterFormat)
            ? m.converted_badge({ format: filterFormat.toUpperCase() })
            : filterFormat}
        <X size={12} />
      </button>
    {/if}

    <div class="ml-auto flex items-center gap-2">
      {#if tableView && selection.selected.size}
        <span class="shrink-0 text-xs text-foreground font-medium">
          {m.browser_selected({ count: String(selection.selected.size) })}
          <button
            class="ml-1 text-primary hover:underline disabled:opacity-50"
            disabled={editing}
            onclick={clearSelection}>{m.common_clear()}</button
          >
        </span>
      {/if}
      {#if !loading && shownCount > 0}
        <span class="shrink-0 text-xs text-muted-foreground">
          {m.browser_showing({ total: String(totalBooks) })}
        </span>
      {/if}
      <div
        class="hidden md:flex items-center rounded-full bg-secondary p-0.5"
        role="group"
        aria-label={m.browser_view_label()}
      >
        <button
          class="p-1.5 rounded-full transition-colors {viewMode === 'grid'
            ? 'bg-card text-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground'}"
          title={m.browser_view_grid()}
          aria-label={m.browser_view_grid()}
          aria-pressed={viewMode === "grid"}
          onclick={() => setViewMode("grid")}
        >
          <LayoutGrid size={14} />
        </button>
        <button
          class="p-1.5 rounded-full transition-colors {viewMode === 'table'
            ? 'bg-card text-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground'}"
          title={m.browser_view_table()}
          aria-label={m.browser_view_table()}
          aria-pressed={viewMode === "table"}
          onclick={() => setViewMode("table")}
        >
          <List size={14} />
        </button>
      </div>
    </div>
  </div>

  <!-- Filter panel -->
  {#if showFilters}
    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
      <div class="relative">
        <input
          type="text"
          bind:value={filterAuthorInput}
          placeholder={m.browser_filter_author_placeholder()}
          class="w-full bg-card card-soft rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
          onkeydown={(e) => e.key === "Enter" && applyFilterInput("author")}
        />
        {#if filterAuthorInput && filterAuthorInput !== filterAuthor}
          <button
            class="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-primary font-medium"
            onclick={() => applyFilterInput("author")}
          >
            {m.browser_apply()}
          </button>
        {/if}
      </div>
      <div class="relative">
        <input
          type="text"
          bind:value={filterTagInput}
          placeholder={m.browser_filter_tag_placeholder()}
          class="w-full bg-card card-soft rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
          onkeydown={(e) => e.key === "Enter" && applyFilterInput("tag")}
        />
        {#if filterTagInput && filterTagInput !== filterTag}
          <button
            class="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-primary font-medium"
            onclick={() => applyFilterInput("tag")}
          >
            {m.browser_apply()}
          </button>
        {/if}
      </div>
      <div class="relative">
        <input
          type="text"
          bind:value={filterSeriesInput}
          placeholder={m.browser_filter_series_placeholder()}
          class="w-full bg-card card-soft rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
          onkeydown={(e) => e.key === "Enter" && applyFilterInput("series")}
        />
        {#if filterSeriesInput && filterSeriesInput !== filterSeries}
          <button
            class="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-primary font-medium"
            onclick={() => applyFilterInput("series")}
          >
            {m.browser_apply()}
          </button>
        {/if}
      </div>
    </div>
  {/if}
</div>

{#if loading}
  {#if tableView}
    <!-- The pane as it will be: a table card beside the panel's room. -->
    <div class="md:flex-1 md:min-h-0">
      <BookTableSkeleton />
    </div>
  {:else}
    <div
      class="grid gap-4 items-start book-grid"
      style="grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));"
    >
      {#each Array(12) as _}
        <div class="animate-pulse">
          <div class="aspect-[2/3] bg-muted rounded-xl"></div>
          <div class="mt-2 h-3 bg-muted rounded w-3/4"></div>
          <div class="mt-1 h-2.5 bg-muted rounded w-1/2"></div>
        </div>
      {/each}
    </div>
  {/if}
{:else if shownCount === 0}
  <div class="flex flex-col items-center justify-center text-center py-20">
    <div
      class="flex items-center justify-center w-14 h-14 rounded-full bg-muted mb-5"
    >
      {#if hasActiveFilters}
        <BookX size={24} strokeWidth={1.5} class="text-muted-foreground" />
      {:else}
        <BookOpen size={24} strokeWidth={1.5} class="text-muted-foreground" />
      {/if}
    </div>
    <p class="text-foreground text-lg font-medium">
      {hasActiveFilters
        ? m.browser_no_matches()
        : emptyMessage || m.browser_no_books()}
    </p>
    {#if searchEverywhereHref && searchQuery.trim()}
      <a
        class="mt-3 text-sm text-primary underline underline-offset-4 hover:opacity-80 transition-opacity"
        href={searchEverywhereHref(searchQuery.trim())}
        data-testid="search-everywhere"
      >
        {m.browser_search_everywhere()}
      </a>
    {/if}
  </div>
{:else}
  {#if tableView}
    <!-- Calibre-like: the table and the panel fill the screen below the
         toolbar and scroll on their own, so the header stays at the top of
         its card. No browser scroll anchoring in the pane: rows added above
         are made up for by hand (loadBefore), the same in every browser. -->
    <div class="flex gap-4 md:flex-1 md:min-h-0">
      <div
        bind:this={tableScroller}
        data-testid="table-pane"
        class="min-w-0 flex-1 bg-card card-soft rounded-xl overflow-y-auto overflow-x-hidden scrollbar-thin"
        style="overflow-anchor: none"
        onscroll={onScroll}
      >
        <BookTable
          {books}
          {sortValue}
          onSort={changeSort}
          selected={selection.selected}
          {onRowClick}
          compact={selectedBooks.length > 0}
          sortDisabled={editing}
          canEdit={isAdmin}
          menuActions={rowActions?.groups() ?? []}
          onMenuOpen={(id) => (menuBookId = id)}
          {editingId}
          {editingField}
          {savedId}
          onEditStart={startRowEdit}
          onEditDone={finishRowEdit}
          head={hasBefore ? topEdgeRow : undefined}
          foot={hasMore ? bottomEdgeRow : undefined}
        />
      </div>
      {#if selectedBooks.length}
        <aside
          class="w-[clamp(20rem,26vw,34rem)] shrink-0 overflow-y-auto scrollbar-thin"
        >
          {#key selectedBooks.map((b) => b.id).join()}
            <LibrarySelectionPanel
              books={selectedBooks}
              canEdit={isAdmin}
              onapplied={applied}
              ondeleted={deleted}
              onediting={(v) => (editing = v)}
            />
          {/key}
        </aside>
      {/if}
    </div>
  {:else if collapse}
    <!-- One grid, mixing whole-series cards and standalone book cards -->
    <div
      class="grid gap-4 items-start book-grid"
      style="grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));"
    >
      {#each groupedItems as item (item.type === "series" ? `s:${item.series.library_id}:${item.series.series_key}` : `b:${item.book.id}`)}
        {#if item.type === "series"}
          <SeriesCard
            series={item.series}
            showLibrary={sharedSeriesKeys.has(item.series.series_key)}
          />
        {:else}
          <BookCard book={item.book} />
        {/if}
      {/each}
    </div>
  {:else}
    <BookGrid {books} />
  {/if}
  {#if hasMore && !tableView}
    <!-- Never a scroll anchor: rows added above it would have the browser
         scroll down to keep it in place — in reach, loading for ever. -->
    <div
      bind:this={bottomEdge}
      class="flex justify-center py-6"
      style="overflow-anchor: none"
    >
      {@render edgeState("after")}
    </div>
  {/if}
{/if}

{#snippet topEdgeRow()}
  <div bind:this={topEdge} class="flex justify-center py-3">
    {@render edgeState("before")}
  </div>
{/snippet}

{#snippet bottomEdgeRow()}
  <div bind:this={bottomEdge} class="flex justify-center py-6">
    {@render edgeState("after")}
  </div>
{/snippet}

<BookActions
  bind:this={rowActions}
  book={menuBook}
  favorite={menuBook?.is_favorite ?? false}
  loadWork
  onfavorite={(id, value) => patchRow(id, { is_favorite: value })}
  onconverted={convertedRow}
  onmoved={movedRow}
  onwork={(id, workId) => patchRow(id, { work_id: workId })}
  ondeleted={(id) => deleted([id])}
/>

<svelte:window onkeydown={onKeydown} onscroll={onScroll} />

{#snippet edgeState(end: "before" | "after")}
  {#if loadFailed === end}
    <span class="flex items-center gap-2 text-sm text-muted-foreground">
      {m.browser_load_failed()}
      <button
        class="text-primary hover:underline"
        onclick={() => (end === "before" ? loadBefore() : loadMore())}
        >{m.common_retry()}</button
      >
    </span>
  {:else}
    <span
      class="flex items-center gap-2 text-sm text-muted-foreground"
      aria-live="polite"
    >
      <Spinner size="sm" color="foreground" />
      {m.common_loading()}
    </span>
  {/if}
{/snippet}
