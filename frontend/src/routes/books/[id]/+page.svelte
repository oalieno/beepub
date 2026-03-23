<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { booksApi } from "$lib/api/books";
  import { bookshelvesApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import StarRating from "$lib/components/StarRating.svelte";
  import Modal from "$lib/components/Modal.svelte";
  import type {
    BookOut,
    ExternalMetadataOut,
    BookshelfOut,
    InteractionOut,
    HighlightOut,
    ReadingStatus,
  } from "$lib/types";
  import HighlightList from "$lib/components/HighlightList.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { UserRole } from "$lib/types";
  import {
    Heart,
    BookOpen,
    Trash2,
    Pencil,
    RefreshCw,
    BookMarked,
    Star,
    StarHalf,
    EllipsisVertical,
    NotebookPen,
    Bookmark,
    BookOpenCheck,
    CircleCheck,
    CircleX,
    ArrowLeft,
    Undo2,
  } from "@lucide/svelte";
  import * as Select from "$lib/components/ui/select";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import DatePicker from "$lib/components/DatePicker.svelte";
  import { marked } from "marked";

  const READING_STATUS_OPTIONS: {
    value: ReadingStatus;
    label: string;
    icon: typeof Bookmark;
  }[] = [
    { value: "want_to_read", label: "Want to Read", icon: Bookmark },
    {
      value: "currently_reading",
      label: "Currently Reading",
      icon: BookOpenCheck,
    },
    { value: "read", label: "Read", icon: CircleCheck },
    { value: "did_not_finish", label: "Did Not Finish", icon: CircleX },
  ];

  const CLEAR_STATUS_VALUE = "__clear_status__";

  const SOURCE_META: Record<
    string,
    {
      label: string;
      color: string;
      logo: string;
      urlPrefix: string;
      idPattern: RegExp;
      idHint: string;
    }
  > = {
    goodreads: {
      label: "Goodreads",
      color: "#5C4B3A",
      logo: "g",
      urlPrefix: "https://www.goodreads.com/book/show/",
      idPattern: /^\d+[\w-]*$/,
      idHint: "e.g. 33017208",
    },
    readmoo: {
      label: "Readmoo",
      color: "#2E7D32",
      logo: "R",
      urlPrefix: "https://readmoo.com/book/",
      idPattern: /^\d+$/,
      idHint: "e.g. 210227953000101",
    },
  };

  function renderStars(rating: number): {
    full: number;
    half: boolean;
    empty: number;
  } {
    const full = Math.floor(rating);
    const half = rating - full >= 0.25 && rating - full < 0.75;
    const extra = rating - full >= 0.75 ? 1 : 0;
    const totalFull = full + extra;
    const empty = 5 - totalFull - (half ? 1 : 0);
    return { full: totalFull, half, empty };
  }

  function handleAuthorFilter(author: string) {
    const q = author.trim();
    if (!q || !book?.library_id) return;

    const params = new URLSearchParams({ author: q });
    goto(`/libraries/${book.library_id}?${params.toString()}`);
  }

  function handleSeriesFilter(seriesName: string) {
    if (!seriesName || !book?.library_id) return;
    const params = new URLSearchParams({ series: seriesName });
    goto(`/libraries/${book.library_id}?${params.toString()}`);
  }

  function handleTagFilter(tag: string) {
    if (!tag || !book?.library_id) return;
    const params = new URLSearchParams({ tag });
    goto(`/libraries/${book.library_id}?${params.toString()}`);
  }

  function formatSeriesIndex(idx: number | null | undefined): string {
    if (idx == null) return "";
    return Number.isInteger(idx) ? String(idx) : String(idx);
  }

  function handleStatusSelectChange(value: string) {
    if (value === CLEAR_STATUS_VALUE) {
      handleStatusChange(null);
      return;
    }
    handleStatusChange(value as ReadingStatus);
  }

  let bookId = $derived(page.params.id as string);

  let book = $state<BookOut | null>(null);
  let interaction = $state<InteractionOut | null>(null);
  let externalMeta = $state<ExternalMetadataOut[]>([]);
  let bookshelves = $state<BookshelfOut[]>([]);
  let bookHighlights = $state<HighlightOut[]>([]);
  let similarBooks = $state<BookOut[]>([]);
  let loading = $state(true);
  let showEditModal = $state(false);
  let showAddToShelf = $state(false);
  let showNotesModal = $state(false);
  let editForm = $state({
    title: "",
    authors: "",
    description: "",
    publisher: "",
    published_date: "",
    series: "",
    series_index: "",
    tags: "",
  });
  let notesText = $state("");
  let savingNotes = $state(false);
  let savingStatus = $state(false);
  let editingUrlSource = $state<string | null>(null);
  let editingUrlValue = $state("");

  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);

  onMount(() => {
    if (!$authStore.token) {
      goto("/login");
    }
  });

  $effect(() => {
    // Re-load data when bookId changes (e.g. navigating from similar books)
    bookId;
    if ($authStore.token) {
      loadData();
      window.scrollTo(0, 0);
    }
  });

  async function loadData() {
    loading = true;
    try {
      const [b, ext, shelves] = await Promise.all([
        booksApi.get(bookId, $authStore.token!),
        booksApi
          .getExternal(bookId, $authStore.token!)
          .catch(() => [] as ExternalMetadataOut[]),
        bookshelvesApi.list($authStore.token!),
      ]);
      book = b;
      externalMeta = ext;
      bookshelves = shelves;
      if (book) {
        editForm = {
          title: book.title ?? "",
          authors: (book.authors ?? []).join(", "),
          description: book.description ?? "",
          publisher: book.publisher ?? "",
          published_date: book.published_date ?? "",
          series: book.series ?? "",
          series_index:
            book.series_index != null ? String(book.series_index) : "",
          tags: (book.tags ?? []).join(", "),
        };
      }
      // Load user interaction (rating, favorite, progress)
      try {
        interaction = await booksApi.getInteraction(bookId, $authStore.token!);
      } catch {
        // ignore
      }
      // Load highlights
      try {
        bookHighlights = await booksApi.getHighlights(
          bookId,
          $authStore.token!,
        );
      } catch {
        // ignore
      }
      // Load similar books
      try {
        similarBooks = await booksApi.getSimilar(bookId, $authStore.token!, 10);
      } catch {
        similarBooks = [];
      }
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleRating(rating: number) {
    if (!book || !$authStore.token) return;
    try {
      await booksApi.updateRating(bookId, rating, $authStore.token);
      if (interaction) interaction = { ...interaction, rating };
      else
        interaction = {
          rating,
          is_favorite: false,
          reading_progress: null,
          reading_status: null,
          started_at: null,
          finished_at: null,
          notes: null,
          updated_at: "",
        };
      toastStore.success("Rating updated");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function toggleFavorite() {
    if (!book || !$authStore.token) return;
    const newVal = !interaction?.is_favorite;
    try {
      await booksApi.updateFavorite(bookId, newVal, $authStore.token);
      if (interaction) interaction = { ...interaction, is_favorite: newVal };
      else
        interaction = {
          rating: null,
          is_favorite: newVal,
          reading_progress: null,
          reading_status: null,
          started_at: null,
          finished_at: null,
          notes: null,
          updated_at: "",
        };
      toastStore.success(
        newVal ? "Added to favorites" : "Removed from favorites",
      );
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleSaveEdit() {
    if (!book || !$authStore.token) return;
    try {
      const parsedTags = editForm.tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const updated = await booksApi.updateMetadata(
        bookId,
        {
          title: editForm.title || null,
          authors:
            editForm.authors
              .split(",")
              .map((a) => a.trim())
              .filter(Boolean).length > 0
              ? editForm.authors
                  .split(",")
                  .map((a) => a.trim())
                  .filter(Boolean)
              : null,
          description: editForm.description || null,
          publisher: editForm.publisher || null,
          published_date: editForm.published_date || null,
          series: editForm.series || null,
          series_index: editForm.series_index
            ? parseFloat(editForm.series_index)
            : null,
          tags: parsedTags.length > 0 ? parsedTags : null,
        },
        $authStore.token,
      );
      book = updated;
      showEditModal = false;
      toastStore.success("Metadata updated");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleDelete() {
    if (!confirm("Delete this book permanently?") || !$authStore.token) return;
    try {
      await booksApi.delete(bookId, $authStore.token);
      toastStore.success("Book deleted");
      goto("/");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleRefreshMeta() {
    if (!$authStore.token) return;
    try {
      await booksApi.refreshMetadata(bookId, $authStore.token);
      toastStore.success("Metadata refresh queued");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function extractSourceId(source: string, url: string | null): string {
    if (!url) return "";
    const prefix = SOURCE_META[source]?.urlPrefix ?? "";
    if (prefix && url.startsWith(prefix)) {
      return url.slice(prefix.length);
    }
    return url;
  }

  function startEditUrl(source: string, currentUrl: string | null) {
    editingUrlSource = source;
    editingUrlValue = extractSourceId(source, currentUrl);
  }

  async function saveExternalUrl() {
    if (!editingUrlSource || !$authStore.token) return;
    try {
      const id = editingUrlValue.trim();
      if (id) {
        const meta = SOURCE_META[editingUrlSource];
        if (meta && !meta.idPattern.test(id)) {
          toastStore.error(`Invalid ID format. ${meta.idHint}`);
          return;
        }
        const prefix = meta?.urlPrefix ?? "";
        const fullUrl = prefix + id;
        await booksApi.updateExternalUrl(
          bookId,
          editingUrlSource,
          fullUrl,
          $authStore.token,
        );
      } else {
        await booksApi.updateExternalUrl(
          bookId,
          editingUrlSource,
          null,
          $authStore.token,
        );
      }
      // Reload external metadata after a short delay for the refresh
      externalMeta = await booksApi
        .getExternal(bookId, $authStore.token)
        .catch(() => [] as ExternalMetadataOut[]);
      editingUrlSource = null;
      toastStore.success(
        id ? "Source URL updated, fetching metadata..." : "Source URL removed",
      );
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleStatusChange(newStatus: ReadingStatus | null) {
    if (!book || !$authStore.token) return;
    savingStatus = true;
    try {
      const shouldClearDates = newStatus === null;
      const data: {
        reading_status: ReadingStatus | null;
        started_at?: string | null;
        finished_at?: string | null;
      } = {
        reading_status: newStatus || null,
        started_at: shouldClearDates ? null : (interaction?.started_at ?? null),
        finished_at: shouldClearDates
          ? null
          : (interaction?.finished_at ?? null),
      };
      await booksApi.updateReadingStatus(bookId, data, $authStore.token);
      if (interaction) {
        interaction = {
          ...interaction,
          reading_status: newStatus || null,
          started_at: shouldClearDates ? null : interaction.started_at,
          finished_at: shouldClearDates ? null : interaction.finished_at,
        };
      } else
        interaction = {
          rating: null,
          is_favorite: false,
          reading_progress: null,
          reading_status: newStatus || null,
          started_at: null,
          finished_at: null,
          notes: null,
          updated_at: "",
        };
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
    if (!book || !$authStore.token) return;
    const dateVal = value || null;
    try {
      const data = {
        reading_status: interaction?.reading_status ?? null,
        started_at:
          field === "started_at" ? dateVal : (interaction?.started_at ?? null),
        finished_at:
          field === "finished_at"
            ? dateVal
            : (interaction?.finished_at ?? null),
      };
      await booksApi.updateReadingStatus(bookId, data, $authStore.token);
      if (interaction) interaction = { ...interaction, [field]: dateVal };
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function handleSaveNotes() {
    if (!book || !$authStore.token) return;
    savingNotes = true;
    try {
      await booksApi.updateNotes(bookId, notesText || null, $authStore.token);
      if (interaction)
        interaction = { ...interaction, notes: notesText || null };
      else
        interaction = {
          rating: null,
          is_favorite: false,
          reading_progress: null,
          reading_status: null,
          started_at: null,
          finished_at: null,
          notes: notesText || null,
          updated_at: "",
        };
      showNotesModal = false;
      toastStore.success("Notes saved");
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      savingNotes = false;
    }
  }

  async function addToShelf(shelfId: string) {
    if (!$authStore.token) return;
    try {
      await bookshelvesApi.addBook(shelfId, bookId, $authStore.token);
      toastStore.success("Added to bookshelf");
      showAddToShelf = false;
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<svelte:head>
  <title>{book?.display_title ?? "Book"} - BeePub</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
  {#if loading}
    <div class="flex items-center justify-center h-64">
      <Spinner size="lg" />
    </div>
  {:else if book}
    <!-- Back Button -->
    <button
      class="flex items-center gap-1.5 text-muted-foreground hover:text-foreground transition-colors mb-6 -ml-1"
      onclick={() => history.back()}
    >
      <ArrowLeft size={18} />
      <span class="text-sm">Back</span>
    </button>

    <!-- Hero Section -->
    <div class="flex flex-col md:flex-row gap-12">
      <!-- Cover -->
      <div
        class="flex-shrink-0 w-64 mx-auto md:mx-0 flex justify-center md:self-start"
      >
        {#if book.cover_path}
          <img
            src="/covers/{book.id}.jpg"
            alt="{book.display_title} cover"
            class="max-w-full h-auto rounded-sm book-shadow"
          />
        {:else}
          <div
            class="w-full aspect-[2/3] rounded-sm bg-secondary flex items-center justify-center book-shadow"
          >
            <BookOpen class="text-muted-foreground/30" size={48} />
          </div>
        {/if}
      </div>

      <!-- Info -->
      <div class="flex-1 min-w-0 flex flex-col pt-6">
        <div>
          <h1 class="text-4xl font-bold leading-tight text-foreground">
            {book.display_title ?? "Untitled"}
          </h1>
          {#if (book.display_authors ?? []).length > 0}
            <p class="text-muted-foreground text-lg mt-2">
              {#each book.display_authors ?? [] as author, idx}
                <button
                  type="button"
                  class="hover:text-foreground hover:underline transition-colors"
                  onclick={() => handleAuthorFilter(author)}
                >
                  {author}
                </button>{idx < (book.display_authors ?? []).length - 1
                  ? ", "
                  : ""}
              {/each}
            </p>
          {/if}
        </div>

        <!-- Rating -->
        <div class="mt-5">
          <p class="text-sm text-muted-foreground mb-1.5">Your rating</p>
          <StarRating
            value={interaction?.rating ?? null}
            onchange={handleRating}
          />
        </div>

        <!-- External Ratings (compact inline) -->
        {#if externalMeta.length > 0 || isAdmin}
          <div class="mt-4 flex flex-wrap items-center gap-4">
            {#each externalMeta as meta}
              {@const src = SOURCE_META[meta.source] ?? {
                label: meta.source,
                color: "#666",
                logo: "?",
                urlPrefix: "",
                idPattern: /^.+$/,
                idHint: "ID",
              }}
              {@const stars =
                meta.rating != null ? renderStars(meta.rating) : null}
              {#if editingUrlSource === meta.source}
                <div class="flex items-center gap-2">
                  <span class="text-muted-foreground text-sm font-medium"
                    >{src.label}</span
                  >
                  <span class="text-xs text-muted-foreground"
                    >{src.urlPrefix}</span
                  >
                  <input
                    bind:value={editingUrlValue}
                    placeholder={src.idHint}
                    class="border border-input bg-background rounded-lg px-2 py-1 text-sm text-foreground w-40 focus:outline-none focus:ring-2 focus:ring-primary/30"
                  />
                  <button
                    class="text-xs text-primary hover:text-primary/80 font-medium"
                    onclick={saveExternalUrl}>Save</button
                  >
                  <button
                    class="text-xs text-muted-foreground hover:text-foreground"
                    onclick={() => (editingUrlSource = null)}>Cancel</button
                  >
                </div>
              {:else}
                <a
                  href={meta.source_url ?? "#"}
                  target={meta.source_url ? "_blank" : undefined}
                  rel={meta.source_url ? "noopener" : undefined}
                  class="flex items-center gap-2 hover:opacity-80 transition-opacity"
                  onclick={meta.source_url
                    ? undefined
                    : (e: MouseEvent) => e.preventDefault()}
                >
                  <span class="text-muted-foreground text-sm font-medium"
                    >{src.label}</span
                  >
                  {#if meta.rating != null && stars}
                    <span class="text-lg font-bold text-foreground"
                      >{meta.rating.toFixed(1)}</span
                    >
                    <div class="flex items-center gap-px">
                      {#each Array(stars.full) as _}
                        <Star
                          size={12}
                          class="fill-muted-foreground text-muted-foreground"
                        />
                      {/each}
                      {#if stars.half}
                        <StarHalf
                          size={12}
                          class="fill-muted-foreground text-muted-foreground"
                        />
                      {/if}
                      {#each Array(stars.empty) as _}
                        <Star size={12} class="text-muted-foreground/30" />
                      {/each}
                    </div>
                  {:else}
                    <span class="text-muted-foreground text-sm">-</span>
                  {/if}
                </a>
                {#if isAdmin}
                  <button
                    class="text-muted-foreground hover:text-foreground"
                    onclick={() => startEditUrl(meta.source, meta.source_url)}
                    title="Edit source URL"
                  >
                    <Pencil size={12} />
                  </button>
                {/if}
              {/if}
            {/each}
            {#if isAdmin}
              {@const existingSources = new Set(
                externalMeta.map((m) => m.source),
              )}
              {#each Object.entries(SOURCE_META) as [key, src]}
                {#if !existingSources.has(key)}
                  {#if editingUrlSource === key}
                    <div class="flex items-center gap-2">
                      <span class="text-muted-foreground text-sm font-medium"
                        >{src.label}</span
                      >
                      <span class="text-xs text-muted-foreground"
                        >{src.urlPrefix}</span
                      >
                      <input
                        bind:value={editingUrlValue}
                        placeholder={src.idHint}
                        class="border border-input bg-background rounded-lg px-2 py-1 text-sm text-foreground w-40 focus:outline-none focus:ring-2 focus:ring-primary/30"
                      />
                      <button
                        class="text-xs text-primary hover:text-primary/80 font-medium"
                        onclick={saveExternalUrl}>Save</button
                      >
                      <button
                        class="text-xs text-muted-foreground hover:text-foreground"
                        onclick={() => (editingUrlSource = null)}>Cancel</button
                      >
                    </div>
                  {:else}
                    <button
                      class="flex items-center gap-1 text-muted-foreground/50 hover:text-muted-foreground text-sm"
                      onclick={() => startEditUrl(key, null)}
                    >
                      + {src.label}
                    </button>
                  {/if}
                {/if}
              {/each}
            {/if}
          </div>
        {/if}

        <!-- Reading Status -->
        <div class="mt-5">
          <div class="flex flex-wrap items-center gap-3">
            <Select.Root
              type="single"
              value={interaction?.reading_status ?? undefined}
              onValueChange={handleStatusSelectChange}
              disabled={savingStatus}
            >
              <Select.Trigger
                class="rounded-full bg-white {interaction?.reading_status ===
                'read'
                  ? 'text-green-600 border-green-600/30'
                  : ''}"
              >
                {#if interaction?.reading_status}
                  {@const current = READING_STATUS_OPTIONS.find(
                    (o) => o.value === interaction?.reading_status,
                  )}
                  {#if current}
                    <current.icon
                      size={14}
                      class={interaction?.reading_status === "read"
                        ? "text-green-600"
                        : ""}
                    />
                    {current.label}
                  {/if}
                {:else}
                  Set status
                {/if}
              </Select.Trigger>
              <Select.Content align="start">
                <Select.Item value={CLEAR_STATUS_VALUE}>
                  {#snippet children()}
                    <BookMarked size={14} class="text-muted-foreground" />
                    <span>Clear status</span>
                  {/snippet}
                </Select.Item>
                <Select.Separator />
                {#each READING_STATUS_OPTIONS as opt}
                  <Select.Item value={opt.value}>
                    {#snippet children({ selected })}
                      <opt.icon
                        size={14}
                        class={opt.value === "read" && selected
                          ? "text-green-600"
                          : "text-muted-foreground"}
                      />
                      <span>{opt.label}</span>
                    {/snippet}
                  </Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
            {#if interaction?.reading_status === "read" || interaction?.reading_status === "currently_reading"}
              <div class="flex items-center gap-2">
                <span class="text-xs text-muted-foreground">Started</span>
                <DatePicker
                  value={interaction?.started_at ?? null}
                  onchange={(v) => handleDateChange("started_at", v ?? "")}
                />
              </div>
            {/if}
            {#if interaction?.reading_status === "read"}
              <div class="flex items-center gap-2">
                <span class="text-xs text-muted-foreground">Finished</span>
                <DatePicker
                  value={interaction?.finished_at ?? null}
                  onchange={(v) => handleDateChange("finished_at", v ?? "")}
                />
              </div>
            {/if}
          </div>
        </div>

        <!-- Action Buttons -->
        <div class="mt-auto pt-6 flex items-center gap-3">
          <button
            onclick={() =>
              goto(`/books/${book!.id}/read`, { replaceState: true })}
            class="flex items-center justify-center gap-2 bg-foreground hover:bg-foreground/90 text-background font-semibold px-4 sm:px-6 py-3 rounded-full transition-colors whitespace-nowrap text-sm sm:text-base"
          >
            <BookOpen size={16} />
            Start Reading
          </button>
          <button
            class="w-10 h-10 flex items-center justify-center bg-card card-soft rounded-full text-foreground hover:shadow-md transition-all"
            onclick={toggleFavorite}
            title={interaction?.is_favorite
              ? "Remove from favorites"
              : "Add to favorites"}
          >
            <Heart
              size={16}
              class={interaction?.is_favorite
                ? "fill-red-500 text-red-500"
                : ""}
            />
          </button>
          <button
            class="w-10 h-10 flex items-center justify-center bg-card card-soft rounded-full text-foreground hover:shadow-md transition-all"
            onclick={() => (showAddToShelf = true)}
            title="Add to bookshelf"
          >
            <BookMarked size={16} />
          </button>
          <button
            class="w-10 h-10 flex items-center justify-center bg-card card-soft rounded-full text-foreground hover:shadow-md transition-all"
            onclick={() => {
              notesText = interaction?.notes ?? "";
              showNotesModal = true;
            }}
            title="Notes"
          >
            <NotebookPen
              size={16}
              class={interaction?.notes ? "text-primary" : ""}
            />
          </button>
          {#if isAdmin}
            <DropdownMenu.Root>
              <DropdownMenu.Trigger>
                <button
                  class="w-10 h-10 flex items-center justify-center bg-card card-soft rounded-full text-muted-foreground hover:text-foreground hover:shadow-md transition-all"
                  title="Admin actions"
                >
                  <EllipsisVertical size={16} />
                </button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Content align="start" side="top">
                <DropdownMenu.Item onclick={() => (showEditModal = true)}>
                  <Pencil size={14} />
                  Edit metadata
                </DropdownMenu.Item>
                <DropdownMenu.Item onclick={handleRefreshMeta}>
                  <RefreshCw size={14} />
                  Refresh metadata
                </DropdownMenu.Item>
                <DropdownMenu.Separator />
                <DropdownMenu.Item variant="destructive" onclick={handleDelete}>
                  <Trash2 size={14} />
                  Delete book
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Root>
          {/if}
        </div>
      </div>
    </div>

    <!-- Separator -->
    <div class="border-t border-border my-8"></div>

    <!-- Description + Metadata -->
    <div class="flex flex-col md:flex-row gap-10">
      {#if book.description ?? book.epub_description}
        <div class="flex-1 min-w-0 order-last md:order-none">
          <h2 class="text-xl font-bold mb-3 text-foreground">Description</h2>
          <div class="text-muted-foreground leading-relaxed prose-description">
            {@html book.description ?? book.epub_description}
          </div>
        </div>
      {/if}

      <div class="flex-shrink-0 w-full md:w-64 order-first md:order-none">
        <div class="flex flex-col gap-4 text-sm">
          {#if book.display_series}
            <div>
              <span class="text-muted-foreground block text-xs mb-0.5"
                >Series</span
              >
              <button
                class="text-foreground font-medium hover:text-primary hover:underline transition-colors"
                onclick={() => book && handleSeriesFilter(book.display_series!)}
              >
                {book.display_series}{#if book.display_series_index != null}
                  [{formatSeriesIndex(book.display_series_index)}]{/if}
              </button>
            </div>
          {/if}
          {#if book.publisher ?? book.epub_publisher}
            <div>
              <span class="text-muted-foreground block text-xs mb-0.5"
                >Publisher</span
              >
              <span class="text-foreground font-medium"
                >{book.publisher ?? book.epub_publisher}</span
              >
            </div>
          {/if}
          {#if book.published_date ?? book.epub_published_date}
            <div>
              <span class="text-muted-foreground block text-xs mb-0.5"
                >Published</span
              >
              <span class="text-foreground font-medium"
                >{book.published_date ?? book.epub_published_date}</span
              >
            </div>
          {/if}
          {#if book.epub_language}
            <div>
              <span class="text-muted-foreground block text-xs mb-0.5"
                >Language</span
              >
              <span class="text-foreground font-medium"
                >{book.epub_language}</span
              >
            </div>
          {/if}
          {#if book.epub_isbn}
            <div>
              <span class="text-muted-foreground block text-xs mb-0.5"
                >ISBN</span
              >
              <span class="text-foreground font-medium">{book.epub_isbn}</span>
            </div>
          {/if}
          <div>
            <span class="text-muted-foreground block text-xs mb-0.5"
              >File Size</span
            >
            <span class="text-foreground font-medium"
              >{book.file_size < 1_048_576
                ? (book.file_size / 1024).toFixed(1) + " KB"
                : (book.file_size / 1_048_576).toFixed(1) + " MB"}</span
            >
          </div>
          {#if book.word_count}
            <div>
              <span class="text-muted-foreground block text-xs mb-0.5"
                >Word Count</span
              >
              <span class="text-foreground font-medium"
                >{book.word_count.toLocaleString()}</span
              >
            </div>
          {/if}
          {#if (book.display_tags ?? []).length > 0}
            <div>
              <span class="text-muted-foreground block text-xs mb-1">Tags</span>
              <div class="flex flex-wrap gap-1.5">
                {#each book.display_tags ?? [] as tag}
                  <button
                    class="text-xs px-2 py-0.5 rounded-full bg-secondary text-foreground hover:bg-secondary/80 transition-colors"
                    onclick={() => handleTagFilter(tag)}
                  >
                    {tag}
                  </button>
                {/each}
              </div>
            </div>
          {/if}
          {#if (book.ai_tags ?? []).length > 0}
            <div>
              <span class="text-muted-foreground block text-xs mb-1"
                >AI Tags</span
              >
              <div class="flex flex-wrap gap-1.5">
                {#each book.ai_tags ?? [] as aiTag}
                  {@const categoryStyles = {
                    genre:
                      "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
                    mood: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300",
                    topic:
                      "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
                  }}
                  <button
                    class="text-xs px-2 py-0.5 rounded-full transition-colors hover:opacity-80 {categoryStyles[
                      aiTag.category
                    ] ?? 'bg-secondary text-foreground'}"
                    onclick={() => handleTagFilter(aiTag.tag)}
                    title="{aiTag.category} · {Math.round(
                      aiTag.confidence * 100,
                    )}% confidence"
                  >
                    {aiTag.label}
                  </button>
                {/each}
              </div>
            </div>
          {/if}
        </div>
      </div>
    </div>

    <!-- Notes -->
    {#if interaction?.notes}
      <div class="border-t border-border my-8"></div>
      <div>
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-xl font-bold text-foreground">Notes</h2>
          <button
            class="text-sm text-muted-foreground hover:text-foreground transition-colors"
            onclick={() => {
              notesText = interaction?.notes ?? "";
              showNotesModal = true;
            }}
          >
            Edit
          </button>
        </div>
        <div
          class="bg-card card-soft rounded-2xl p-4 prose-description text-muted-foreground leading-relaxed"
        >
          {@html marked.parse(interaction.notes)}
        </div>
      </div>
    {/if}

    <!-- Highlights -->
    {#if bookHighlights.length > 0}
      <div class="border-t border-border my-8"></div>
      <div>
        <h2 class="text-xl font-bold mb-3 text-foreground">Highlights</h2>
        <div class="bg-card card-soft rounded-2xl p-4 max-h-80 overflow-y-auto">
          <HighlightList
            highlights={bookHighlights}
            onselect={(hl) => goto(`/books/${bookId}/read`)}
            ondelete={async (hl) => {
              if (!$authStore.token) return;
              try {
                await booksApi.deleteHighlight(bookId, hl.id, $authStore.token);
                bookHighlights = bookHighlights.filter((h) => h.id !== hl.id);
                toastStore.success("Highlight removed");
              } catch (e) {
                toastStore.error((e as Error).message);
              }
            }}
          />
        </div>
      </div>
    {/if}

    <!-- Similar Books -->
    {#if similarBooks.length > 0}
      <div class="border-t border-border my-8"></div>
      <div>
        <h2 class="text-xl font-bold mb-3 text-foreground">Similar Books</h2>
        <div class="flex gap-4 overflow-x-auto pb-2 -mx-2 px-2 snap-x">
          {#each similarBooks as simBook}
            <a href="/books/{simBook.id}" class="flex-shrink-0 w-28 group">
              <div
                class="aspect-[2/3] rounded-lg overflow-hidden bg-secondary mb-2 book-shadow group-hover:book-shadow-hover transition-shadow"
              >
                {#if simBook.cover_path}
                  <img
                    src="/covers/{simBook.id}.jpg"
                    alt={simBook.display_title ?? ""}
                    class="w-full h-full object-cover"
                    loading="lazy"
                  />
                {:else}
                  <div
                    class="w-full h-full flex items-center justify-center text-muted-foreground text-xs p-2 text-center"
                  >
                    {simBook.display_title ?? "Untitled"}
                  </div>
                {/if}
              </div>
              <p
                class="text-xs text-foreground font-medium line-clamp-2 group-hover:text-primary transition-colors"
              >
                {simBook.display_title ?? "Untitled"}
              </p>
              {#if simBook.display_authors?.length}
                <p class="text-xs text-muted-foreground line-clamp-1">
                  {simBook.display_authors.join(", ")}
                </p>
              {/if}
            </a>
          {/each}
        </div>
      </div>
    {/if}
  {/if}
</div>

<!-- Edit Modal -->
{#if book}
  <Modal
    title="Edit Metadata"
    open={showEditModal}
    onclose={() => (showEditModal = false)}
  >
    <div class="space-y-4">
      <div class="space-y-1">
        <div class="flex items-center justify-between">
          <label
            class="block text-sm font-medium text-foreground"
            for="edit-title">Title</label
          >
          {#if editForm.title && book.epub_title}
            <button
              class="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              onclick={() => (editForm.title = "")}
            >
              <Undo2 size={12} />
              Reset
            </button>
          {/if}
        </div>
        <input
          id="edit-title"
          bind:value={editForm.title}
          placeholder={book.epub_title ?? ""}
          class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
        {#if editForm.title && book.epub_title && editForm.title !== book.epub_title}
          <p class="text-xs text-muted-foreground">
            Original: {book.epub_title}
          </p>
        {/if}
      </div>
      <div class="space-y-1">
        <div class="flex items-center justify-between">
          <label
            class="block text-sm font-medium text-foreground"
            for="edit-authors">Authors (comma-separated)</label
          >
          {#if editForm.authors && book.epub_authors?.length}
            <button
              class="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              onclick={() => (editForm.authors = "")}
            >
              <Undo2 size={12} />
              Reset
            </button>
          {/if}
        </div>
        <input
          id="edit-authors"
          bind:value={editForm.authors}
          placeholder={(book.epub_authors ?? []).join(", ")}
          class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
        {#if editForm.authors && book.epub_authors?.length && editForm.authors !== (book.epub_authors ?? []).join(", ")}
          <p class="text-xs text-muted-foreground">
            Original: {(book.epub_authors ?? []).join(", ")}
          </p>
        {/if}
      </div>
      <div class="space-y-1">
        <div class="flex items-center justify-between">
          <label
            class="block text-sm font-medium text-foreground"
            for="edit-publisher">Publisher</label
          >
          {#if editForm.publisher && book.epub_publisher}
            <button
              class="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              onclick={() => (editForm.publisher = "")}
            >
              <Undo2 size={12} />
              Reset
            </button>
          {/if}
        </div>
        <input
          id="edit-publisher"
          bind:value={editForm.publisher}
          placeholder={book.epub_publisher ?? ""}
          class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
        {#if editForm.publisher && book.epub_publisher && editForm.publisher !== book.epub_publisher}
          <p class="text-xs text-muted-foreground">
            Original: {book.epub_publisher}
          </p>
        {/if}
      </div>
      <div class="space-y-1">
        <div class="flex items-center justify-between">
          <label
            class="block text-sm font-medium text-foreground"
            for="edit-date">Published Date</label
          >
          {#if editForm.published_date && book.epub_published_date}
            <button
              class="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              onclick={() => (editForm.published_date = "")}
            >
              <Undo2 size={12} />
              Reset
            </button>
          {/if}
        </div>
        <input
          id="edit-date"
          bind:value={editForm.published_date}
          placeholder={book.epub_published_date ?? ""}
          class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
        {#if editForm.published_date && book.epub_published_date && editForm.published_date !== book.epub_published_date}
          <p class="text-xs text-muted-foreground">
            Original: {book.epub_published_date}
          </p>
        {/if}
      </div>
      <div class="space-y-1">
        <div class="flex items-center justify-between">
          <label
            class="block text-sm font-medium text-foreground"
            for="edit-series">Series</label
          >
          {#if editForm.series && book.epub_series}
            <button
              class="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              onclick={() => {
                editForm.series = "";
                editForm.series_index = "";
              }}
            >
              <Undo2 size={12} />
              Reset
            </button>
          {/if}
        </div>
        <div class="flex gap-2">
          <input
            id="edit-series"
            bind:value={editForm.series}
            placeholder={book.epub_series ?? ""}
            class="flex-1 border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          <input
            id="edit-series-index"
            bind:value={editForm.series_index}
            placeholder={book.epub_series_index != null
              ? String(book.epub_series_index)
              : "#"}
            type="number"
            step="0.1"
            class="w-20 border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
        </div>
        {#if editForm.series && book.epub_series && editForm.series !== book.epub_series}
          <p class="text-xs text-muted-foreground">
            Original: {book.epub_series}{#if book.epub_series_index != null}
              [{book.epub_series_index}]{/if}
          </p>
        {/if}
      </div>
      <div class="space-y-1">
        <div class="flex items-center justify-between">
          <label
            class="block text-sm font-medium text-foreground"
            for="edit-tags">Tags (comma-separated)</label
          >
          {#if editForm.tags && book.epub_tags?.length}
            <button
              class="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              onclick={() => (editForm.tags = "")}
            >
              <Undo2 size={12} />
              Reset
            </button>
          {/if}
        </div>
        <input
          id="edit-tags"
          bind:value={editForm.tags}
          placeholder={(book.epub_tags ?? []).join(", ")}
          class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
        {#if editForm.tags && book.epub_tags?.length && editForm.tags !== (book.epub_tags ?? []).join(", ")}
          <p class="text-xs text-muted-foreground">
            Original: {(book.epub_tags ?? []).join(", ")}
          </p>
        {/if}
      </div>
      <div class="space-y-1">
        <div class="flex items-center justify-between">
          <label
            class="block text-sm font-medium text-foreground"
            for="edit-desc">Description</label
          >
          {#if editForm.description && book.epub_description}
            <button
              class="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              onclick={() => (editForm.description = "")}
            >
              <Undo2 size={12} />
              Reset
            </button>
          {/if}
        </div>
        <textarea
          id="edit-desc"
          bind:value={editForm.description}
          placeholder={book.epub_description ?? ""}
          rows={4}
          class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none"
        ></textarea>
        {#if editForm.description && book.epub_description && editForm.description !== book.epub_description}
          <p class="text-xs text-muted-foreground">
            Original: {book.epub_description.slice(0, 100)}...
          </p>
        {/if}
      </div>
      <div class="flex justify-end gap-2 pt-2">
        <button
          class="px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
          onclick={() => (showEditModal = false)}>Cancel</button
        >
        <button
          class="px-5 py-2.5 text-sm bg-primary hover:bg-primary/90 text-primary-foreground font-semibold rounded-xl"
          onclick={handleSaveEdit}>Save</button
        >
      </div>
    </div>
  </Modal>

  <Modal
    title="Notes"
    open={showNotesModal}
    onclose={() => (showNotesModal = false)}
  >
    <div class="space-y-4">
      <div class="space-y-1">
        <label class="block text-sm text-muted-foreground" for="notes-text"
          >Markdown supported</label
        >
        <textarea
          id="notes-text"
          bind:value={notesText}
          rows={10}
          class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none font-mono text-sm"
          placeholder="Write your notes here..."
        ></textarea>
      </div>
      <div class="flex justify-end gap-2 pt-2">
        <button
          class="px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
          onclick={() => (showNotesModal = false)}>Cancel</button
        >
        <button
          class="px-5 py-2.5 text-sm bg-primary hover:bg-primary/90 text-primary-foreground font-semibold rounded-xl disabled:opacity-50"
          onclick={handleSaveNotes}
          disabled={savingNotes}
        >
          {savingNotes ? "Saving..." : "Save"}
        </button>
      </div>
    </div>
  </Modal>

  <Modal
    title="Add to Bookshelf"
    open={showAddToShelf}
    onclose={() => (showAddToShelf = false)}
  >
    <div class="space-y-2">
      {#if bookshelves.length === 0}
        <p class="text-muted-foreground text-sm">
          No bookshelves yet. <a href="/bookshelves" class="text-primary"
            >Create one</a
          >.
        </p>
      {:else}
        {#each bookshelves as shelf}
          <button
            class="w-full text-left px-4 py-3 rounded-xl bg-secondary/50 hover:bg-secondary hover:shadow-sm transition-all"
            onclick={() => addToShelf(shelf.id)}
          >
            <p class="font-medium text-foreground">{shelf.name}</p>
            {#if shelf.description}
              <p class="text-muted-foreground text-xs mt-0.5">
                {shelf.description}
              </p>
            {/if}
          </button>
        {/each}
      {/if}
    </div>
  </Modal>
{/if}
