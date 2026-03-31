<script lang="ts">
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import { Pencil } from "@lucide/svelte";
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
  > = {
    goodreads: {
      label: "Goodreads",
      urlPrefix: "https://www.goodreads.com/book/show/",
      idPattern: /^\d+[\w-]*$/,
      idHint: "e.g. 33017208",
    },
    readmoo: {
      label: "Readmoo",
      urlPrefix: "https://readmoo.com/book/",
      idPattern: /^\d+$/,
      idHint: "e.g. 210227953000101",
    },
  };

  let editingUrlSource = $state<string | null>(null);
  let editingUrlValue = $state("");
  let validationError = $state("");

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
</script>

{#if externalMeta.length > 0 || isAdmin}
  <div class="mt-4 flex flex-wrap items-center gap-4">
    {#each externalMeta as meta}
      {@const src = getSourceMeta(meta.source)}
      <div class="flex items-center gap-2">
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
          {#if meta.rating != null}
            <span class="text-lg font-bold text-foreground"
              >{meta.rating.toFixed(1)}</span
            >
          {:else}
            <span class="text-muted-foreground text-sm">-</span>
          {/if}
        </a>
        {#if isAdmin}
          <Popover.Root
            bind:open={
              () => editingUrlSource === meta.source,
              (v) => {
                if (v) startEditUrl(meta.source, meta.source_url);
                else editingUrlSource = null;
              }
            }
          >
            <Popover.Trigger>
              <button
                class="text-muted-foreground hover:text-foreground transition-colors"
                title="Edit source URL"
              >
                <Pencil size={12} />
              </button>
            </Popover.Trigger>
            <Popover.Content align="start" class="w-64">
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
            </Popover.Content>
          </Popover.Root>
        {/if}
      </div>
    {/each}
    {#if isAdmin}
      {@const existingSources = new Set(externalMeta.map((m) => m.source))}
      {#each Object.entries(SOURCE_META) as [key, src]}
        {#if !existingSources.has(key)}
          <Popover.Root
            bind:open={
              () => editingUrlSource === key,
              (v) => {
                if (v) startEditUrl(key, null);
                else editingUrlSource = null;
              }
            }
          >
            <Popover.Trigger>
              <button
                class="flex items-center gap-1 text-muted-foreground/50 hover:text-muted-foreground text-sm"
              >
                + {src.label}
              </button>
            </Popover.Trigger>
            <Popover.Content align="start" class="w-64">
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
            </Popover.Content>
          </Popover.Root>
        {/if}
      {/each}
    {/if}
  </div>
{/if}
