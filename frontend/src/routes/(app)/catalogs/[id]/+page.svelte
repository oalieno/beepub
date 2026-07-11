<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { isNative } from "$lib/platform";
  import { isLocalMode } from "$lib/api/client";
  import { toastStore } from "$lib/stores/toast";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import BackButton from "$lib/components/BackButton.svelte";
  import {
    BookOpen,
    Check,
    ChevronRight,
    Download,
    FolderOpen,
    Loader2,
    Lock,
    RefreshCw,
    Rss,
    Search,
  } from "@lucide/svelte";
  import { BookGridSkeleton } from "$lib/components/skeletons";
  import * as m from "$lib/paraglide/messages.js";
  import {
    fetchFeed,
    fetchSearchTemplate,
    OpdsError,
    type OpdsCredentials,
  } from "$lib/opds/client";
  import {
    buildSearchUrl,
    type OpdsBookEntry,
    type OpdsEntry,
    type OpdsFeed,
  } from "$lib/opds/parse";
  import type { OpdsCoverLoader } from "$lib/opds/covers";
  import type { OpdsCatalog } from "$lib/services/opdsCatalogs";

  // In serverless local mode the (app) layout renders no chrome (there is
  // no authenticated user), so this page provides its own header.
  const localMode = isLocalMode();
  const catalogId = page.params.id ?? "";

  let catalog = $state<OpdsCatalog | null>(null);
  let notFound = $state(false);
  let feedTitle = $state("");
  let entries = $state<OpdsEntry[]>([]);
  let nextUrl = $state<string | null>(null);
  let searchDescUrl = $state<string | null>(null);
  let loading = $state(true);
  let loadingMore = $state(false);
  let error = $state<"auth" | "generic" | null>(null);
  let searchTerms = $state("");
  let searchBusy = $state(false);
  // entry.key → data URI, filled lazily for credentialed catalogs.
  let coverSrcs = $state<Record<string, string>>({});

  // Cached per page session; plain vars — nothing renders from them.
  let searchTemplate: string | null = null;
  let coverLoader: OpdsCoverLoader | null = null;
  let loadToken = 0;

  function creds(): OpdsCredentials | undefined {
    if (!catalog?.username) return undefined;
    return { username: catalog.username, password: catalog.password ?? "" };
  }

  // Credentialed catalogs load covers through the transport (plain <img>
  // can't send Basic auth); public ones use the URL directly.
  const credentialed = $derived(!!catalog?.username);

  const navEntries = $derived(entries.filter((e) => e.kind === "nav"));
  const bookEntries = $derived(
    entries.filter((e) => e.kind === "book") as OpdsBookEntry[],
  );

  function feedHref(url: string): string {
    return `/catalogs/${catalogId}?feed=${encodeURIComponent(url)}`;
  }

  function loadCovers(list: OpdsEntry[]) {
    const loader = coverLoader;
    if (!loader) return;
    for (const entry of list) {
      if (entry.kind !== "book") continue;
      const url = entry.thumbnailUrl ?? entry.coverUrl;
      if (!url || coverSrcs[entry.key]) continue;
      void loader.load(url).then((uri) => {
        if (uri) coverSrcs = { ...coverSrcs, [entry.key]: uri };
      });
    }
  }

  // A bare server origin — the mental model from connecting the app to a
  // BeePub server — serves the web app's HTML, not a feed. Both BeePub and
  // calibre-web keep their catalog at /opds, so on a parse failure at the
  // catalog root with no path, probe /opds once and persist the fix.
  async function probeOpdsPath(
    err: unknown,
    target: string,
  ): Promise<OpdsFeed | null> {
    if (page.url.searchParams.get("feed")) return null; // catalog roots only
    if (!(err instanceof OpdsError) || err.kind !== "parse") return null;
    const cat = catalog;
    if (!cat) return null;
    let probeUrl: string;
    try {
      const url = new URL(target);
      if (url.pathname !== "/" && url.pathname !== "") return null;
      probeUrl = `${url.origin}/opds`;
    } catch {
      return null;
    }
    try {
      const feed = await fetchFeed(probeUrl, creds());
      const { updateCatalog } = await import("$lib/services/opdsCatalogs");
      const updated = await updateCatalog(cat.id, {
        name: cat.name,
        url: probeUrl,
        username: cat.username,
        password: cat.password,
      });
      // Triggers one redundant refetch via the $effect — once, on the
      // visit that heals the URL.
      if (updated) catalog = updated;
      return feed;
    } catch {
      return null;
    }
  }

  async function loadFeed(target: string) {
    const token = ++loadToken;
    loading = true;
    error = null;
    try {
      let feed: OpdsFeed;
      try {
        feed = await fetchFeed(target, creds());
      } catch (err) {
        const probed = await probeOpdsPath(err, target);
        if (!probed) throw err;
        feed = probed;
      }
      if (token !== loadToken) return; // superseded by a newer navigation
      feedTitle = feed.title;
      entries = feed.entries;
      nextUrl = feed.nextUrl ?? null;
      searchDescUrl = feed.searchDescUrl ?? null;
      loadCovers(feed.entries);
    } catch (err) {
      if (token !== loadToken) return;
      error =
        err instanceof OpdsError && err.kind === "auth" ? "auth" : "generic";
    } finally {
      if (token === loadToken) loading = false;
    }
  }

  async function loadMore() {
    if (!nextUrl || loadingMore) return;
    loadingMore = true;
    try {
      const feed = await fetchFeed(nextUrl, creds());
      entries = [...entries, ...feed.entries];
      nextUrl = feed.nextUrl ?? null;
      loadCovers(feed.entries);
    } catch {
      toastStore.error(m.catalogs_feed_error());
    } finally {
      loadingMore = false;
    }
  }

  // --- Download queue ---
  //
  // Sequential, one book at a time (the readingSync "don't stampede
  // NAS-class servers" posture); further taps enqueue. States persist for
  // the page session so navigating feeds keeps imported/duplicate badges.
  type DownloadState = {
    status: "queued" | "downloading" | "imported" | "duplicate" | "error";
    pct: number | null;
  };
  let downloadStates = $state<Record<string, DownloadState>>({});
  const downloadQueue: OpdsBookEntry[] = [];
  let downloadActive = false;

  function setDownloadState(key: string, state: DownloadState) {
    downloadStates = { ...downloadStates, [key]: state };
  }

  function requestDownload(entry: OpdsBookEntry) {
    if (!entry.epubUrl) return;
    const current = downloadStates[entry.key]?.status;
    // error is re-tappable; everything else is settled or in flight.
    if (current && current !== "error") return;
    setDownloadState(entry.key, { status: "queued", pct: null });
    downloadQueue.push(entry);
    void pumpQueue();
  }

  async function pumpQueue() {
    if (downloadActive) return;
    downloadActive = true;
    try {
      let entry: OpdsBookEntry | undefined;
      while ((entry = downloadQueue.shift())) {
        await runDownload(entry);
      }
    } finally {
      downloadActive = false;
    }
  }

  async function runDownload(entry: OpdsBookEntry) {
    const cat = catalog;
    if (!cat) return;
    setDownloadState(entry.key, { status: "downloading", pct: null });
    const { downloadAndImport } = await import("$lib/opds/download");
    const { DuplicateBookError, InvalidEpubError } =
      await import("$lib/services/localLibrary");
    try {
      const imported = await downloadAndImport(entry, cat, (pct) => {
        setDownloadState(entry.key, { status: "downloading", pct });
      });
      setDownloadState(entry.key, { status: "imported", pct: null });
      toastStore.success(m.local_import_success({ title: imported.title }));
      // Mirror the /local import hook: if the same file exists on the
      // connected BeePub server, link it and start syncing right away.
      void import("$lib/services/readingSync").then(({ linkAndSyncBook }) =>
        linkAndSyncBook(imported).then((linked) => {
          if (linked) toastStore.info(m.local_linked());
        }),
      );
    } catch (err) {
      if (err instanceof DuplicateBookError) {
        setDownloadState(entry.key, { status: "duplicate", pct: null });
        toastStore.info(
          m.local_import_duplicate({ title: err.existing.title }),
        );
      } else if (err instanceof InvalidEpubError) {
        setDownloadState(entry.key, { status: "error", pct: null });
        toastStore.error(m.local_import_invalid());
      } else {
        setDownloadState(entry.key, { status: "error", pct: null });
        toastStore.error(m.catalogs_download_error({ title: entry.title }));
      }
    }
  }

  async function handleSearch(e: Event) {
    e.preventDefault();
    const terms = searchTerms.trim();
    if (!terms || searchBusy) return;
    if (!searchTemplate) {
      if (!searchDescUrl) return;
      searchBusy = true;
      searchTemplate = await fetchSearchTemplate(searchDescUrl, creds());
      searchBusy = false;
      if (!searchTemplate) {
        toastStore.error(m.catalogs_feed_error());
        return;
      }
    }
    goto(feedHref(buildSearchUrl(searchTemplate, terms)));
  }

  onMount(async () => {
    if (!isNative()) {
      loading = false;
      return;
    }
    const { getCatalog } = await import("$lib/services/opdsCatalogs");
    const found = await getCatalog(catalogId);
    if (!found) {
      notFound = true;
      loading = false;
      return;
    }
    if (found.username) {
      const { OpdsCoverLoader } = await import("$lib/opds/covers");
      coverLoader = new OpdsCoverLoader({
        username: found.username,
        password: found.password ?? "",
      });
    }
    catalog = found;
  });

  // Reload on every feed navigation (the component is reused across
  // same-route gotos). Reads are synchronous so both the query param and
  // the catalog are tracked.
  $effect(() => {
    const target = page.url.searchParams.get("feed") ?? catalog?.url;
    if (!catalog || !target) return;
    void loadFeed(target);
  });
