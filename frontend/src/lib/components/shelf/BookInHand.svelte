<script lang="ts">
  /**
   * The book taken down: a layer over the whole screen with the dim
   * room, the book itself (the engine draws it into `gl`), what is said
   * beside it while it is shut, and its two pages once it is open.
   *
   * The engine owns this layer: it places the caption and the pages over
   * the book, and says what state the book is in with the classes
   * `shown`, `inhand`, `opened` and `diving` on the layer (`center` on
   * the caption). The styles at the bottom answer to those.
   */
  import { onMount } from "svelte";
  import { Button } from "#lib/components/ui/button/index.ts";
  import type { BookOut, InteractionOut } from "#lib/types.ts";
  import * as m from "#lib/paraglide/messages.js";
  import { authorsOf, titleOf } from "./book";

  let {
    book,
    interaction,
    onopen,
    onshut,
    onputback,
    onstep,
    onread,
    ondetails,
  }: {
    book: BookOut | null;
    /** The reader's own record of it, once fetched. */
    interaction: InteractionOut | null;
    onopen: () => void;
    onshut: () => void;
    onputback: () => void;
    /** To the book before (-1) or after (1) on the shelf. */
    onstep: (by: -1 | 1) => void;
    onread: (id: string) => void;
    ondetails: (id: string) => void;
  } = $props();

  let stage: HTMLElement;
  let scrim: HTMLElement;
  let glHost: HTMLElement;
  let cap: HTMLElement;
  let left: HTMLElement;
  let right: HTMLElement;
  /** The layer's parts, for the engine. */
  export const elements = () => ({ stage, scrim, glHost, cap, left, right });

  // The whole screen: on the body, where nothing above it in the page
  // may clip or offset it.
  onMount(() => {
    document.body.append(stage);
    return () => stage.remove();
  });

  let year = $derived(
    (book?.published_date ?? book?.epub_published_date ?? "").slice(0, 4),
  );
  let format = $derived(book?.format?.toUpperCase() ?? "");
  // The description as plain words (it is often HTML).
  let blurb = $derived.by(() => {
    const raw = book?.description ?? book?.epub_description ?? "";
    if (!raw) return "";
    const doc = new DOMParser().parseFromString(raw, "text/html");
    return (doc.body.textContent ?? "").replace(/\s+/g, " ").trim();
  });
  let percent = $derived(
    Math.round(interaction?.reading_progress?.percentage ?? 0),
  );
  let reading = $derived(
    interaction?.reading_status === "currently_reading" ||
      (percent > 0 && percent < 100),
  );
  let finished = $derived(interaction?.reading_status === "read");
  let status = $derived(
    finished
      ? m.status_read()
      : reading
        ? `${m.status_reading()}${percent ? ` ${percent}%` : ""}`
        : "",
  );
  let readLabel = $derived(
    finished
      ? m.shelf_read_again()
      : reading
        ? m.book_continue_reading()
        : m.book_start_reading(),
  );
</script>

<!-- `dark`: one look in either theme, as the bookshelf behind it. -->
<div
  bind:this={stage}
  class="stage dark fixed inset-0 z-70 overflow-hidden text-foreground antialiased"
  hidden
  data-testid="bookshelf-stage"
