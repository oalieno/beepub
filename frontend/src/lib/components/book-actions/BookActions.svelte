<script lang="ts" module>
  import type { Heart } from "@lucide/svelte";
  import type { BookOut } from "#lib/types.ts";
  import type { DownloadRequest } from "#lib/stores/downloads.ts";
  import type { booksApi as BooksApi } from "#lib/api/books.ts";

  /** One thing a book's ⋯ menu offers. */
  export interface BookAction {
    key: string;
    label: string;
    icon: typeof Heart;
    /** The icon's colour when it marks the book's state (a favourite,
     *  notes written, a report open). */
    tone?: string;
    destructive?: boolean;
    disabled?: boolean;
    run: () => void;
  }

  export type Edition = Awaited<
    ReturnType<typeof BooksApi.getEditions>
  >["editions"][number];

  /** What the app's download queue needs to fetch a book (native). */
  export function downloadRequestFor(book: BookOut): DownloadRequest {
    return {
      bookId: book.id,
      title: book.display_title ?? book.title ?? "Untitled",
      known: {
        isImageBook: book.is_image_book,
        sectionWeights: book.section_weights ?? null,
      },
    };
  }
</script>

<script lang="ts">
  /**
   * A book's actions, defined once for every ⋯ menu that offers them: the
   * book page's (menu and bottom sheet) and the library table's rows.
   * Mounted once, outside the menus — a menu's content unmounts as it
   * closes, and the dialogs its items open must outlive it. Each menu
   * renders `groups()`; what differs between them is told by the
   * callbacks.
   */
  import { goto } from "$app/navigation";
  import {
    Heart as HeartIcon,
    ShelvingUnit,
    NotebookPen,
    Flag,
    Share,
    FileText,
    Languages,
    Pencil,
    RefreshCw,
    FolderInput,
    Star,
    Plus,
    Unlink,
    Scissors,
    Link,
    Trash2,
    Search,
    X,
    BookOpen,
    Check,
    HardDrive,
    Library as LibraryIcon,
  } from "@lucide/svelte";
  import * as Dialog from "#lib/components/ui/dialog/index.ts";
  import { Button } from "#lib/components/ui/button/index.ts";
  import Modal from "#lib/components/Modal.svelte";
  import ReportIssueModal from "#lib/components/ReportIssueModal.svelte";
  import ZhConvertDialog from "#lib/components/ZhConvertDialog.svelte";
  import { authedSrc } from "#lib/actions/authedSrc.ts";
  import { coverUrl } from "#lib/api/client.ts";
  import { booksApi } from "#lib/api/books.ts";
  import { worksApi } from "#lib/api/works.ts";
  import { bookshelvesApi } from "#lib/api/bookshelves.ts";
  import { librariesApi } from "#lib/api/libraries.ts";
  import { authStore } from "#lib/stores/auth.ts";
  import { toastStore } from "#lib/stores/toast.ts";
  import { confirmDialog } from "#lib/stores/confirm.ts";
  import { shareBook } from "#lib/stores/downloads.ts";
  import { isNative } from "#lib/platform.ts";
  import { UserRole, type BookshelfOut, type LibraryOut } from "#lib/types.ts";
  import * as m from "#lib/paraglide/messages.js";

  let {
    book,
    favorite = false,
    hasNotes = false,
    editions = $bindable([]),
    primaryBookId = $bindable(null),
    loadWork = false,
    onfavorite,
    onnotes,
    onreported,
    onconverted,
    onmoved,
    onwork,
    ondeleted,
  }: {
    book: BookOut | null | undefined;
    favorite?: boolean;
    hasNotes?: boolean;
    /** The book's work: its other editions and the primary one. */
    editions?: Edition[];
    primaryBookId?: string | null;
    /** The caller has no editions for its books (the table): asked for
     *  whenever the book changes. */
    loadWork?: boolean;
    onfavorite?: (id: string, favorite: boolean) => void;
    /** Where the notes are written. Not given: the book's page, the
     *  editor open. */
    onnotes?: () => void;
    onreported?: (id: string) => void;
    onconverted?: (id: string) => void;
    onmoved?: (id: string, libraryId: string) => void;
    onwork?: (id: string, workId: string | null) => void;
    ondeleted: (id: string) => void;
  } = $props();

  let user = $derived($authStore.user);
  let isAdmin = $derived(user?.role === UserRole.Admin);

  // The book the open dialog is about — kept apart from `book`, which in
  // the table follows whichever row's menu was opened last.
  let target = $state<BookOut | null>(null);
  let showShelves = $state(false);
  let shelves = $state<BookshelfOut[]>([]);
  let showReport = $state(false);
  let showConvertZh = $state(false);
  let showMove = $state(false);
  let moveLibraries = $state<LibraryOut[]>([]);
  let moveFrom = $state<string | null>(null);
  let showWorkRemove = $state(false);
  let showWorkSplit = $state(false);
  let showWorkSearch = $state(false);
  let workSearchMode = $state<"add" | "create">("add");
  let workSearchQuery = $state("");
  let workSearchResults = $state<BookOut[]>([]);
  let workSearchTotal = $state(0);
  let workSearching = $state(false);
  let workSearchTimeout: ReturnType<typeof setTimeout> | null = null;
  const WORK_SEARCH_LIMIT = 20;

  // Only an admin's work items need the editions; until they come, the
  // primary edition is not known.
  let workKey = $derived(
    loadWork && isAdmin && book?.work_id ? `${book.id}:${book.work_id}` : null,
  );
  let workLoading = $state(false);
  $effect(() => {
    if (!loadWork) return;
    const key = workKey;
    editions = [];
    primaryBookId = null;
    workLoading = !!key;
    if (!key) return;
    const id = key.split(":")[0];
    let stale = false;
    booksApi
      .getEditions(id)
      .then((v) => {
        if (stale) return;
        editions = v.editions;
        primaryBookId = v.primary_book_id;
      })
      .catch(() => {})
      .finally(() => {
        if (!stale) workLoading = false;
      });
    return () => {
      stale = true;
    };
  });

  // A book whose text may be Simplified Chinese can be converted. Chinese
  // is told by its script: zh-TW/zh-HK/zh-Hant are already Traditional, a
  // bare "zh" may be either (the dialog's preview shows which).
  function canConvertZh(b: BookOut): boolean {
    // A Calibre library's files are Calibre's to change.
    if (b.format === "physical" || b.is_image_book || b.calibre_id != null)
      return false;
    if (!(isAdmin || user?.can_upload)) return false;
    try {
      const locale = new Intl.Locale(b.epub_language ?? "");
      return locale.language === "zh" && locale.maximize().script !== "Hant";
    } catch {
      return false;
    }
  }

  // A copy as uploaded: the source of a converted format (TXT/MOBI/AZW3/
  // CBZ, whose book is the EPUB made at ingest), or an EPUB as it was
  // before conversion to Traditional. Web only — the app's "download to
  // phone" wants the EPUB.
  function hasOriginal(b: BookOut): boolean {
    return (
      ["txt", "mobi", "azw3", "cbz"].includes(b.format) || !!b.has_original
    );
  }

  let actionGroups = $derived.by((): BookAction[][] => {
    const b = book;
    if (!b) return [];
    const reading: BookAction[] = [
      {
        key: "favorite",
        label: favorite ? m.book_remove_favorite() : m.book_add_favorite(),
        icon: HeartIcon,
        tone: favorite ? "fill-red-500 text-red-500" : undefined,
        run: () => toggleFavorite(b, !favorite),
      },
      {
        key: "shelf",
        label: m.book_add_to_shelf(),
        icon: ShelvingUnit,
        run: () => openShelves(b),
      },
      {
        key: "notes",
        label: m.book_notes(),
        icon: NotebookPen,
        tone: hasNotes ? "text-primary" : undefined,
        run: () => (onnotes ? onnotes() : goto(`/books/${b.id}#notes`)),
      },
      {
        key: "report",
        label: m.book_report_issue(),
        icon: Flag,
        tone: b.has_unresolved_reports ? "text-destructive" : undefined,
        run: () => {
          target = b;
          showReport = true;
        },
      },
    ];
    if (isNative() && b.format !== "physical" && user?.can_download)
      reading.push({
        key: "device",
        label: m.book_download_to_device(),
        icon: Share,
        run: () => void shareBook(downloadRequestFor(b)),
      });
    if (hasOriginal(b) && !isNative() && user?.can_download)
      reading.push({
        key: "original",
        label: m.book_download_original({ format: b.format.toUpperCase() }),
        icon: FileText,
        run: () => window.location.assign(`/api/books/${b.id}/original`),
      });
    if (canConvertZh(b))
      reading.push({
        key: "convert-zh",
        label: m.book_convert_zh(),
        icon: Languages,
        run: () => {
          target = b;
          showConvertZh = true;
        },
      });
    if (!isAdmin) return [reading];

    const manage: BookAction[] = [
      {
        key: "edit",
        label: m.book_edit_metadata(),
        icon: Pencil,
        run: () => goto(`/books/${b.id}/edit`),
      },
      {
        key: "refresh",
        label: m.book_refresh_metadata(),
        icon: RefreshCw,
        run: () => refreshMetadata(b),
      },
    ];
    // Calibre books are sync-managed: they cannot move, and one deleted
    // would come back with the next sync.
    const calibre = b.calibre_id != null;
    if (!calibre)
      manage.push({
        key: "move",
        label: m.book_move_library(),
        icon: FolderInput,
        run: () => openMove(b),
      });

    const work: BookAction[] = [];
    if (b.work_id) {
      const primary = primaryBookId === b.id;
      work.push(
        {
          key: "primary",
          label: primary ? m.work_is_primary() : m.work_set_as_primary(),
          icon: Star,
          tone: primary ? "fill-amber-500 text-amber-500" : undefined,
          disabled: primary || workLoading,
          run: () => setPrimary(b),
        },
        {
          key: "work-add",
          label: m.work_add_to_work(),
          icon: Plus,
          run: () => openWorkSearch(b, "add"),
        },
        {
          key: "work-remove",
          label: m.work_remove_from_work(),
          icon: Unlink,
          run: () => {
            target = b;
            showWorkRemove = true;
          },
        },
        {
          key: "work-split",
          label: m.work_split_work(),
          icon: Scissors,
          run: () => {
            target = b;
            showWorkSplit = true;
          },
        },
      );
    } else {
      work.push({
        key: "work-link",
        label: m.work_link_book(),
        icon: Link,
        run: () => openWorkSearch(b, "create"),
      });
    }
    // Where delete would be: why it, moving and converting are not here.
    if (calibre)
      work.push({
        key: "calibre",
        label: m.book_managed_by_calibre(),
        icon: HardDrive,
        disabled: true,
        run: () => {},
      });
    if (!calibre)
      work.push({
        key: "delete",
        label: m.book_delete(),
        icon: Trash2,
        destructive: true,
        run: () => remove(b),
      });
    return [reading, manage, work];
  });

  /** The book's actions in groups, a separator between them. */
  export function groups(): BookAction[][] {
    return actionGroups;
  }

  async function toggleFavorite(b: BookOut, value: boolean) {
    try {
      await booksApi.updateFavorite(b.id, value);
      onfavorite?.(b.id, value);
      toastStore.success(
        value ? m.book_favorite_added() : m.book_favorite_removed(),
      );
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function openShelves(b: BookOut) {
    try {
      shelves = await bookshelvesApi.list();
      target = b;
      showShelves = true;
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function addToShelf(shelfId: string) {
    if (!target) return;
    try {
      await bookshelvesApi.addBook(shelfId, target.id);
      toastStore.success(m.book_added_to_shelf());
      showShelves = false;
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function refreshMetadata(b: BookOut) {
    try {
      await booksApi.refreshMetadata(b.id);
      toastStore.success(m.book_refresh_queued());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function openMove(b: BookOut) {
    try {
      // Calibre libraries are sync-managed — not valid move targets.
      // A book from a list does not say which library it is in.
      const [libraries, own] = await Promise.all([
        librariesApi.list(),
        b.library_id ?? booksApi.get(b.id).then((full) => full.library_id),
      ]);
      moveLibraries = libraries.filter((l) => !l.calibre_path);
      moveFrom = own;
      target = b;
      showMove = true;
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function moveToLibrary(libraryId: string) {
    if (!target) return;
    const id = target.id;
    try {
      const result = await booksApi.moveToLibrary(id, libraryId);
      if (result.status === "moved") {
        toastStore.success(m.book_moved_library());
        onmoved?.(id, libraryId);
      }
      showMove = false;
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function remove(b: BookOut) {
    const ok = await confirmDialog({
      title: m.book_delete_confirm(),
      description: b.display_title ?? undefined,
      destructive: true,
    });
    if (!ok) return;
    try {
      await booksApi.delete(b.id);
      toastStore.success(m.book_deleted());
      ondeleted(b.id);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  // --- The book's work ---

  async function setPrimary(b: BookOut) {
    if (!b.work_id) return;
    try {
      await worksApi.update(b.work_id, { primary_book_id: b.id });
      primaryBookId = b.id;
      toastStore.success(m.work_primary_set());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function leftWork(id: string) {
    editions = [];
    primaryBookId = null;
    onwork?.(id, null);
  }

  async function workRemove() {
    if (!target?.work_id) return;
    const id = target.id;
    try {
      await worksApi.removeBook(target.work_id, id);
      leftWork(id);
      showWorkRemove = false;
      toastStore.success(m.work_book_removed());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function workSplit() {
    if (!target?.work_id) return;
    const id = target.id;
    try {
      await worksApi.deleteWork(target.work_id);
      leftWork(id);
      showWorkSplit = false;
      toastStore.success(m.work_split_success());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function workAddBook(otherId: string) {
    if (!target) return;
    const id = target.id;
    try {
      if (workSearchMode === "add" && target.work_id) {
        await worksApi.addBook(target.work_id, otherId);
        toastStore.success(m.work_book_added());
      } else {
        const work = await worksApi.create([id, otherId]);
        onwork?.(id, work.id);
        toastStore.success(m.work_created());
      }
      const data = await booksApi.getEditions(id);
      editions = data.editions;
      primaryBookId = data.primary_book_id;
      closeWorkSearch();
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function workSearch(query: string) {
    if (workSearchTimeout) clearTimeout(workSearchTimeout);
    if (query.length < 2) {
      workSearchResults = [];
      workSearchTotal = 0;
      workSearching = false;
      return;
    }
    workSearching = true;
    workSearchTimeout = setTimeout(async () => {
      try {
        const res = await booksApi.search(query, WORK_SEARCH_LIMIT);
        const editionIds = new Set(editions.map((e) => e.id));
        workSearchResults = res.items.filter(
          (r) => r.id !== target?.id && !editionIds.has(r.id),
        );
        workSearchTotal = res.total;
      } catch {
        workSearchResults = [];
        workSearchTotal = 0;
      } finally {
        workSearching = false;
      }
    }, 300);
  }

  function openWorkSearch(b: BookOut, mode: "add" | "create") {
    target = b;
    workSearchMode = mode;
    workSearchQuery = b.display_title ?? b.title ?? "";
    workSearchResults = [];
    workSearchTotal = 0;
    showWorkSearch = true;
    if (workSearchQuery) workSearch(workSearchQuery);
  }

  function closeWorkSearch() {
    showWorkSearch = false;
    workSearchQuery = "";
    workSearchResults = [];
    workSearchTotal = 0;
  }
</script>

<Modal
  title={m.book_add_to_bookshelf()}
  open={showShelves}
  onclose={() => (showShelves = false)}
  contentClass="sm:max-w-sm"
>
  <div class="-mx-3 space-y-0.5">
    {#if shelves.length === 0}
      <p class="px-3 text-muted-foreground text-sm">
        {m.book_no_bookshelves()}<a href="/bookshelves" class="text-primary"
          >{m.book_create_bookshelf()}</a
        >.
      </p>
    {:else}
      {#each shelves as shelf (shelf.id)}
        <button
          class="w-full flex items-center gap-3 text-left px-3 py-2.5 rounded-lg hover:bg-secondary transition-colors"
          onclick={() => addToShelf(shelf.id)}
        >
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm font-medium text-foreground"
              >{shelf.name}</span
            >
            {#if shelf.description}
              <span class="block truncate text-xs text-muted-foreground"
                >{shelf.description}</span
              >
            {/if}
          </span>
        </button>
      {/each}
    {/if}
  </div>
</Modal>

<Modal
  title={m.book_move_library()}
  open={showMove}
  onclose={() => (showMove = false)}
  contentClass="sm:max-w-sm"
>
  <div class="-mx-3 space-y-0.5">
    {#if moveLibraries.length === 0}
      <p class="px-3 text-muted-foreground text-sm">
        {m.book_move_library_none()}
      </p>
    {:else}
      {#each moveLibraries as library (library.id)}
        {@const current = library.id === moveFrom}
        <!-- The library the book is already in stays in the list, ticked
             and inert: the list then reads as "where it is, where it can
             go" rather than a bare set of names. -->
        <button
          class="w-full flex items-center gap-3 text-left px-3 py-2.5 rounded-lg transition-colors {current
            ? 'cursor-default'
            : 'hover:bg-secondary'}"
          disabled={current}
          aria-current={current ? "true" : undefined}
          onclick={() => moveToLibrary(library.id)}
        >
          <LibraryIcon
            size={16}
            class="shrink-0 {current
              ? 'text-primary'
              : 'text-muted-foreground'}"
          />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm font-medium text-foreground"
              >{library.name}</span
            >
            {#if library.description}
              <span class="block truncate text-xs text-muted-foreground"
                >{library.description}</span
              >
            {/if}
          </span>
          {#if current}
            <Check size={16} class="shrink-0 text-primary" />
          {:else}
            <span class="shrink-0 text-xs text-muted-foreground tabular-nums"
              >{m.collection_book_count({
                count: library.book_count ?? 0,
              })}</span
            >
          {/if}
        </button>
      {/each}
    {/if}
  </div>
</Modal>

{#if target}
  {@const id = target.id}
  <ReportIssueModal
    bookId={id}
    bind:open={showReport}
    onreported={() => onreported?.(id)}
  />

  <ZhConvertDialog
    open={showConvertZh}
    books={[{ id, title: target.display_title ?? "" }]}
    onclose={() => (showConvertZh = false)}
    onconverted={() => onconverted?.(id)}
  />
{/if}

<!-- Remove from Work Confirmation -->
<Dialog.Root bind:open={showWorkRemove}>
  <Dialog.Content class="sm:max-w-sm bg-popover">
    <Dialog.Header>
      <Dialog.Title>{m.work_remove_from_work()}</Dialog.Title>
      <Dialog.Description
        >{m.work_remove_from_work_confirm()}</Dialog.Description
      >
    </Dialog.Header>
    <Dialog.Footer>
      <Button
        variant="outline"
        class="rounded-xl"
        onclick={() => (showWorkRemove = false)}
      >
        {m.common_cancel()}
      </Button>
      <Button
        class="rounded-xl bg-destructive text-white hover:bg-destructive/90"
        onclick={workRemove}
      >
        {m.work_remove_from_work()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<!-- Split Work Confirmation -->
<Dialog.Root bind:open={showWorkSplit}>
  <Dialog.Content class="sm:max-w-sm bg-popover">
    <Dialog.Header>
      <Dialog.Title>{m.work_split_work()}</Dialog.Title>
      <Dialog.Description
        >{m.work_split_work_confirm({
          count: editions.length + 1,
        })}</Dialog.Description
      >
    </Dialog.Header>
    <Dialog.Footer>
      <Button
        variant="outline"
        class="rounded-xl"
        onclick={() => (showWorkSplit = false)}
      >
        {m.common_cancel()}
      </Button>
      <Button
        class="rounded-xl bg-destructive text-white hover:bg-destructive/90"
        onclick={workSplit}
      >
        {m.work_split_work()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<!-- Work Search Modal (Add to Work / Link to Another Book) -->
{#if showWorkSearch}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 z-[100] bg-black/50 backdrop-blur-sm"
    onclick={closeWorkSearch}
    onkeydown={(e) => e.key === "Escape" && (showWorkSearch = false)}
  >
    <div
      role="presentation"
      class="max-w-xl mt-[12vh] mx-4 sm:mx-auto bg-card rounded-2xl shadow-2xl border border-border/50 overflow-hidden"
      onclick={(e) => e.stopPropagation()}
    >
      <!-- Header -->
      <div class="px-4 py-3 border-b border-border/50">
        <p class="text-sm font-medium text-foreground">
          {workSearchMode === "add" ? m.work_add_to_work() : m.work_link_book()}
        </p>
      </div>

      <!-- Search input -->
      <div class="flex items-center gap-3 px-4 py-3 border-b border-border/50">
        <Search size={20} class="text-muted-foreground shrink-0" />
        <!-- svelte-ignore a11y_autofocus -->
        <input
          bind:value={workSearchQuery}
          oninput={() => workSearch(workSearchQuery)}
          placeholder={m.work_search_placeholder()}
          class="flex-1 bg-transparent text-foreground placeholder:text-muted-foreground outline-none text-base"
          autofocus
        />
        {#if workSearchQuery}
          <button
            aria-label={m.common_clear()}
            class="text-muted-foreground hover:text-foreground"
            onclick={() => {
              workSearchQuery = "";
              workSearchResults = [];
              workSearchTotal = 0;
            }}
          >
            <X size={16} />
          </button>
        {/if}
        <kbd
          class="hidden sm:inline text-xs text-muted-foreground bg-secondary px-1.5 py-0.5 rounded"
          >esc</kbd
        >
      </div>

      <!-- Results -->
      <div class="min-h-[240px] max-h-[60vh] overflow-y-auto">
        {#if workSearching}
          <div class="px-4 py-8 text-center text-muted-foreground text-sm">
            {m.work_searching()}
          </div>
        {:else if workSearchQuery.length >= 2 && workSearchResults.length === 0}
          <div class="px-4 py-8 text-center text-muted-foreground text-sm">
            {m.work_no_results()}
          </div>
        {:else}
          {#each workSearchResults as result (result.id)}
            <button
              class="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-secondary/50 transition-colors"
              onclick={() => workAddBook(result.id)}
            >
              <div
                class="w-10 h-14 shrink-0 rounded-sm overflow-hidden bg-secondary flex items-center justify-center"
              >
                {#if result.cover_path}
                  <img
                    use:authedSrc={coverUrl(
                      result.id,
                      result.updated_at,
                      "thumb",
                    )}
                    alt=""
                    class="w-full h-full object-cover"
                    loading="lazy"
                  />
                {:else}
                  <BookOpen size={16} class="text-muted-foreground/30" />
                {/if}
              </div>
              <div class="flex-1 min-w-0">
                <p class="text-sm font-medium text-foreground truncate">
                  {result.display_title ?? m.common_untitled()}
                </p>
                <p class="text-xs text-muted-foreground truncate">
                  {(result.display_authors ?? []).join(", ") || " "}
                </p>
              </div>
            </button>
          {/each}
          {#if workSearchTotal > WORK_SEARCH_LIMIT}
            <p
              class="px-4 py-3 text-center text-xs text-muted-foreground border-t border-border/50"
            >
              {m.work_search_more_results({ count: workSearchTotal })}
            </p>
          {/if}
        {/if}
      </div>
    </div>
  </div>
{/if}
