<script lang="ts">
  import { booksApi } from "$lib/api/books";
  import * as m from "$lib/paraglide/messages.js";
  import { toastStore } from "$lib/stores/toast";
  import { Pencil, Plus, Unlink, Ban } from "@lucide/svelte";
  import * as Popover from "$lib/components/ui/popover";
  import type { ExternalMetadataOut } from "$lib/types";

  let {
    bookId,
    externalMeta = $bindable(),
    isAdmin,
  }: {
    bookId: string;
    externalMeta: ExternalMetadataOut[];
    isAdmin: boolean;
  } = $props();

  const SOURCE_META: Record<
    string,
    {
      label: string;
      urlPrefix: string;
      idPattern: RegExp;
      idHint: string;
    }
  > = $derived({
    goodreads: {
      label: m.external_goodreads(),
      urlPrefix: "https://www.goodreads.com/book/show/",
      idPattern: /^\d+[\w-]*$/,
      idHint: "e.g. 33017208",
    },
    readmoo: {
      label: m.external_readmoo(),
      urlPrefix: "https://readmoo.com/book/",
      idPattern: /^\d+$/,
      idHint: "e.g. 210227953000101",
    },
    google_books: {
      label: m.external_google_books(),
      urlPrefix: "https://books.google.com/books?id=",
      idPattern: /^[\w-]+$/,
      idHint: "e.g. qixiEAAAQBAJ",
    },
    hardcover: {
      label: m.external_hardcover(),
      urlPrefix: "https://hardcover.app/books/",
      idPattern: /^[\w-]+$/,
      idHint: "e.g. the-left-hand-of-darkness",
    },
  });

  let editingUrlSource = $state<string | null>(null);
  let editingUrlValue = $state("");
  let validationError = $state("");
  let sourcesOpen = $state(false);

  async function markNotFound(source: string) {
    try {
      await booksApi.updateExternalUrl(bookId, source, null);
      externalMeta = await booksApi
        .getExternal(bookId)
        .catch(() => [] as ExternalMetadataOut[]);
      toastStore.success("Marked as not found");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function unlinkSource(source: string) {
    try {
      await booksApi.unlinkExternal(bookId, source);
      externalMeta = await booksApi
        .getExternal(bookId)
        .catch(() => [] as ExternalMetadataOut[]);
      toastStore.success("Source unlinked");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  // Sources with actual data (rating or URL) — shown inline
  let foundMeta = $derived(
    externalMeta.filter((m) => m.source_url != null || m.rating != null),
  );

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
    validationError = "";
  }

  async function saveExternalUrl() {
    if (!editingUrlSource) return;
    try {
      const id = editingUrlValue.trim();
      if (id) {
        const meta = SOURCE_META[editingUrlSource];
        if (meta && !meta.idPattern.test(id)) {
          validationError = `Invalid ID format. ${meta.idHint}`;
          return;
        }
        const prefix = meta?.urlPrefix ?? "";
        const fullUrl = prefix + id;
        await booksApi.updateExternalUrl(bookId, editingUrlSource, fullUrl);
      } else {
        await booksApi.updateExternalUrl(bookId, editingUrlSource, null);
      }
      externalMeta = await booksApi
        .getExternal(bookId)
        .catch(() => [] as ExternalMetadataOut[]);
      editingUrlSource = null;
      toastStore.success(
        id ? "Source URL updated, fetching metadata..." : "Source URL removed",
      );
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function getSourceMeta(source: string) {
    return (
      SOURCE_META[source] ?? {
        label: source,
        urlPrefix: "",
        idPattern: /^.+$/,
        idHint: "ID",
      }
    );
  }

  function getExternalUrl(
    source: string,
    sourceUrl: string | null,
  ): string | null {
    if (!sourceUrl) return null;
    if (sourceUrl.startsWith("http")) return sourceUrl;
    const prefix = SOURCE_META[source]?.urlPrefix ?? "";
    return prefix ? prefix + sourceUrl : null;
  }
</script>

{#snippet urlEditForm(source: string, currentUrl: string | null)}
  {@const src = getSourceMeta(source)}
  <div class="space-y-3">
    <p class="text-sm font-medium text-foreground">
      Link {src.label} page
    </p>
    <div class="flex items-center gap-1.5">
      <span class="text-xs text-muted-foreground whitespace-nowrap"
        >...{src.urlPrefix.slice(-12)}</span
      >
      <input
        bind:value={editingUrlValue}
        placeholder={src.idHint}
        class="flex-1 min-w-0 border border-input bg-background rounded-lg px-2.5 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
    </div>
    {#if validationError}
      <p class="text-xs text-red-600">{validationError}</p>
    {/if}
    <div class="flex justify-end gap-2">
      <button
        class="text-sm text-muted-foreground hover:text-foreground"
        onclick={() => (editingUrlSource = null)}>Cancel</button
      >
      <button
        class="text-sm bg-foreground text-background font-medium px-4 py-1.5 rounded-lg hover:bg-foreground/90 transition-colors"
        onclick={saveExternalUrl}>Save</button
      >
    </div>
  </div>
{/snippet}

{#if foundMeta.length > 0 || isAdmin}
  <div class="mt-4 flex flex-wrap items-center gap-4">
    <!-- Inline: only sources with data -->
    {#each foundMeta as meta}
      {@const src = getSourceMeta(meta.source)}
      {@const externalUrl = getExternalUrl(meta.source, meta.source_url)}
      <a
        href={externalUrl ?? "#"}
        target={externalUrl ? "_blank" : undefined}
        rel={externalUrl ? "noopener" : undefined}
        class="flex items-center gap-2 hover:opacity-80 transition-opacity"
        onclick={externalUrl
          ? undefined
          : (e: MouseEvent) => e.preventDefault()}
      >
        <span class="text-muted-foreground text-sm font-medium"
          >{src.label}</span
        >
        {#if meta.rating != null}
          <span class="text-lg font-bold text-foreground"
            >{meta.rating.toFixed(1)}</span
          >
        {:else}
          <span class="text-muted-foreground text-sm">-</span>
        {/if}
      </a>
    {/each}

    <!-- "+ Sources" popover for managing all sources -->
    {#if isAdmin}
      <Popover.Root
        bind:open={
          () => sourcesOpen,
          (v) => {
            sourcesOpen = v;
            if (!v) editingUrlSource = null;
          }
        }
      >
        <Popover.Trigger>
          <button
            class="flex items-center gap-1 text-muted-foreground/60 hover:text-muted-foreground text-sm transition-colors"
          >
            <Plus size={14} />
            Sources
          </button>
        </Popover.Trigger>
        <Popover.Content align="start" class="w-72">
          {#if editingUrlSource}
            {@const currentMeta = externalMeta.find(
              (m) => m.source === editingUrlSource,
            )}
            {@render urlEditForm(
              editingUrlSource,
              currentMeta?.source_url ?? null,
            )}
          {:else}
            <div class="space-y-1">
              <p class="text-sm font-medium text-foreground mb-3">
                Metadata sources
              </p>
              {#each Object.entries(SOURCE_META) as [key, src]}
                {@const meta = externalMeta.find((m) => m.source === key)}
                {@const externalUrl = meta
                  ? getExternalUrl(key, meta.source_url)
                  : null}
                {@const isEmptyMarker =
                  meta != null &&
                  meta.source_url == null &&
                  meta.rating == null}
                <div class="flex items-center justify-between py-1.5 text-sm">
                  <span class="text-foreground">{src.label}</span>
                  <div class="flex items-center gap-2">
                    {#if !meta}
                      <!-- Never fetched -->
                      <button
                        class="text-xs text-primary hover:text-primary/80 transition-colors"
                        onclick={() => startEditUrl(key, null)}
                      >
                        + Link
                      </button>
                    {:else if isEmptyMarker}
                      <!-- Searched but not found -->
                      <span
                        class="text-xs text-muted-foreground/60 bg-secondary/50 px-2 py-0.5 rounded"
                        >not found</span
                      >
                      <button
                        class="text-muted-foreground/50 hover:text-foreground transition-colors"
                        onclick={() => startEditUrl(key, null)}
                        title="Link manually"
                      >
                        <Pencil size={12} />
                      </button>
                      <button
                        class="text-muted-foreground/50 hover:text-foreground transition-colors"
                        onclick={() => unlinkSource(key)}
                        title="Unlink — allow re-search"
                      >
                        <Unlink size={12} />
                      </button>
                    {:else}
                      <!-- Has data -->
                      {#if meta.rating != null}
                        <a
                          href={externalUrl ?? "#"}
                          target="_blank"
                          rel="noopener"
                          class="font-bold text-foreground hover:opacity-80"
                          >{meta.rating.toFixed(1)}</a
                        >
                      {:else}
                        <span class="text-muted-foreground">-</span>
                      {/if}
                      <button
                        class="text-muted-foreground/50 hover:text-foreground transition-colors"
                        onclick={() =>
                          startEditUrl(key, meta?.source_url ?? null)}
                        title="Edit source URL"
                      >
                        <Pencil size={12} />
                      </button>
                      <button
                        class="text-muted-foreground/50 hover:text-foreground transition-colors"
                        onclick={() => markNotFound(key)}
                        title="Mark as not found"
                      >
                        <Ban size={12} />
                      </button>
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </Popover.Content>
      </Popover.Root>
    {/if}
  </div>
{/if}
