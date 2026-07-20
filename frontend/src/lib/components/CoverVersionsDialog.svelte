<script lang="ts" module>
  export interface CoverVersion {
    source: string;
    label: string;
    url: string;
  }
</script>

<script lang="ts">
  import Modal from "$lib/components/Modal.svelte";
  import MetadataVersionSearch from "$lib/components/MetadataVersionSearch.svelte";
  import * as m from "$lib/paraglide/messages.js";
  import { Upload } from "@lucide/svelte";
  import type { IsbnSourceResult } from "$lib/types";

  // The cover's version picker — same gesture as the field dialogs,
  // with thumbnails instead of text and a manual-upload escape hatch.
  let {
    open = false,
    onclose,
    currentSrc,
    versions,
    searchQuery = "",
    onPick,
    onUpload,
    onRecords,
  }: {
    open?: boolean;
    onclose: () => void;
    // What the page currently shows (staged pick included) — marked 目前.
    currentSrc: string | null;
    versions: CoverVersion[];
    searchQuery?: string;
    onPick: (version: CoverVersion) => void;
    onUpload: (file: File) => void;
    onRecords: (records: IsbnSourceResult[]) => void;
  } = $props();

  let fileInput = $state<HTMLInputElement | null>(null);

  function handleFileChange(event: Event) {
    const file = (event.currentTarget as HTMLInputElement).files?.[0];
    if (file) onUpload(file);
    if (fileInput) fileInput.value = "";
  }
</script>

<Modal title={m.metadata_field_cover()} {open} {onclose}>
  <div class="space-y-4">
    <div class="grid grid-cols-3 gap-3">
      {#each versions as version (version.source + version.url)}
        {@const isCurrent = version.url === currentSrc}
        <button
          type="button"
          class="group text-left"
          onclick={() => onPick(version)}
        >
          <div
            class="aspect-[2/3] overflow-hidden rounded-md border-2 transition-colors {isCurrent
              ? 'border-primary'
              : 'border-transparent group-hover:border-border'}"
          >
            <img
              src={version.url}
              alt={version.label}
              loading="lazy"
              class="h-full w-full object-cover"
            />
          </div>
          <p class="mt-1 truncate text-center text-xs text-muted-foreground">
            {version.label}
            {#if isCurrent}
              · {m.metadata_version_current()}
            {/if}
          </p>
        </button>
      {/each}

      <button
        type="button"
        class="flex aspect-[2/3] flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed border-border text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
        onclick={() => fileInput?.click()}
      >
        <Upload size={20} />
        <span class="px-2 text-center text-xs">{m.metadata_cover_upload()}</span
        >
      </button>
      <input
        bind:this={fileInput}
        type="file"
        accept="image/*"
        class="hidden"
        onchange={handleFileChange}
      />
    </div>

    <div class="border-t pt-4">
      <p class="mb-2 text-xs font-medium text-muted-foreground">
        {m.metadata_search_more()}
      </p>
      <MetadataVersionSearch initialQuery={searchQuery} {onRecords} />
    </div>
  </div>
</Modal>