>
  <!-- Past the edges: the layer steps back a little before a dive. -->
  <div
    bind:this={scrim}
    class="scrim absolute -inset-[8%] touch-none bg-[rgb(8_6_4/0.93)] opacity-0 transition-opacity duration-500"
  ></div>
  <div
    bind:this={glHost}
    class="[&>canvas]:pointer-events-none [&>canvas]:absolute [&>canvas]:inset-0 [&>canvas]:size-full"
  ></div>

  <div
    bind:this={cap}
    class="cap pointer-events-none absolute flex translate-y-2.5 flex-col gap-2.5 opacity-0 transition-[opacity,translate] duration-300"
  >
    {#if book}
      <div
        class="text-xs font-semibold tracking-[0.16em] text-muted-foreground tabular-nums"
      >
        {[format, year].filter(Boolean).join(" · ")}
      </div>
      <h2
        class="m-0 line-clamp-4 font-book text-[clamp(26px,4.4vw,48px)] leading-[1.22] font-black tracking-[0.03em] text-balance"
      >
        {titleOf(book)}
      </h2>
      <div class="text-[15px] tracking-[0.12em] text-muted-foreground">
        {authorsOf(book)}
      </div>
      {#if status}
        <div class="text-[13px] text-muted-foreground">{status}</div>
      {/if}
      <Button
        size="lg"
        class="openit mt-3 self-start rounded-full px-6 text-[15px] font-bold tracking-[0.08em]"
        onclick={onopen}
      >
        {m.shelf_open()} →
      </Button>
    {/if}
  </div>

  <!-- The open book's two pages. Every measure on them follows the book
       (`--pw`, its page's width; `--fs`, its type's size) and the colour
       of its cloth, all set by the engine: they are styled below, in the
       book's own terms. -->
  <div bind:this={left} class="pg pg-l">
    {#if book}
      <div class="sheet">
        <div class="it">{titleOf(book)}</div>
        <div class="ia">{authorsOf(book)}</div>
        <div class="rule"></div>
        <div class="from">{m.shelf_from()}</div>
        {#if year}<div class="no">{year}</div>{/if}
      </div>
    {/if}
  </div>
  <div bind:this={right} class="pg pg-r">
    {#if book}
      <div class="top">
        <span>{format}</span>
        <span>{year}</span>
      </div>
      <h2>{m.shelf_about()}</h2>
      <div class="rule"></div>
      <p class="blurb" class:missing={!blurb}>
        {blurb || m.shelf_no_description()}
      </p>
      <div class="foot">
        <button class="more" type="button" onclick={() => ondetails(book.id)}>
          {m.shelf_details()}
        </button>
        {#if book.file_size !== null}
          <button class="read" type="button" onclick={() => onread(book.id)}>
            {readLabel}
          </button>
        {/if}
      </div>
      <div class="num">{status}</div>
    {/if}
  </div>

  <div
    class="bar pointer-events-none absolute bottom-[calc(1.125rem+env(safe-area-inset-bottom,0px))] left-1/2 flex -translate-x-1/2 items-center gap-0.5 rounded-full border bg-card/90 p-1 whitespace-nowrap opacity-0 transition-opacity duration-300"
  >
    <Button
      variant="ghost"
      size="sm"
      class="rounded-full text-muted-foreground"
      onclick={() => onstep(-1)}
    >
      ‹ {m.shelf_prev()}
    </Button>
    <Button
      variant="ghost"
      size="sm"
      class="when-hand rounded-full font-bold"
      onclick={onputback}
    >
      {m.shelf_put_back()}
    </Button>
    <Button
      variant="ghost"
      size="sm"
      class="when-open rounded-full font-bold"
      onclick={onshut}
    >
      {m.shelf_shut()}
    </Button>
    <Button
      variant="ghost"
      size="sm"
      class="rounded-full text-muted-foreground"
      onclick={() => onstep(1)}
    >
      {m.shelf_next()} ›
    </Button>
  </div>
</div>

<style>
  /* ---- the states the engine sets ---- */
  .stage:global(.shown) .scrim {
    opacity: 1;
  }
  .stage:global(.inhand) .cap {
    opacity: 1;
    translate: 0 0;
    pointer-events: auto;
  }
  .cap:global(.center) {
    align-items: center;
    text-align: center;
  }
  .cap:global(.center) :global(.openit) {
    align-self: center;
  }
  .stage:global(.inhand) .bar,
  .stage:global(.opened) .bar {
    opacity: 1;
    pointer-events: auto;
  }
  .bar :global(.when-open),
  .stage:global(.opened) .bar :global(.when-hand) {
    display: none;
  }
  .stage:global(.opened) .bar :global(.when-open) {
    display: inline-flex;
  }
  /* Scaled about the page: nothing of it is cut off at the screen's edge. */
  .stage:global(.diving) {
    overflow: visible;
  }
  .stage:global(.diving) .bar {
    opacity: 0;
    pointer-events: none;
  }
  .stage:global(.diving) .pg {
    pointer-events: none;
  }

  /* ---- the pages ---- */
  .stage {
    --paper: #ece0c6;
    --paper-ink: #2c241b;
    --paper-muted: #8c7d68;
  }
  .pg {
    position: absolute;
    opacity: 0;
    transition: opacity 0.22s ease;
    pointer-events: none;
    color: var(--paper-ink);
    font-size: var(--fs);
    overflow: hidden;
  }
  .stage:global(.opened) .pg {
    opacity: 1;
    pointer-events: auto;
  }
  /* Left: the inside of the cover — its cloth showing round a pasted
     endpaper that carries the title. Right: the first page. */
  .pg-l {
    background: var(--cloth);
    border-radius: 3px 0 0 3px;
    padding: calc(var(--pw) * 0.028) 0 calc(var(--pw) * 0.028)
      calc(var(--pw) * 0.028);
  }
  .sheet {
    height: 100%;
    background:
      linear-gradient(270deg, rgba(70, 48, 24, 0.2), rgba(70, 48, 24, 0) 14%),
      var(--paper);
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    font-family: var(--font-book);
    padding: calc(var(--pw) * 0.1);
  }
  .it {
    margin-top: auto;
    font-size: 1.9em;
    font-weight: 900;
    line-height: 1.35;
    letter-spacing: 0.06em;
    text-wrap: balance;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    overflow: hidden;
  }
  .ia {
    margin-top: 0.7em;
    font-size: 0.92em;
    color: var(--paper-muted);
    letter-spacing: 0.2em;
  }
  .rule {
    width: 1.6em;
    height: 1px;
    background: var(--strong);
  }
  .pg-l .rule {
    margin-top: 1.5em;
  }
  .from {
    margin-top: auto;
    font-family: Georgia, "Times New Roman", var(--font-book);
    font-style: italic;
    font-size: 0.78em;
    color: var(--paper-muted);
  }
  .no {
    margin: 0.9em 0 0.4em;
    font-size: 0.62em;
    letter-spacing: 0.34em;
    color: var(--paper-muted);
    font-variant-numeric: tabular-nums;
  }
  .pg-r {
    background:
      linear-gradient(90deg, rgba(70, 48, 24, 0.2), rgba(70, 48, 24, 0) 14%),
      var(--paper);
    border-radius: 0 2px 2px 0;
    padding: calc(var(--pw) * 0.085) calc(var(--pw) * 0.12)
      calc(var(--pw) * 0.07) calc(var(--pw) * 0.12);
    display: flex;
    flex-direction: column;
    /* The edges of the pages under it. */
    box-shadow:
      1px 0 0 #d9cbae,
      2px 0 0 var(--paper),
      3px 0 0 #d9cbae,
      4px 0 0 var(--paper),
      5px 0 0 #cdbe9f;
  }
  .top {
    display: flex;
    justify-content: space-between;
    font-size: 0.62em;
    letter-spacing: 0.26em;
    color: var(--paper-muted);
    font-variant-numeric: tabular-nums;
  }
  .pg-r h2 {
    margin: 2.6em 0 0;
    font-family: var(--font-book);
    font-weight: 700;
    font-size: 1.18em;
    letter-spacing: 0.14em;
    color: inherit;
  }
  .pg-r .rule {
    margin: 1.1em 0 1.4em;
    width: 1.8em;
  }
  .blurb {
    font-family: var(--font-book);
    font-weight: 500;
    font-size: 0.9em;
    line-height: 2.05;
    margin: 0;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 8;
    line-clamp: 8;
    overflow: hidden;
    flex-shrink: 0;
  }
  .blurb.missing {
    color: var(--paper-muted);
  }
  .foot {
    margin-top: auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1em;
  }
  .more {
    font-size: 0.78em;
    letter-spacing: 0.08em;
    color: var(--paper-muted);
    white-space: nowrap;
    text-decoration: underline;
    text-underline-offset: 0.3em;
  }
  .read {
    font-size: 0.86em;
    font-weight: 700;
    letter-spacing: 0.08em;
    color: var(--on-strong);
    background: var(--strong);
    padding: 0.6em 1.3em;
    border-radius: 999px;
    white-space: nowrap;
  }
  .num {
    margin-top: 1.6em;
    text-align: center;
    font-family: var(--font-book);
    font-size: 0.66em;
    color: var(--paper-muted);
    font-variant-numeric: tabular-nums;
  }
</style>
