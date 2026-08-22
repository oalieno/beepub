<script lang="ts" module>
  import type { LocalBookEntry } from "$lib/services/localLibrary";
  import type { ReadingStatus } from "$lib/types";

  /** A shelf entry with its per-mount presentation state resolved. */
  export type LocalShelfEntry = LocalBookEntry & {
    coverSrc: string | null;
    linked: boolean;
    /** From the device reading records; absent on shelves that skip the
     *  extra Preferences reads. */
    progressPct?: number | null;
    readingStatus?: ReadingStatus | null;
    lastReadAt?: string | null;
  };
</script>

<script lang="ts">
  import { goto } from "$app/navigation";
  import {
    Bookmark,
    Check,
    Cloud,
    CloudUpload,
    EllipsisVertical,
    Loader2,
    Share,
    Trash2,
  } from "@lucide/svelte";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import GeneratedCover from "$lib/components/GeneratedCover.svelte";
  import * as m from "$lib/paraglide/messages.js";

  let {
    entry,
    ondelete,
    onupload,
    onexport,
    uploading = false,
  }: {
    entry: LocalShelfEntry;
    /** When absent the delete action is not rendered (read-only shelf). */
    ondelete?: (e: MouseEvent, entry: LocalShelfEntry) => void;
    /** Offered for unlinked books only; the page owns the gate (server
     *  configured, online, can_upload). */
    onupload?: (entry: LocalShelfEntry) => void;
    /** Share the EPUB file via the OS share sheet (native only). */
    onexport?: (entry: LocalShelfEntry) => void;
    uploading?: boolean;
  } = $props();

  let showUpload = $derived(!!onupload && !entry.linked);

  function formatSize(bytes: number): string {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
</script>

<div
  role="button"
  tabindex="0"
  class="text-left w-full group cursor-pointer"
  style="-webkit-tap-highlight-color: transparent;"
  onclick={() => goto(`/books/${entry.id}/read`)}
  onkeydown={(e) => e.key === "Enter" && goto(`/books/${entry.id}/read`)}
>
  <!-- Cover -->
  <div class="h-56 sm:h-64 mb-3 flex items-end justify-center">
    <div
      class="relative inline-flex book-shadow-hover transition-all duration-300"
    >
      {#if entry.coverSrc}
        <img
          src={entry.coverSrc}
          alt={entry.title}
          class="max-h-56 sm:max-h-64 w-auto max-w-full rounded-sm book-shadow"
          loading="lazy"
        />
      {:else}
        <GeneratedCover title={entry.title} class="h-56 sm:h-64 aspect-[2/3]" />
      {/if}
    </div>
  </div>

  <!-- Info below cover -->
  <div class="min-h-[3rem]">
    <h3
      class="font-medium text-sm line-clamp-2 leading-snug text-foreground group-hover:text-primary transition-colors"
    >
      {entry.title}
    </h3>
    <div class="flex items-center gap-1.5 mt-1 text-xs text-muted-foreground">
      <!-- Status line mirrors BookCard's semantics: reading → percentage,
           read → check; all in the info row (covers carry no badges). -->
      {#if entry.readingStatus === "read"}
        <span class="inline-flex items-center gap-1 text-primary font-medium">
          <Check size={12} strokeWidth={3} />{m.mybooks_tab_read()}
        </span>
      {:else if entry.readingStatus === "currently_reading"}
        <span>
          {#if entry.progressPct != null && entry.progressPct > 0}
            {Math.round(entry.progressPct)}%
          {:else}
            {m.mybooks_tab_reading()}
          {/if}
        </span>
      {:else if entry.readingStatus === "want_to_read"}
        <span class="inline-flex items-center gap-1">
          <Bookmark size={12} />{m.mybooks_tab_want_to_read()}
        </span>
      {:else if entry.readingStatus === "did_not_finish"}
        <span>{m.mybooks_tab_did_not_finish()}</span>
      {/if}
      <span>{formatSize(entry.fileSize)}</span>
      {#if entry.linked}
        <!-- Linked to a server book: reading state syncs -->
        <span title={m.local_linked_badge()}>
          <Cloud size={12} />
        </span>
      {/if}
      <!-- Actions live at the row's end, off the cover (owner's call) and
           collapsed into a menu — a bare trash can invites misclicks
           (audit J). Stop both events so the trigger doesn't open the
           book. -->
      {#if uploading}
        <span class="ml-auto -my-1 w-6 h-6 flex items-center justify-center">
          <Loader2 size={14} class="animate-spin" />
        </span>
      {:else if ondelete || showUpload || onexport}
        <DropdownMenu.Root>
          <DropdownMenu.Trigger
            aria-label={m.book_more_actions()}
            onclick={(e) => e.stopPropagation()}
            onkeydown={(e) => e.stopPropagation()}
            class="ml-auto -my-1 w-6 h-6 flex items-center justify-center rounded-full hover:bg-secondary hover:text-foreground can-hover:opacity-0 can-hover:group-hover:opacity-100 data-[state=open]:opacity-100 transition-all"
          >
            <EllipsisVertical size={14} />
          </DropdownMenu.Trigger>
          <DropdownMenu.Content align="end">
            {#if showUpload}
              <DropdownMenu.Item onclick={() => onupload?.(entry)}>
                <CloudUpload size={14} />
                {m.local_upload()}
              </DropdownMenu.Item>
            {/if}
            {#if onexport}
              <DropdownMenu.Item onclick={() => onexport?.(entry)}>
                <Share size={14} />
                {m.local_export()}
              </DropdownMenu.Item>
            {/if}
            {#if ondelete}
              {#if showUpload || onexport}
                <DropdownMenu.Separator />
              {/if}
              <DropdownMenu.Item
                variant="destructive"
                onclick={(e) => ondelete(e, entry)}
              >
                <Trash2 size={14} />
                {m.local_delete()}
              </DropdownMenu.Item>
            {/if}
          </DropdownMenu.Content>
        </DropdownMenu.Root>
      {/if}
    </div>
  </div>
</div>
