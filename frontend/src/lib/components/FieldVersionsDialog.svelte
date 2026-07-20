<script lang="ts" module>
  export interface FieldVersion {
    key: string;
    // null = the EPUB original (picking it clears the override).
    source: string | null;
    label: string;
    value: string;
    url: string | null;
  }
</script>

<script lang="ts">
  import Modal from "$lib/components/Modal.svelte";
  import MetadataVersionSearch from "$lib/components/MetadataVersionSearch.svelte";
  import * as m from "$lib/paraglide/messages.js";
  import { ExternalLink } from "@lucide/svelte";
  import type { IsbnSourceResult } from "$lib/types";

  // One field's version picker: existing versions on top (EPUB original
  // + every source that has a value for this field), search below.
  // Clicking a version fills the field and closes — no confirm step.
  let {
    open = false,
    onclose,
    fieldLabel,
    currentValue,
    versions,
    multiline = false,
    searchQuery = "",
    onPick,
    onRecords,
  }: {
    open?: boolean;
    onclose: () => void;
    fieldLabel: string;
    currentValue: string;
    versions: FieldVersion[];
    multiline?: boolean;
    searchQuery?: string;
    onPick: (version: FieldVersion) => void;
    onRecords: (records: IsbnSourceResult[]) => void;
  } = $props();

  const currentIsUnlisted = $derived(
    currentValue !== "" && !versions.some((v) => v.value === currentValue),
  );
</script>

<Modal
  title={fieldLabel}
  {open}
  {onclose}
  contentClass={multiline ? "sm:max-w-2xl" : ""}
>
  <div class="space-y-4">
    <div class="space-y-2">
      {#if currentIsUnlisted}
        <!-- A hand-edited value matches no source — show it so "目前"
             always has an answer, but there's nothing to pick. -->
        <div class="rounded-lg border border-primary/40 bg-primary/5 p-3">
          <div class="mb-1 flex items-center gap-2">
            <span class="text-xs font-medium text-muted-foreground">
              {m.metadata_version_manual()}
            </span>
            <span
              class="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary"
            >
              {m.metadata_version_current()}
            </span>
          </div>
          <p
            class="text-sm text-foreground {multiline
              ? 'max-h-40 overflow-y-auto whitespace-pre-wrap'
              : 'truncate'}"
          >
            {currentValue}
          </p>
        </div>
      {/if}

      {#each versions as version (version.key)}
        {@const isCurrent = version.value === currentValue}
        <div class="relative">
          <button
            type="button"
            class="w-full rounded-lg border p-3 text-left transition-colors {isCurrent
              ? 'border-primary/40 bg-primary/5'
              : 'border-border hover:bg-secondary'}"
            onclick={() => onPick(version)}
          >
            <div class="mb-1 flex items-center gap-2 pr-6">
              <span class="text-xs font-medium text-muted-foreground">
                {version.label}
              </span>
              {#if isCurrent}
                <span
                  class="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary"
                >
                  {m.metadata_version_current()}
                </span>
              {/if}
            </div>
            <p
              class="text-sm text-foreground {multiline
                ? 'max-h-40 overflow-y-auto whitespace-pre-wrap'
                : 'truncate'}"
            >
              {version.value}
            </p>
          </button>
          {#if version.url}
            <a
              href={version.url}
              target="_blank"
              rel="noreferrer"
              class="absolute top-3 right-3 text-muted-foreground hover:text-primary"
              aria-label={version.label}
            >
              <ExternalLink size={12} />
            </a>
          {/if}
        </div>
      {/each}

      {#if versions.length === 0}
        <p class="py-2 text-center text-sm text-muted-foreground">
          {m.metadata_versions_none()}
        </p>
      {/if}
    </div>

    <div class="border-t pt-4">
      <p class="mb-2 text-xs font-medium text-muted-foreground">
        {m.metadata_search_more()}
      </p>
      <MetadataVersionSearch initialQuery={searchQuery} {onRecords} />
    </div>
  </div>
</Modal>
