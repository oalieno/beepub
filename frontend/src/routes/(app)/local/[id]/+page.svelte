<script lang="ts">
  /**
   * The book page for a device-local book — the local library's twin of
   * /books/[id]: cover and descriptive metadata (read from the EPUB on
   * demand), reading status, notes and highlights, all kept in the device
   * records and synced like the reader's edits once the book is linked.
   */
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import {
    BookOpen,
    Bookmark,
    EllipsisVertical,
    History,
    Share,
    Trash2,
  } from "@lucide/svelte";
  import BackButton from "$lib/components/BackButton.svelte";
  import BackToTop from "$lib/components/BackToTop.svelte";
  import BottomSheet from "$lib/components/BottomSheet.svelte";
  import BookNotesEditor from "$lib/components/BookNotesEditor.svelte";
  import GeneratedCover from "$lib/components/GeneratedCover.svelte";
  import HighlightList from "$lib/components/HighlightList.svelte";
  import ReadingStatusSelect from "$lib/components/ReadingStatusSelect.svelte";
  import { BookDetailSkeleton } from "$lib/components/skeletons";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import { isNative } from "$lib/platform";
  import {
    emptyLocalInteraction,
    localSync,
    readLocalInteraction,
    readLocalProgress,
    setLocalNotes,
    setLocalReadingStatus,
    type LocalInteractionRecord,
  } from "$lib/reading/local";
  import {
    getLocalBook,
    getLocalCoverSrc,
    readLocalBookDetails,
    removeLocalBook,
    shareLocalBookFile,
    type LocalBookDetails,
    type LocalBookEntry,
  } from "$lib/services/localLibrary";
  import { sanitizeDescription } from "$lib/sanitize";
  import { confirmDialog } from "$lib/stores/confirm";
  import { keyboardVisible } from "$lib/stores/keyboard";
  import { toastStore } from "$lib/stores/toast";
  import type { HighlightOut, InteractionOut, ReadingStatus } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";

  let bookId = $derived(page.params.id as string);

  let loading = $state(true);
  let entry = $state<LocalBookEntry | null>(null);
  let coverSrc = $state<string | null>(null);
  let details = $state<LocalBookDetails | null>(null);
  let record = $state<LocalInteractionRecord>(emptyLocalInteraction());
  let percentage = $state<number | null>(null);
  let highlights = $state<HighlightOut[]>([]);
  let savingStatus = $state(false);
  let showMobileActions = $state(false);
  let wantToRead = $derived(record.reading_status === "want_to_read");
  let readLabel = $derived(
    percentage != null && percentage > 0
      ? m.book_continue_reading()
      : m.book_start_reading(),
  );

  function read() {
    goto(`/books/${bookId}/read`, { replaceState: true });
  }

  function toggleWantToRead() {
    void handleStatusChange(wantToRead ? null : "want_to_read");
  }

  // ReadingStatusSelect speaks the server's interaction shape.
  let interaction = $derived<InteractionOut>({
    rating: null,
    is_favorite: false,
    reading_progress: percentage != null ? { percentage } : null,
    reading_status: record.reading_status,
    started_at: record.started_at,
    finished_at: record.finished_at,
    notes: record.notes ?? null,
    updated_at: record.status_updated_at ?? "",
  } as InteractionOut);

  onMount(async () => {
    const found = await getLocalBook(bookId);
    if (!found) {
      await goto("/local", { replaceState: true });
      return;
    }
    entry = found;
    const [cover, stored, progress, marks] = await Promise.all([
      getLocalCoverSrc(found),
      readLocalInteraction(bookId),
      readLocalProgress(bookId),
      localSync.listHighlights(bookId),
    ]);
    coverSrc = cover;
    record = stored ?? emptyLocalInteraction();
    percentage = progress?.percentage ?? null;
    highlights = marks;
    loading = false;
    // The OPF parse is the slow part; the page stands without it.
    details = await readLocalBookDetails(bookId);
  });

  function pushSync() {
    void import("$lib/services/readingSync").then(({ syncLocalBook }) =>
      syncLocalBook(bookId).catch(() => {}),
    );
  }

  async function handleStatusChange(status: ReadingStatus | null) {
    savingStatus = true;
    try {
      // Same rule as the server book page: clearing the status clears
      // its dates, anything else keeps them.
      record = await setLocalReadingStatus(
        bookId,
        status,
        status ? record.started_at : null,
        status ? record.finished_at : null,
      );
      pushSync();
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      savingStatus = false;
    }
  }

  async function handleDateChange(
    field: "started_at" | "finished_at",
    value: string,
  ) {
    const date = value || null;
    record = await setLocalReadingStatus(
      bookId,
      record.reading_status,
      field === "started_at" ? date : record.started_at,
      field === "finished_at" ? date : record.finished_at,
    );
    pushSync();
  }

  async function saveNotes(notes: string | null) {
    record = await setLocalNotes(bookId, notes);
    pushSync();
  }

  async function deleteHighlight(hl: HighlightOut) {
    if (
      !(await confirmDialog({
        title: m.highlights_delete_confirm(),
        destructive: true,
      }))
    )
      return;
    const prev = highlights;
    highlights = highlights.filter((h) => h.id !== hl.id);
    try {
      await localSync.deleteHighlight(bookId, hl.id);
      toastStore.success(m.book_highlight_removed());
      pushSync();
    } catch (e) {
      toastStore.error((e as Error).message);
      highlights = prev;
    }
  }

  async function handleExport() {
    try {
      await shareLocalBookFile(bookId);
    } catch (err) {
      // Dismissing the share sheet also rejects — that is not an error.
      const msg = (err as Error).message ?? "";
      if (!/cancel/i.test(msg))
        toastStore.error(msg || m.local_export_failed());
    }
  }

  async function handleDelete() {
    if (!entry) return;
    if (
      !(await confirmDialog({
        title: m.local_delete_confirm({ title: entry.title }),
        destructive: true,
      }))
    )
      return;
    try {
      await removeLocalBook(bookId);
      void import("$lib/stores/linkedBooks").then(({ refreshLinkedBookIds }) =>
        refreshLinkedBookIds(),
      );
      toastStore.success(m.local_deleted());
      await goto("/local", { replaceState: true });
    } catch (err) {
      toastStore.error((err as Error).message);
    }
  }