</script>

<svelte:head>
  <title>{catalog ? catalog.name : m.catalogs_page_title()}</title>
</svelte:head>

<div
  class="px-6 sm:px-8 py-6"
  style={localMode
    ? "padding-top: calc(env(safe-area-inset-top, 0px) + 1.5rem);"
    : ""}
>
  <div class="mb-4">
    {#if page.url.searchParams.get("feed")}
      <!-- Deeper in the catalog: back walks the feed history. -->
      <BackButton
        href={`/catalogs/${catalogId}`}
        label={catalog?.name ?? m.nav_catalogs()}
        onclick={() => history.back()}
      />
    {:else}
      <BackButton href="/catalogs" label={m.nav_catalogs()} />
    {/if}
  </div>

  {#if loading}
    <BookGridSkeleton count={6} />
  {:else if !isNative()}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      <Rss class="mx-auto mb-4 text-muted-foreground/30" size={48} />
      <p class="text-muted-foreground text-lg">
        {m.catalogs_native_only()}
      </p>
    </div>
  {:else if notFound}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      <Rss class="mx-auto mb-4 text-muted-foreground/30" size={48} />
      <p class="text-muted-foreground text-lg">{m.catalogs_feed_error()}</p>
    </div>
  {:else if error}
    <div class="bg-card card-soft rounded-2xl p-12 text-center">
      {#if error === "auth"}
        <Lock class="mx-auto mb-4 text-muted-foreground/30" size={48} />
        <p class="text-muted-foreground text-lg mb-6">
          {m.catalogs_auth_error()}
        </p>
        <Button
          variant="outline"
          class="rounded-xl"
          onclick={() => goto("/catalogs")}
        >
          {m.catalogs_edit()}
        </Button>
      {:else}
        <Rss class="mx-auto mb-4 text-muted-foreground/30" size={48} />
        <p class="text-muted-foreground text-lg mb-6">
          {m.catalogs_feed_error()}
        </p>
        <Button
          variant="outline"
          class="rounded-xl"
          onclick={() => {
            const target = page.url.searchParams.get("feed") ?? catalog?.url;
            if (target) void loadFeed(target);
          }}
        >
          {m.common_retry()}
        </Button>
      {/if}
    </div>
  {:else}
    <div class="flex items-center justify-between gap-3 mb-6 flex-wrap">
      <h1
        class="text-xl font-bold min-w-0 truncate"
        style="font-family: var(--font-heading)"
      >
        {feedTitle || catalog?.name}
      </h1>
      {#if searchDescUrl}
        <form onsubmit={handleSearch} class="relative w-full sm:w-64">
          <Search
            size={15}
            class="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
          />
          {#if searchBusy}
            <Loader2
              size={15}
              class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground animate-spin"
            />
          {/if}
          <Input
            bind:value={searchTerms}
            placeholder={m.catalogs_search_placeholder()}
            class="pl-9"
            type="search"
            autocapitalize="none"
            autocorrect="off"
            spellcheck={false}
          />
        </form>
      {/if}
    </div>

    {#if entries.length === 0}
      <div class="flex flex-col items-center justify-center py-24 text-center">
        <div class="mb-4 p-3 bg-primary/10 rounded-xl">
          <Rss class="text-primary/50" size={28} />
        </div>
        <p class="text-muted-foreground text-sm max-w-xs">
          {m.catalogs_feed_empty()}
        </p>
      </div>
    {:else}
      {#if navEntries.length > 0}
        <div class="space-y-2 mb-8">
          {#each navEntries as entry (entry.key)}
            {#if entry.kind === "nav"}
              <a
                href={feedHref(entry.href)}
                class="w-full bg-card card-soft rounded-2xl p-4 flex items-center gap-3 group"
                style="-webkit-tap-highlight-color: transparent;"
              >
                <div class="p-2.5 bg-primary/10 rounded-xl shrink-0">
                  <FolderOpen class="text-primary" size={18} />
                </div>
                <div class="flex-1 min-w-0">
                  <h3
                    class="font-medium text-sm truncate text-foreground group-hover:text-primary transition-colors"
                  >
                    {entry.title}
                  </h3>
                  {#if entry.content}
                    <p
                      class="text-muted-foreground text-xs line-clamp-1 mt-0.5"
                    >
                      {entry.content}
                    </p>
                  {/if}
                </div>
                <ChevronRight
                  size={16}
                  class="text-muted-foreground shrink-0"
                />
              </a>
            {/if}
          {/each}
        </div>
      {/if}

      {#if bookEntries.length > 0}
        <div
          class="grid gap-4"
          style="grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));"
        >
          {#each bookEntries as entry (entry.key)}
            {@const coverSrc = credentialed
              ? coverSrcs[entry.key]
              : (entry.thumbnailUrl ?? entry.coverUrl)}
            {@const dl = downloadStates[entry.key]}
            <div class="group">
              <!-- Cover -->
              <div class="h-56 sm:h-64 mb-3 flex items-end justify-center">
                <div class="relative inline-flex">
                  {#if coverSrc}
                    <img
                      src={coverSrc}
                      alt={entry.title}
                      class="max-h-56 sm:max-h-64 w-auto max-w-full rounded-sm book-shadow"
                      loading="lazy"
                    />
                  {:else}
                    <div
                      class="h-56 sm:h-64 aspect-[2/3] bg-secondary rounded-sm flex flex-col items-center justify-center gap-2 p-4 book-shadow"
                    >
                      <BookOpen class="text-muted-foreground/30" size={36} />
                      <span
                        class="text-muted-foreground/60 text-xs text-center line-clamp-3"
                        >{entry.title}</span
                      >
                    </div>
                  {/if}

                  <!-- Download overlay -->
                  {#if dl?.status === "imported" || dl?.status === "duplicate"}
                    <span
                      class="absolute bottom-1.5 right-1.5 bg-primary text-primary-foreground p-1.5 rounded-full"
                      title={dl.status === "imported"
                        ? m.catalogs_imported()
                        : m.catalogs_duplicate()}
                    >
                      <Check size={14} />
                    </span>
                  {:else if dl?.status === "downloading" || dl?.status === "queued"}
                    <span
                      class="absolute bottom-1.5 right-1.5 flex items-center gap-1 bg-black/60 text-white/90 px-1.5 py-1 rounded-full text-[10px] font-medium"
                      title={m.catalogs_downloading()}
                    >
                      <Loader2 class="animate-spin" size={12} />
                      {#if dl.status === "downloading" && dl.pct !== null}
                        {dl.pct}%
                      {/if}
                    </span>
                  {:else if !entry.epubUrl}
                    <span
                      class="absolute bottom-1.5 right-1.5 bg-black/40 text-white/50 p-1.5 rounded-full"
                      title={m.catalogs_no_epub()}
                    >
                      <Download size={14} />
                    </span>
                  {:else}
                    <button
                      class="absolute bottom-1.5 right-1.5 p-1.5 rounded-full bg-black/60 text-white/90 hover:bg-primary hover:text-primary-foreground transition-all duration-200"
                      style="-webkit-tap-highlight-color: transparent; touch-action: manipulation;"
                      title={m.catalogs_download()}
                      onclick={() => requestDownload(entry)}
                    >
                      {#if dl?.status === "error"}
                        <RefreshCw size={14} />
                      {:else}
                        <Download size={14} />
                      {/if}
                    </button>
                  {/if}
                </div>
              </div>

              <!-- Info below cover -->
              <div class="min-h-[3rem]">
                <h3
                  class="font-medium text-sm line-clamp-2 leading-snug text-foreground"
                >
                  {entry.title}
                </h3>
                {#if entry.authors.length}
                  <p class="text-muted-foreground text-xs mt-0.5 line-clamp-1">
                    {entry.authors.join(", ")}
                  </p>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      {/if}

      {#if nextUrl}
        <div class="mt-8 pb-8 text-center">
          <Button
            variant="outline"
            class="rounded-xl"
            disabled={loadingMore}
            onclick={loadMore}
          >
            {#if loadingMore}
              <Loader2 class="animate-spin" size={16} />
            {/if}
            {m.catalogs_load_more()}
          </Button>
        </div>
      {/if}
    {/if}
  {/if}
</div>
