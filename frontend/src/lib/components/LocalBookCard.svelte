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
  import { BookOpen, Cloud, Trash2 } from "@lucide/svelte";
  import * as m from "$lib/paraglide/messages.js";

  let {
    entry,
    ondelete,
  }: {
    entry: LocalShelfEntry;
    /** When absent the delete overlay is not rendered (read-only shelf). */
    ondelete?: (e: MouseEvent, entry: LocalShelfEntry) => void;
  } = $props();

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

      <!-- Delete button overlay -->
      {#if ondelete}
        <button
          class="absolute top-2 right-2 p-1.5 rounded-full bg-black/50 text-white/80 hover:bg-destructive hover:text-white transition-all duration-200
            opacity-70 can-hover:opacity-0 can-hover:group-hover:opacity-100"
          style="-webkit-tap-highlight-color: transparent; touch-action: manipulation;"
          title={m.local_delete()}
          onclick={(e) => ondelete(e, entry)}
        >
          <Trash2 size={14} />
        </button>
      {/if}

      <!-- File size badge -->
      <span
        class="absolute bottom-1.5 left-1.5 text-[10px] font-medium bg-black/50 text-white/90 px-1.5 py-0.5 rounded-full"
      >
        {formatSize(entry.fileSize)}
      </span>

      {#if entry.linked}
        <!-- Linked to a server book: reading state syncs -->
        <span
          class="absolute bottom-1.5 right-1.5 bg-black/50 text-white/90 p-1 rounded-full"
          title={m.local_linked_badge()}
        >
          <Cloud size={12} />
        </span>
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
    {#if entry.authors?.length}
      <p class="text-muted-foreground text-xs mt-0.5 line-clamp-1">
        {entry.authors.join(", ")}
      </p>
    {/if}
  </div>
</div>
