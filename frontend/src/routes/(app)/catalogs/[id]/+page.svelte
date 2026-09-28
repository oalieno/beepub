<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { toastStore } from "$lib/stores/toast";
  import { authStore } from "$lib/stores/auth";
  import { activeLibrary } from "$lib/stores/activeLibrary";
  import { authedSrc } from "$lib/actions/authedSrc";
  import * as Select from "$lib/components/ui/select";
  import { librariesApi } from "$lib/api/libraries";
  import { UserRole, type LibraryOut } from "$lib/types";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import BackButton from "$lib/components/BackButton.svelte";
  import {
    BookOpen,
    Check,
    ChevronRight,
    Download,
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
  import {
    catalogSide,
    getCatalog,
    saveCatalog,
    type CatalogInfo,
  } from "$lib/opds/catalogs";
  import {
    fetchServerFeed,
    fetchServerSearchTemplate,
    importableDownload,
    serverImageUrl,
  } from "$lib/opds/server";

  const catalogId = page.params.id ?? "";
  // Device catalogs download onto the device; server catalogs import into
  // a server library, fetched through the server.
  const side = catalogSide();
  const isAdmin = $derived($authStore.user?.role === UserRole.Admin);
  const canImport = $derived(
    side === "device" || isAdmin || !!$authStore.user?.can_upload,
  );

  let catalog = $state<CatalogInfo | null>(null);
  let notFound = $state(false);
  let feedTitle = $state("");
  let entries = $state<OpdsEntry[]>([]);
  let nextUrl = $state<string | null>(null);
  let searchDescUrl = $state<string | null>(null);
  let loading = $state(true);
  let loadingMore = $state(false);
  let error = $state<"auth" | "blocked" | "generic" | null>(null);
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

  function loadFeedFrom(target: string): Promise<OpdsFeed> {
    return side === "device"
      ? fetchFeed(target, creds())
      : fetchServerFeed(catalogId, target);
  }

  // Credentialed device catalogs load covers through the transport (plain
  // <img> can't send Basic auth); public ones use the URL directly.
  // Server catalogs always go through the server.
  const credentialed = $derived(side === "device" && !!catalog?.hasCredentials);

  function coverOf(entry: OpdsBookEntry): string | undefined {
    // Server: the full cover, which the server cuts to card size —
    // thumbnails are often ~100px wide (Gutenberg), too small for a card.
    if (side === "server") {
      const url = entry.coverUrl ?? entry.thumbnailUrl;
      return url && serverImageUrl(catalogId, url);
    }
    // Device: thumbnail first, fetched over the phone's own connection.
    const url = entry.thumbnailUrl ?? entry.coverUrl;
    return credentialed ? coverSrcs[entry.key] : url;
  }

  /** The name of the file a tap would fetch, as the feed calls it. */
  function variantOf(entry: OpdsBookEntry): string | undefined {
    if (side === "server") return importableDownload(entry)?.title;
    return entry.downloads.find((d) => d.href === entry.epubUrl)?.title;
  }

  function downloadable(entry: OpdsBookEntry): boolean {
    return side === "device" ? !!entry.epubUrl : !!importableDownload(entry);
  }

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
    // Only whoever manages the list can fix its URL.
    const canPersist = side === "device" || isAdmin;
    let probeUrl: string;
    try {
      const url = new URL(target);
      if (url.pathname !== "/" && url.pathname !== "") return null;
      probeUrl = `${url.origin}/opds`;
    } catch {
      return null;
    }
    try {
      const feed = await loadFeedFrom(probeUrl);
      if (!canPersist) return feed;
      const updated = await saveCatalog(side, cat.id, {
        name: cat.name,
        url: probeUrl,
        username: cat.username ?? undefined,
        // Device: the stored one. Server: omitted keeps it.
        password: cat.password ?? undefined,
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
        feed = await loadFeedFrom(target);
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
        err instanceof OpdsError &&
        (err.kind === "auth" || err.kind === "blocked")
          ? err.kind
          : "generic";
    } finally {
      if (token === loadToken) loading = false;
    }
  }

  async function loadMore() {
    if (!nextUrl || loadingMore) return;
    loadingMore = true;
    try {
      const feed = await loadFeedFrom(nextUrl);
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
    /** Server: the book it became (or already was), to open from the check. */
    bookId?: string;
  };
  let downloadStates = $state<Record<string, DownloadState>>({});
  const downloadQueue: OpdsBookEntry[] = [];
  let downloadActive = false;

  function setDownloadState(key: string, state: DownloadState) {
    downloadStates = { ...downloadStates, [key]: state };
  }

  function requestDownload(entry: OpdsBookEntry) {
    if (!downloadable(entry)) return;
    if (side === "server" && !importLibrary) return;
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

  async function runImport(entry: OpdsBookEntry, libraryId: string) {
    setDownloadState(entry.key, { status: "downloading", pct: null });
    const { importToServer } = await import("$lib/opds/server");
    try {
      const { status, book } = await importToServer(
        catalogId,
        entry,
        libraryId,
      );
      setDownloadState(entry.key, { status, pct: null, bookId: book.id });
      if (status === "imported")
        toastStore.success(m.catalogs_import_done({ title: entry.title }));
      else toastStore.info(m.catalogs_import_duplicate({ title: entry.title }));
    } catch (err) {
      setDownloadState(entry.key, { status: "error", pct: null });
      toastStore.error(
        err instanceof OpdsError && err.kind === "blocked"
          ? m.catalogs_blocked_error()
          : m.catalogs_import_error({ title: entry.title }),
      );
    }
  }

  async function runDownload(entry: OpdsBookEntry) {
    if (side === "server") {
      if (importLibrary) await runImport(entry, importLibrary);
      return;
    }
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
      searchTemplate =
        side === "device"
          ? await fetchSearchTemplate(searchDescUrl, creds())
          : await fetchServerSearchTemplate(catalogId, searchDescUrl);
      searchBusy = false;
      if (!searchTemplate) {
        toastStore.error(m.catalogs_feed_error());
        return;
      }
    }
    goto(feedHref(buildSearchUrl(searchTemplate, terms)));
  }

  // --- Import target (server) ---
  //
  // Where imports land: the libraries that take uploads (Calibre ones are
  // read-only). Starts at the active library when it can, else the last
  // pick, else the first.
  const IMPORT_LIBRARY_KEY = "opds-import-library";
  let importLibraries = $state<LibraryOut[]>([]);
  let importLibrary = $state<string | null>(null);

  async function loadImportLibraries() {
    if (side !== "server" || !canImport) return;
    try {
      importLibraries = (await librariesApi.list()).filter(
        (l) => !l.calibre_path,
      );
    } catch {
      importLibraries = [];
    }
    let remembered: string | null = null;
    try {
      remembered = localStorage.getItem(IMPORT_LIBRARY_KEY);
    } catch {
      // storage unavailable
    }
    const ids = importLibraries.map((l) => l.id);
    importLibrary =
      [$activeLibrary, remembered].find((id) => id && ids.includes(id)) ??
      ids[0] ??
      null;
  }

  function pickImportLibrary(id: string) {
    importLibrary = id;
    try {
      localStorage.setItem(IMPORT_LIBRARY_KEY, id);
    } catch {
      // storage unavailable
    }
  }

  onMount(async () => {
    let found: CatalogInfo | null = null;
    try {
      found = await getCatalog(side, catalogId);
    } catch {
      error = "generic";
      loading = false;
      return;
    }
    if (!found) {
      notFound = true;
      loading = false;
      return;
    }
    if (side === "device" && found.username) {
      const { OpdsCoverLoader } = await import("$lib/opds/covers");
      coverLoader = new OpdsCoverLoader({
        username: found.username,
        password: found.password ?? "",
      });
    }
    catalog = found;
    void loadImportLibraries();
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

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
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
        {#if side === "device" || isAdmin}
          <Button
            variant="outline"
            class="rounded-xl"
            onclick={() => goto("/catalogs")}
          >
            {m.catalogs_edit()}
          </Button>
        {/if}
      {:else if error === "blocked"}
        <Lock class="mx-auto mb-4 text-muted-foreground/30" size={48} />
        <p class="text-muted-foreground text-lg">
          {m.catalogs_blocked_error()}
        </p>
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

    {#if side === "server" && canImport}
      <div class="flex items-center gap-2 mb-6 text-sm text-muted-foreground">
        {#if importLibraries.length > 0}
          <span>{m.catalogs_import_target()}</span>
          <Select.Root
            type="single"
            value={importLibrary ?? undefined}
            onValueChange={(v) => v && pickImportLibrary(v)}
          >
            <Select.Trigger
              class="w-[200px]"
              aria-label={m.catalogs_import_target()}
            >
              {importLibraries.find((l) => l.id === importLibrary)?.name ?? ""}
            </Select.Trigger>
            <Select.Content>
              {#each importLibraries as library (library.id)}
                <Select.Item value={library.id}>{library.name}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        {:else}
          <span>{m.catalogs_no_upload_library()}</span>
        {/if}
      </div>
    {/if}

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
                class="w-full bg-card card-soft rounded-2xl px-5 py-4 flex items-center gap-3 group"
                style="-webkit-tap-highlight-color: transparent;"
              >
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
            {@const coverSrc = coverOf(entry)}
            {@const dl = downloadStates[entry.key]}
            <div class="group">
              <!-- Cover -->
              <div class="h-56 sm:h-64 mb-3 flex items-end justify-center">
                <div class="relative inline-flex">
                  {#if coverSrc && side === "server"}
                    <img
                      use:authedSrc={coverSrc}
                      alt={entry.title}
                      class="max-h-56 sm:max-h-64 w-auto max-w-full rounded-sm book-shadow"
                      loading="lazy"
                    />
                  {:else if coverSrc}
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
                  {#if (dl?.status === "imported" || dl?.status === "duplicate") && dl.bookId}
                    <a
                      href={`/books/${dl.bookId}`}
                      class="absolute bottom-1.5 right-1.5 bg-primary text-primary-foreground p-1.5 rounded-full"
                      title={dl.status === "imported"
                        ? m.catalogs_server_imported()
                        : m.catalogs_server_duplicate()}
                    >
                      <Check size={14} />
                    </a>
                  {:else if dl?.status === "imported" || dl?.status === "duplicate"}
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
                      title={side === "device"
                        ? m.catalogs_downloading()
                        : m.catalogs_importing()}
                    >
                      <Loader2 class="animate-spin" size={12} />
                      {#if dl.status === "downloading" && dl.pct !== null}
                        {dl.pct}%
                      {/if}
                    </span>
                  {:else if !canImport || (side === "server" && !importLibrary)}
                    <!-- Browsing only: no upload permission, or nowhere to import. -->
                  {:else if !downloadable(entry)}
                    <span
                      class="absolute bottom-1.5 right-1.5 bg-black/40 text-white/50 p-1.5 rounded-full"
                      title={side === "device"
                        ? m.catalogs_no_epub()
                        : m.catalogs_import_unsupported()}
                    >
                      <Download size={14} />
                    </span>
                  {:else}
                    <button
                      class="absolute bottom-1.5 right-1.5 p-1.5 rounded-full bg-black/60 text-white/90 hover:bg-primary hover:text-primary-foreground transition-all duration-200"
                      style="-webkit-tap-highlight-color: transparent; touch-action: manipulation;"
                      title={side === "device"
                        ? m.catalogs_download()
                        : m.catalogs_import()}
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
                {#if variantOf(entry)}
                  <!-- Catalogs list one book per variant (Gutenberg: with
                       and without images); the link's name tells them apart. -->
                  <p
                    class="text-muted-foreground/80 text-xs mt-0.5 line-clamp-2"
                  >
                    {variantOf(entry)}
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
