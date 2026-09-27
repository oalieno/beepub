<script lang="ts" module>
  export interface ContinueReadingItem {
    id: string;
    title: string;
    /** 0..100, or null when there is no position yet. */
    percentage: number | null;
    authors?: string[];
    /** A server cover (fetched with auth) or a ready-to-use src. */
    authedCover?: string | null;
    coverSrc?: string | null;
  }
</script>

<script lang="ts">
  /**
   * The horizontal "continue reading" row: tapping a book opens the
   * reader straight away — the one shortcut past the book page. Shared by
   * the home page (server books) and the device shelf (local books).
   */
  import { authedSrc } from "$lib/actions/authedSrc";
  import GeneratedCover from "$lib/components/GeneratedCover.svelte";
  import * as m from "$lib/paraglide/messages.js";

  let {
    items,
    seeAllHref,
  }: {
    items: ContinueReadingItem[];
    seeAllHref?: string;
  } = $props();
</script>

<section class="mb-12" data-testid="continue-reading">
  <div class="flex items-end justify-between mb-6">
    <div>
      <h2 class="text-2xl font-bold text-foreground">
        {m.home_continue_reading()}
      </h2>
      <p class="text-muted-foreground text-sm mt-1">
        {m.home_continue_reading_subtitle()}
      </p>
    </div>
    {#if seeAllHref}
      <a
        href={seeAllHref}
        class="text-primary hover:text-primary/80 text-sm font-medium"
        >{m.home_see_all()}</a
      >
    {/if}
  </div>
  <div
    class="flex gap-4 overflow-x-auto pb-2 snap-x snap-mandatory scrollbar-hide"
  >
    {#each items as item (item.id)}
      <a
        href="/books/{item.id}/read"
        class="shrink-0 snap-start w-[140px] sm:w-[160px] group"
      >
        <div
          class="aspect-[2/3] rounded-xl overflow-hidden bg-muted mb-2 relative"
        >
          {#if item.authedCover}
            <img
              use:authedSrc={item.authedCover}
              alt={item.title}
              class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
            />
          {:else if item.coverSrc}
            <img
              src={item.coverSrc}
              alt={item.title}
              class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
            />
          {:else}
            <!-- Same stand-in the shelf cards and book pages use. -->
            <GeneratedCover
              title={item.title}
              authors={item.authors ?? []}
              class="w-full h-full"
            />
          {/if}
          {#if item.percentage != null}
            <div
              class="absolute bottom-0 left-0 right-0 h-1 bg-muted-foreground/20"
            >
              <div
                class="h-full bg-primary transition-all"
                style="width: {Math.round(item.percentage)}%"
              ></div>
            </div>
          {/if}
        </div>
        <p
          class="text-sm font-medium text-foreground line-clamp-2 leading-tight group-hover:text-primary transition-colors"
        >
          {item.title}
        </p>
        {#if item.percentage != null}
          <p class="text-xs text-muted-foreground mt-0.5">
            {Math.round(item.percentage)}%
          </p>
        {/if}
      </a>
    {/each}
  </div>
</section>
