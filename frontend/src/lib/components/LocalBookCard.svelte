<script lang="ts" module>
  import type { LocalBookEntry } from "$lib/services/localLibrary";

  /** A shelf entry with its per-mount presentation state resolved. */
  export type LocalShelfEntry = LocalBookEntry & {
    coverSrc: string | null;
    linked: boolean;
  };
</script>

<script lang="ts">
  import { goto } from "$app/navigation";
  import {
    BookOpen,
    Cloud,
    CloudUpload,
    EllipsisVertical,
    Loader2,
    Trash2,
  } from "@lucide/svelte";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import * as m from "$lib/paraglide/messages.js";

  let {
    entry,
    ondelete,
    onupload,
    uploading = false,
  }: {
    entry: LocalShelfEntry;
    /** When absent the delete action is not rendered (read-only shelf). */
    ondelete?: (e: MouseEvent, entry: LocalShelfEntry) => void;
    /** Offered for unlinked books only; the page owns the gate (server
     *  configured, online, can_upload). */
    onupload?: (entry: LocalShelfEntry) => void;
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

      {#if uploading}
        <div
          class="absolute top-2 right-2 z-10 w-7 h-7 rounded-full bg-black/50 backdrop-blur-sm flex items-center justify-center text-white/80"
        >
          <Loader2 size={14} class="animate-spin" />
        </div>
      {:else if ondelete || showUpload}
        <!-- Actions collapsed into a menu — a bare trash can as the card's
             only visible action invites misclicks (audit J). Stop both
             events so the trigger doesn't also open the book. -->
        <DropdownMenu.Root>
          <DropdownMenu.Trigger
            aria-label={m.book_more_actions()}
            onclick={(e) => e.stopPropagation()}
            onkeydown={(e) => e.stopPropagation()}
            class="absolute top-2 right-2 z-10 w-7 h-7 rounded-full bg-black/50 backdrop-blur-sm flex items-center justify-center text-white/80 hover:text-white hover:bg-black/70 can-hover:opacity-0 can-hover:group-hover:opacity-100 data-[state=open]:opacity-100 transition-all"
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
            {#if ondelete}
              {#if showUpload}
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

  <!-- Info below cover -->
  <div class="min-h-[3rem]">
    <h3
      class="font-medium text-sm line-clamp-2 leading-snug text-foreground group-hover:text-primary transition-colors"
    >
      {entry.title}
    </h3>
    <div class="flex items-center gap-1.5 mt-1 text-xs text-muted-foreground">
      <span>{formatSize(entry.fileSize)}</span>
      {#if entry.linked}
        <!-- Linked to a server book: reading state syncs -->
        <span title={m.local_linked_badge()}>
          <Cloud size={12} />
        </span>
      {/if}
    </div>
  </div>
</div>
