<script lang="ts">
  import { tick } from "svelte";
  import { page } from "$app/state";
  import { replaceState, afterNavigate } from "$app/navigation";
  import { booksApi } from "$lib/api/books";
  import BookBrowser from "$lib/components/BookBrowser.svelte";
  import type { BookBrowserState } from "$lib/components/BookBrowser.svelte";
  import { Library } from "@lucide/svelte";
  import type { Snapshot } from "./$types";

  let bookBrowser = $state<BookBrowser>();
  let restoreData = $state<BookBrowserState | null>(null);
  let pendingScrollY = $state(0);
  let restoredFromSnapshot = $state(false);
  let mounted = $state(false);

  interface PageSnapshot {
    browserState: BookBrowserState;
    scrollY: number;
  }

  export const snapshot: Snapshot<PageSnapshot> = {
    capture: () => ({
      browserState: bookBrowser?.getState() ?? {
        books: [],
        totalBooks: 0,
        searchQuery: "",
        filterAuthor: "",
        filterTag: "",
        filterSeries: "",
        sortValue: "added_at:desc",
      },
      scrollY: window.scrollY,
    }),
    restore: (data) => {
      restoreData = data.browserState;
      pendingScrollY = data.scrollY;
      restoredFromSnapshot = true;
    },
  };

  afterNavigate(async () => {
    if (restoredFromSnapshot) {
      restoredFromSnapshot = false;
      mounted = true;
      await tick();
      await tick();
      window.scrollTo(0, pendingScrollY);
      restoreData = null;
      return;
    }
    restoreData = null;
    mounted = true;
  });

  function fetchBooks(params: {
    search?: string;
    author?: string;
    tag?: string;
    series?: string;
    sort?: string;
    order?: string;
    limit?: number;
    offset?: number;
  }) {
    return booksApi.getAll(params);
  }

  function handleStateChange(state: BookBrowserState) {
    const url = new URL(page.url);
    if (state.searchQuery) url.searchParams.set("search", state.searchQuery);
    else url.searchParams.delete("search");
    if (state.filterAuthor) url.searchParams.set("author", state.filterAuthor);
    else url.searchParams.delete("author");
    if (state.filterTag) url.searchParams.set("tag", state.filterTag);
    else url.searchParams.delete("tag");
    if (state.filterSeries) url.searchParams.set("series", state.filterSeries);
    else url.searchParams.delete("series");
    if (state.sortValue !== "added_at:desc")
      url.searchParams.set("sort", state.sortValue);
    else url.searchParams.delete("sort");
    replaceState(url, {});
  }
</script>

<svelte:head>
  <title>All Books - BeePub</title>
</svelte:head>

<div class="px-6 sm:px-8 py-6">
  <div class="mb-8">
    <div class="flex items-center gap-2">
      <Library size={24} class="text-primary" />
      <h1 class="text-3xl font-bold text-foreground">All Books</h1>
    </div>
    <p class="text-muted-foreground mt-1">
      Browse all books across your libraries.
    </p>
  </div>

  {#if mounted}
    <BookBrowser
      bind:this={bookBrowser}
      {fetchBooks}
      {restoreData}
      initialSearch={(page.url.searchParams.get("search") ?? "").trim()}
      initialTag={(page.url.searchParams.get("tag") ?? "").trim()}
      initialAuthor={(page.url.searchParams.get("author") ?? "").trim()}
      initialSeries={(page.url.searchParams.get("series") ?? "").trim()}
      initialSort={page.url.searchParams.get("sort") || "added_at:desc"}
      onStateChange={handleStateChange}
    />
  {/if}
</div>
