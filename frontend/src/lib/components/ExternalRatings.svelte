<script lang="ts">
  import { booksApi } from "$lib/api/books";
  import * as m from "$lib/paraglide/messages.js";
  import { toastStore } from "$lib/stores/toast";
  import { getMetadataSources } from "$lib/stores/metadataSources";
  import { onMount } from "svelte";
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

  type SourceMeta = {
    label: string;
    urlPrefix: string;
    idPattern: RegExp;
    idHint: string;
  };

  // Server-driven registry: only enabled, manually-linkable sources
  // (the ratings-bearing plugins declare url_prefix). Registry order.
  let sourceMeta = $state<Record<string, SourceMeta>>({});
  let linkableSources = $state<string[]>([]);
  let sourcesLoaded = $state(false);

  onMount(async () => {
    try {
      const registry = await getMetadataSources();
      const map: Record<string, SourceMeta> = {};
      const linkable: string[] = [];
      for (const source of registry) {
        if (!source.enabled || !source.url_prefix) continue;
        map[source.name] = {
          label: source.label,
          urlPrefix: source.url_prefix,
          idPattern: new RegExp(source.id_pattern ?? "^.+$"),
          idHint: source.id_hint ?? "ID",
        };
        linkable.push(source.name);
      }
      sourceMeta = map;
      linkableSources = linkable;
      sourcesLoaded = true;
    } catch {
      // Registry unavailable — inline ratings fall back to raw names.
    }
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
      toastStore.success(m.external_marked_not_found());
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
      toastStore.success(m.external_source_unlinked());
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  // Sources with actual data (rating or URL) — shown inline. Once the
  // registry is loaded, disabled/unknown sources are hidden (their rows
  // stay in the DB and reappear on re-enable).
  let foundMeta = $derived(
    externalMeta
      .filter((x) => x.source_url != null || x.rating != null)
      .filter((x) => !sourcesLoaded || x.source in sourceMeta),
  );

  function extractSourceId(source: string, url: string | null): string {
    if (!url) return "";
    const prefix = sourceMeta[source]?.urlPrefix ?? "";
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
        const meta = sourceMeta[editingUrlSource];
        if (meta && !meta.idPattern.test(id)) {
          validationError = m.external_invalid_id({ hint: meta.idHint });
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
        id ? m.external_url_updated() : m.external_url_removed(),
      );
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function getSourceMeta(source: string): SourceMeta {
    return (
      sourceMeta[source] ?? {
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
    const prefix = sourceMeta[source]?.urlPrefix ?? "";
    return prefix ? prefix + sourceUrl : null;
  }
</script>

{#snippet urlEditForm(source: string, currentUrl: string | null)}
  {@const src = getSourceMeta(source)}
  <div class="space-y-3">
    <p class="text-sm font-medium text-foreground">
      {m.external_link_source({ source: src.label })}
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
        onclick={() => (editingUrlSource = null)}>{m.common_cancel()}</button
      >
      <button
        class="text-sm bg-foreground text-background font-medium px-4 py-1.5 rounded-lg hover:bg-foreground/90 transition-colors"
        onclick={saveExternalUrl}>{m.common_save()}</button
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
    {#if isAdmin && linkableSources.length > 0}
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
            {m.external_sources_button()}
          </button>
        </Popover.Trigger>
        <Popover.Content align="start" class="w-72">
          {#if editingUrlSource}
            {@const currentMeta = externalMeta.find(
              (x) => x.source === editingUrlSource,
            )}
            {@render urlEditForm(
              editingUrlSource,
              currentMeta?.source_url ?? null,
            )}
          {:else}
            <div class="space-y-1">
              <p class="text-sm font-medium text-foreground mb-3">
                {m.external_metadata_sources()}
              </p>
              {#each linkableSources as key}
                {@const src = getSourceMeta(key)}
                {@const meta = externalMeta.find((x) => x.source === key)}
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
                        {m.external_link()}
                      </button>
                    {:else if isEmptyMarker}
                      <!-- Searched but not found -->
                      <span
                        class="text-xs text-muted-foreground/60 bg-secondary/50 px-2 py-0.5 rounded"
                        >{m.external_not_found()}</span
                      >
                      <button
                        class="text-muted-foreground/50 hover:text-foreground transition-colors"
                        onclick={() => startEditUrl(key, null)}
                        title={m.external_link_manually()}
                      >
                        <Pencil size={12} />
                      </button>
                      <button
                        class="text-muted-foreground/50 hover:text-foreground transition-colors"
                        onclick={() => unlinkSource(key)}
                        title={m.external_unlink()}
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
                        title={m.external_edit_url()}
                      >
                        <Pencil size={12} />
                      </button>
                      <button
                        class="text-muted-foreground/50 hover:text-foreground transition-colors"
                        onclick={() => markNotFound(key)}
                        title={m.external_mark_not_found()}
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
