<script lang="ts">
  import Modal from "$lib/components/Modal.svelte";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import { Undo2 } from "@lucide/svelte";
  import type { BookOut } from "$lib/types";

  let {
    book,
    open = $bindable(false),
    onupdate,
  }: {
    book: BookOut;
    open: boolean;
    onupdate: (updated: BookOut) => void;
  } = $props();

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

  $effect(() => {
    if (open && book) {
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
  });

  async function handleSave() {
    try {
      const parsedTags = editForm.tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const parsedAuthors = editForm.authors
        .split(",")
        .map((a) => a.trim())
        .filter(Boolean);
      const updated = await booksApi.updateMetadata(book.id, {
        title: editForm.title || null,
        authors: parsedAuthors.length > 0 ? parsedAuthors : null,
        description: editForm.description || null,
        publisher: editForm.publisher || null,
        published_date: editForm.published_date || null,
        series: editForm.series || null,
        series_index: editForm.series_index
          ? parseFloat(editForm.series_index)
          : null,
        tags: parsedTags.length > 0 ? parsedTags : null,
      });
      open = false;
      onupdate(updated);
      toastStore.success("Metadata updated");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  const inputClass =
    "w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-primary/30";
</script>

<Modal title="Edit Metadata" {open} onclose={() => (open = false)}>
  <div class="space-y-4">
    <!-- Title -->
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
        class={inputClass}
      />
      {#if editForm.title && book.epub_title && editForm.title !== book.epub_title}
        <p class="text-xs text-muted-foreground">
          Original: {book.epub_title}
        </p>
      {/if}
    </div>

    <!-- Authors -->
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
        class={inputClass}
      />
      {#if editForm.authors && book.epub_authors?.length && editForm.authors !== (book.epub_authors ?? []).join(", ")}
        <p class="text-xs text-muted-foreground">
          Original: {(book.epub_authors ?? []).join(", ")}
        </p>
      {/if}
    </div>

    <!-- Publisher -->
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
        class={inputClass}
      />
      {#if editForm.publisher && book.epub_publisher && editForm.publisher !== book.epub_publisher}
        <p class="text-xs text-muted-foreground">
          Original: {book.epub_publisher}
        </p>
      {/if}
    </div>

    <!-- Published Date -->
    <div class="space-y-1">
      <div class="flex items-center justify-between">
        <label class="block text-sm font-medium text-foreground" for="edit-date"
          >Published Date</label
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
        class={inputClass}
      />
      {#if editForm.published_date && book.epub_published_date && editForm.published_date !== book.epub_published_date}
        <p class="text-xs text-muted-foreground">
          Original: {book.epub_published_date}
        </p>
      {/if}
    </div>

    <!-- Series -->
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

    <!-- Tags -->
    <div class="space-y-1">
      <div class="flex items-center justify-between">
        <label class="block text-sm font-medium text-foreground" for="edit-tags"
          >Tags (comma-separated)</label
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
        class={inputClass}
      />
      {#if editForm.tags && book.epub_tags?.length && editForm.tags !== (book.epub_tags ?? []).join(", ")}
        <p class="text-xs text-muted-foreground">
          Original: {(book.epub_tags ?? []).join(", ")}
        </p>
      {/if}
    </div>

    <!-- Description -->
    <div class="space-y-1">
      <div class="flex items-center justify-between">
        <label class="block text-sm font-medium text-foreground" for="edit-desc"
          >Description</label
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
        class="{inputClass} resize-none"
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
        onclick={() => (open = false)}>Cancel</button
      >
      <button
        class="px-5 py-2.5 text-sm bg-primary hover:bg-primary/90 text-primary-foreground font-semibold rounded-xl"
        onclick={handleSave}>Save</button
      >
    </div>
  </div>
</Modal>