</script>

<svelte:head>
  <title>{entry?.title ?? m.local_page_title()} - BeePub</title>
</svelte:head>

<!-- Bottom padding clears the phone's sticky action bar (and its safe
     area), as on the server book page. -->
<div
  class="max-w-5xl mx-auto px-6 sm:px-8 py-6 pb-[calc(6rem+env(safe-area-inset-bottom,0px))] md:pb-6"
>
  <!-- Live while the book loads, so a slow read never traps anyone. -->
  <div class="mb-6 -ml-1">
    <BackButton href="/local" onclick={() => history.back()} />
  </div>

  {#if loading}
    <BookDetailSkeleton />
  {:else if entry}
    <div class="flex flex-col md:flex-row gap-12">
      <div
        class="flex-shrink-0 w-64 mx-auto md:mx-0 flex justify-center md:self-start"
      >
        {#if coverSrc}
          <img
            src={coverSrc}
            alt="{entry.title} cover"
            class="max-w-full h-auto rounded-sm book-shadow"
          />
        {:else}
          <GeneratedCover
            title={entry.title}
            authors={entry.authors}
            class="w-full aspect-[2/3]"
          />
        {/if}
      </div>

      <div class="flex-1 min-w-0 flex flex-col md:pt-6">
        <h1 class="text-4xl font-bold leading-tight text-foreground">
          {entry.title}
        </h1>
        {#if entry.authors.length > 0}
          <p class="text-muted-foreground text-lg mt-2">
            {entry.authors.join(", ")}
          </p>
        {/if}

        <ReadingStatusSelect
          {interaction}
          saving={savingStatus}
          onstatuschange={handleStatusChange}
          ondatechange={handleDateChange}
        />

        <!-- Action buttons (desktop; phones get the sticky bar below) -->
        <div class="mt-auto pt-6 hidden md:flex items-center gap-2.5">
          <button
            onclick={read}
            class="h-10 flex items-center justify-center gap-2 bg-foreground hover:bg-foreground/90 text-background font-semibold px-5 rounded-full transition-colors whitespace-nowrap text-sm"
          >
            <BookOpen size={16} />
            {readLabel}
          </button>
          <button
            class="h-10 w-10 flex items-center justify-center bg-card card-soft rounded-full hover:shadow-md transition-all {wantToRead
              ? 'text-primary'
              : 'text-foreground'}"
            onclick={toggleWantToRead}
            title={wantToRead
              ? m.book_remove_want_to_read()
              : m.book_want_to_read()}
          >
            <Bookmark size={16} class={wantToRead ? "fill-primary" : ""} />
          </button>
          <DropdownMenu.Root>
            <DropdownMenu.Trigger
              class="h-10 w-10 flex items-center justify-center bg-card card-soft rounded-full text-muted-foreground hover:text-foreground hover:shadow-md transition-all"
              aria-label={m.book_more_actions()}
            >
              <EllipsisVertical size={16} />
            </DropdownMenu.Trigger>
            <DropdownMenu.Content align="start" side="top">
              {#if isNative()}
                <DropdownMenu.Item onclick={handleExport}>
                  <Share size={14} />
                  {m.local_export()}
                </DropdownMenu.Item>
              {/if}
              <DropdownMenu.Item
                onclick={() => goto(`/books/${bookId}/read-legacy`)}
              >
                <History size={14} />
                {m.book_open_reader_legacy()}
              </DropdownMenu.Item>
              <DropdownMenu.Separator />
              <DropdownMenu.Item variant="destructive" onclick={handleDelete}>
                <Trash2 size={14} />
                {m.local_delete()}
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        </div>
      </div>
    </div>

    {#if details?.description || details?.publisher || details?.published}
      <div class="border-t border-border my-8"></div>
      <div class="flex flex-col md:flex-row gap-10">
        {#if details.description}
          <div class="flex-1 min-w-0">
            <h2 class="text-xl font-bold mb-3 text-foreground">
              {m.book_description()}
            </h2>
            <div
              class="text-muted-foreground leading-relaxed prose-description"
            >
              {@html sanitizeDescription(details.description)}
            </div>
          </div>
        {/if}
        {#if details.publisher || details.published}
          <dl class="md:w-64 shrink-0 space-y-3 text-sm">
            {#if details.publisher}
              <div>
                <dt class="text-muted-foreground">
                  {m.metadata_label_publisher()}
                </dt>
                <dd class="text-foreground">{details.publisher}</dd>
              </div>
            {/if}
            {#if details.published}
              <div>
                <dt class="text-muted-foreground">
                  {m.metadata_label_published()}
                </dt>
                <dd class="text-foreground">
                  {details.published.slice(0, 10)}
                </dd>
              </div>
            {/if}
          </dl>
        {/if}
      </div>
    {/if}

    <div class="border-t border-border my-8"></div>
    <BookNotesEditor
      {bookId}
      initialNotes={record.notes ?? ""}
      saveFn={saveNotes}
    />

    {#if highlights.length > 0}
      <div class="border-t border-border my-8"></div>
      <h2 class="text-xl font-bold mb-3 text-foreground">
        {m.book_highlights()}
      </h2>
      <div class="bg-card card-soft rounded-2xl p-4 max-h-80 overflow-y-auto">
        <HighlightList
          {highlights}
          onselect={(hl) =>
            goto(
              `/books/${bookId}/read?cfi=${encodeURIComponent(hl.cfi_range)}`,
            )}
          ondelete={deleteHighlight}
        />
      </div>
    {/if}
  {/if}
</div>

{#if entry && !loading}
  <BackToTop />
{/if}

<!-- Phone sticky action bar, the same bar as the server book page -->
{#if entry && !loading && !$keyboardVisible}
  <div
    class="fixed bottom-0 left-0 right-0 z-40 md:hidden bg-background/95 backdrop-blur-sm border-t border-border px-4 pt-3"
    style="padding-bottom: max(0.75rem, env(safe-area-inset-bottom));"
  >
    <div class="flex items-center gap-2.5" style="max-width: 900px;">
      <button
        onclick={read}
        class="h-12 flex-1 flex items-center justify-center gap-2 bg-foreground hover:bg-foreground/90 text-background font-semibold rounded-full transition-colors text-base"
      >
        <BookOpen size={16} />
        {readLabel}
      </button>
      <button
        class="h-12 w-12 flex items-center justify-center bg-card card-soft rounded-full transition-all {wantToRead
          ? 'text-primary'
          : 'text-foreground'}"
        onclick={toggleWantToRead}
        title={wantToRead
          ? m.book_remove_want_to_read()
          : m.book_want_to_read()}
      >
        <Bookmark size={18} class={wantToRead ? "fill-primary" : ""} />
      </button>
      <button
        aria-label={m.book_more_actions()}
        class="h-12 w-12 flex items-center justify-center bg-card card-soft rounded-full text-muted-foreground transition-all"
        onclick={() => (showMobileActions = true)}
      >
        <EllipsisVertical size={18} />
      </button>
    </div>
  </div>

  <BottomSheet bind:open={showMobileActions}>
    {#if isNative()}
      <button
        class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
        onclick={() => {
          showMobileActions = false;
          void handleExport();
        }}
      >
        <Share size={20} class="text-muted-foreground shrink-0" />
        {m.local_export()}
      </button>
    {/if}
    <button
      class="flex items-center gap-4 w-full px-2 py-3.5 text-foreground text-[15px] rounded-lg active:bg-secondary transition-colors"
      onclick={() => {
        showMobileActions = false;
        goto(`/books/${bookId}/read-legacy`);
      }}
    >
      <History size={20} class="text-muted-foreground shrink-0" />
      {m.book_open_reader_legacy()}
    </button>
    <button
      class="flex items-center gap-4 w-full px-2 py-3.5 text-destructive text-[15px] rounded-lg active:bg-secondary transition-colors"
      onclick={() => {
        showMobileActions = false;
        void handleDelete();
      }}
    >
      <Trash2 size={20} class="shrink-0" />
      {m.local_delete()}
    </button>
  </BottomSheet>
{/if}
