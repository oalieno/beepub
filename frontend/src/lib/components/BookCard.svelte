<script lang="ts">
  import { goto } from "$app/navigation";
  import type { BookOut, BookWithInteractionOut } from "$lib/types";
  import {
    TriangleAlert,
    BookCopy,
    Bookmark,
    Check,
    HardDrive,
  } from "@lucide/svelte";
  import GeneratedCover from "$lib/components/GeneratedCover.svelte";
  import { coverUrl } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import { linkedServerBookIds } from "$lib/stores/linkedBooks";
  import * as m from "$lib/paraglide/messages.js";

  let { book }: { book: BookOut } = $props();

  // Covers are uncontrolled artwork — nothing gets stacked on them. All
  // semantic state lives in the info line below, where contrast is ours.
  // Interaction fields ride inline on list responses when the endpoint
  // provides them; plain BookOut lists simply render no status line.
  let interaction = $derived(book as Partial<BookWithInteractionOut>);
  let status = $derived(interaction.reading_status ?? null);
  let progress = $derived(interaction.reading_percentage ?? null);
</script>

<div
  role="button"
  tabindex="0"
  class="text-left w-full group cursor-pointer"
  style="-webkit-tap-highlight-color: transparent;"
  onclick={() => goto(`/books/${book.id}`)}
  onkeydown={(e) => e.key === "Enter" && goto(`/books/${book.id}`)}
>
  <!-- Cover -->
  <div
    class="aspect-[2/3] mb-3 flex items-end justify-center overflow-hidden rounded-sm"
  >
    {#if book.cover_path}
      <div
        class="relative inline-flex book-shadow-hover transition-all duration-300"
      >
        <img
          use:authedSrc={coverUrl(book.id, book.updated_at)}
          alt="{book.display_title} cover"
          class="w-full h-full object-cover rounded-sm book-shadow"
          loading="lazy"
        />
      </div>
    {:else}
      <div
        class="relative h-full book-shadow-hover transition-all duration-300"
      >
        <GeneratedCover
          title={book.display_title ?? m.common_untitled()}
          authors={book.display_authors ?? []}
          class="h-full aspect-[2/3]"
        />
      </div>
    {/if}
  </div>

  <!-- Info below cover — fixed height so grid rows align -->
  <div class="min-h-[3rem]">
    <h3
      class="font-medium text-sm line-clamp-2 leading-snug text-foreground group-hover:text-primary transition-colors"
    >
      {book.display_title ?? m.common_untitled()}
    </h3>
    {#if status || book.format === "physical" || book.has_unresolved_reports || $linkedServerBookIds.has(book.id)}
      <div class="flex items-center gap-1.5 mt-1 text-xs">
        {#if book.format === "physical"}
          <span class="text-muted-foreground" title={m.physical_badge()}>
            <BookCopy size={12} />
          </span>
        {/if}
        {#if status === "read"}
          <span class="inline-flex items-center gap-1 text-primary font-medium">
            <Check size={12} strokeWidth={3} />{m.mybooks_tab_read()}
          </span>
        {:else if status === "currently_reading"}
          <span class="text-muted-foreground">
            {#if progress != null && progress > 0}
              {Math.round(progress)}%
            {:else}
              {m.mybooks_tab_reading()}
            {/if}
          </span>
        {:else if status === "want_to_read"}
          <span class="inline-flex items-center gap-1 text-muted-foreground">
            <Bookmark size={12} />{m.mybooks_tab_want_to_read()}
          </span>
        {:else if status === "did_not_finish"}
          <span class="text-muted-foreground"
            >{m.mybooks_tab_did_not_finish()}</span
          >
        {/if}
        {#if book.has_unresolved_reports}
          <TriangleAlert size={12} class="text-destructive shrink-0" />
        {/if}
        {#if $linkedServerBookIds.has(book.id)}
          <!-- The mirror of the local shelf's cloud badge (native only:
               the set stays empty on web) -->
          <span class="text-muted-foreground" title={m.book_on_device()}>
            <HardDrive size={12} />
          </span>
        {/if}
      </div>
    {/if}
  </div>
</div>
