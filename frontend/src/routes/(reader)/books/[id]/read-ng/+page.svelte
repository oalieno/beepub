<script lang="ts">
  /**
   * read-ng — the experimental route for the new reader engine (reader-ng
   * G0). Loads a book through BookReader and wraps it in a geometry
   * instrument panel: every slider is a layout input, and the readout
   * shows whether the anchor survived the resulting reflow. The panel is
   * a measuring device, not product UI; it goes before G1.
   */
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { booksApi } from "$lib/api/books";
  import { resolveReading } from "$lib/reading/resolve";
  import type { BookSource } from "$lib/reading/source";
  import type { Book, LayoutParams, Relocation } from "$lib/reader/core";
  import BookReader from "$lib/components/reader/BookReader.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Label } from "$lib/components/ui/label";
  import { Switch } from "$lib/components/ui/switch";
  import {
    ArrowLeft,
    ChevronLeft,
    ChevronRight,
    Moon,
    PanelTop,
    SlidersHorizontal,
    Sun,
    X,
  } from "@lucide/svelte";

  let bookId = $derived(page.params.id as string);
  let initialCfi = $derived(page.url.searchParams.get("cfi"));

  let source = $state<BookSource | null>(null);
  let title = $state("");
  let ready = $state(false);
  let rendered = $state(false);
  let loadError = $state<string | null>(null);
  let reader: BookReader | undefined = $state();
  let book = $state<Book | null>(null);

  // Instrument inputs. Defaults mirror the paginator's own except a single
  // column: BeePub reads single-column, spread none.
  // Query params seed the inputs so probes start from a known geometry
  // (?font=sans&size=20&lh=1.8&gap=7&margin=48&inline=720&cols=1&dark=1).
  const q = page.url.searchParams;
  const num = (key: string, fallback: number) => {
    const v = Number(q.get(key));
    return q.has(key) && Number.isFinite(v) ? v : fallback;
  };
  let fontFamily = $state<"serif" | "sans">(
    q.get("font") === "sans" ? "sans" : "serif",
  );
  let fontSize = $state(num("size", 18));
  let lineHeight = $state(num("lh", 1.8));
  let darkMode = $state(q.get("dark") === "1");
  let gap = $state(num("gap", 7));
  let margin = $state(num("margin", 48));
  let maxInlineSize = $state(num("inline", 720));
  let maxColumnCount = $state(num("cols", 1));
  // "Chrome" = an in-flow 48px header. Toggling it changes the container
  // height, the same geometry change hiding/pinning the top bar would make.
  let chromeBar = $state(true);
  let showPanel = $state(true);
  let jumpIndex = $state(0);
  let layout = $derived<LayoutParams>({
    gap,
    margin,
    maxInlineSize,
    maxColumnCount,
  });

  // Readout. The paginator re-derives position from its anchor after any
  // layout change (relocate reason "anchor"); the invariant under test is
  // that the previous visible-range start lies inside the new visible
  // range. Track it live so the owner sees ✓/✗ while dragging a slider.
  let loc = $state<Relocation | null>(null);
  let anchorRange: Range | null = null;
  let anchorCfi = $state<string | null>(null);
  let anchorHeld = $state<boolean | null>(null);
  let reflowCount = $state(0);

  function handleRelocate(r: Relocation) {
    loc = r;
    if (r.reason !== "anchor") {
      anchorRange = r.range?.cloneRange() ?? null;
      anchorCfi = r.cfi;
      anchorHeld = null;
      reflowCount = 0;
      return;
    }
    reflowCount += 1;
    const doc = r.range?.startContainer.ownerDocument;
    if (
      !anchorRange ||
      !r.range ||
      anchorRange.startContainer.ownerDocument !== doc
    ) {
      anchorHeld = null;
      return;
    }
    try {
      anchorHeld =
        r.range.comparePoint(
          anchorRange.startContainer,
          anchorRange.startOffset,
        ) === 0;
    } catch {
      anchorHeld = null;
    }
  }

  onMount(async () => {
    try {
      const resolved = await resolveReading(bookId);
      source = resolved.source;
      if (resolved.localEntry) {
        title = resolved.localEntry.title;
      } else {
        booksApi
          .get(bookId)
          .then((b) => {
            title = b.display_title ?? b.title ?? b.epub_title ?? "";
          })
          .catch(() => {});
      }
      ready = true;
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e);
    }
  });

  function shortCfi(cfi: string | null): string {
    if (!cfi) return "—";
    return cfi.length > 46 ? cfi.slice(0, 22) + "…" + cfi.slice(-22) : cfi;
  }
</script>

<svelte:head>
  <title>{title ? `${title} · read-ng` : "read-ng"}</title>
</svelte:head>

<div
  class="flex h-[100dvh] min-h-0 flex-col {darkMode
    ? 'reader-dark bg-ink-900'
    : 'reader-light bg-background'}"
>
  {#if chromeBar}
    <header
      class="flex h-12 shrink-0 items-center gap-1 border-b border-border px-2 text-foreground"
      data-testid="ng-chrome"
    >
      <Button
        variant="ghost"
        size="icon"
        href={`/books/${bookId}`}
        aria-label="Back"
      >
        <ArrowLeft />
      </Button>
      <div class="min-w-0 flex-1 truncate text-sm">{title}</div>
      {#if loc}
        <span class="text-xs text-muted-foreground tabular-nums">
          §{loc.index} · {Math.round(loc.fraction * 100)}%
        </span>
      {/if}
      <Button
        variant="ghost"
        size="icon"
        aria-label="Previous page"
        onclick={() => reader?.prev()}
      >
        <ChevronLeft />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Next page"
        onclick={() => reader?.next()}
      >
        <ChevronRight />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Toggle theme"
        onclick={() => (darkMode = !darkMode)}
      >
        {#if darkMode}<Sun />{:else}<Moon />{/if}
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Toggle panel"
        onclick={() => (showPanel = !showPanel)}
      >
        <SlidersHorizontal />
      </Button>
    </header>
  {/if}

  <div class="relative min-h-0 flex-1">
    {#if ready && source}
      <BookReader
        bind:this={reader}
        {bookId}
        {source}
        {initialCfi}
        {fontFamily}
        {fontSize}
        {lineHeight}
        {darkMode}
        {layout}
        onbook={(b) => (book = b)}
        onready={() => (rendered = true)}
        onerror={(e) => (loadError = e.message)}
        onrelocate={handleRelocate}
      />
    {/if}

    {#if !rendered && !loadError}
      <div
        class="pointer-events-none absolute inset-0 flex items-center justify-center"
      >
        <Spinner />
      </div>
    {/if}

    {#if loadError}
      <div
        class="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-background px-8 text-center text-foreground"
      >
        <p class="text-sm">The new reader could not open this book.</p>
        <pre
          class="max-w-full overflow-x-auto rounded-md bg-muted p-3 text-left text-xs">{loadError}</pre>
        <Button variant="outline" href={`/books/${bookId}/read`}
          >Open in the current reader</Button
        >
      </div>
    {/if}

    {#if !chromeBar}
      <Button
        variant="secondary"
        size="icon"
        class="absolute left-2 top-2 z-10 opacity-70"
        aria-label="Show header"
        onclick={() => (chromeBar = true)}
      >
        <PanelTop />
      </Button>
    {/if}
  </div>

  {#if showPanel}
    <aside
      class="fixed bottom-4 right-4 z-20 w-72 rounded-lg border border-border bg-card p-3 text-xs text-card-foreground shadow-lg"
      data-testid="ng-panel"
    >
      <div class="mb-2 flex items-center justify-between">
        <span class="font-medium">Geometry</span>
        <Button
          variant="ghost"
          size="icon"
          class="size-6"
          aria-label="Close panel"
          onclick={() => (showPanel = false)}
        >
          <X class="size-3.5" />
        </Button>
      </div>

      <!-- Native range inputs: the installed ui set has no slider, and this
           panel is torn out before G1. -->
      <div
        class="grid grid-cols-[5.5rem_1fr_3rem] items-center gap-x-2 gap-y-1.5"
      >
        <Label for="ng-gap">gap %</Label>
        <input
          id="ng-gap"
          type="range"
          min="0"
          max="20"
          step="0.5"
          bind:value={gap}
        />
        <span class="text-right tabular-nums">{gap}</span>

        <Label for="ng-margin">margin px</Label>
        <input
          id="ng-margin"
          type="range"
          min="0"
          max="120"
          step="4"
          bind:value={margin}
        />
        <span class="text-right tabular-nums">{margin}</span>

        <Label for="ng-size">font px</Label>
        <input
          id="ng-size"
          type="range"
          min="12"
          max="32"
          step="1"
          bind:value={fontSize}
        />
        <span class="text-right tabular-nums">{fontSize}</span>

        <Label for="ng-lh">line-height</Label>
        <input
          id="ng-lh"
          type="range"
          min="1.2"
          max="2.6"
          step="0.1"
          bind:value={lineHeight}
        />
        <span class="text-right tabular-nums">{lineHeight.toFixed(1)}</span>

        <Label for="ng-inline">max inline</Label>
        <input
          id="ng-inline"
          type="range"
          min="360"
          max="2000"
          step="20"
          bind:value={maxInlineSize}
        />
        <span class="text-right tabular-nums">{maxInlineSize}</span>

        <Label for="ng-cols">columns</Label>
        <input
          id="ng-cols"
          type="range"
          min="1"
          max="2"
          step="1"
          bind:value={maxColumnCount}
        />
        <span class="text-right tabular-nums">{maxColumnCount}</span>
      </div>

      <div class="mt-2 flex items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <Switch id="ng-chrome" bind:checked={chromeBar} />
          <Label for="ng-chrome">header (48px)</Label>
        </div>
        <div class="flex items-center gap-2">
          <Switch
            id="ng-sans"
            checked={fontFamily === "sans"}
            onCheckedChange={(v) => (fontFamily = v ? "sans" : "serif")}
          />
          <Label for="ng-sans">sans</Label>
        </div>
      </div>

      <div class="mt-2 flex items-center gap-2">
        <Label for="ng-jump">section</Label>
        <input
          id="ng-jump"
          type="number"
          min="0"
          max={book ? book.sections.length - 1 : 0}
          bind:value={jumpIndex}
          class="w-16 rounded-md border border-input bg-background px-1.5 py-0.5 tabular-nums"
        />
        <span class="text-muted-foreground"
          >/ {book ? book.sections.length - 1 : "—"}</span
        >
        <Button
          variant="outline"
          size="sm"
          class="ml-auto h-6 px-2 text-xs"
          onclick={() => reader?.goTo(jumpIndex)}
        >
          go
        </Button>
      </div>

      <dl
        class="mt-2 grid grid-cols-[5.5rem_1fr] gap-x-2 gap-y-0.5 border-t border-border pt-2 tabular-nums"
      >
        <dt class="text-muted-foreground">section</dt>
        <dd>{loc ? loc.index : "—"} {book?.dir ? `· ${book.dir}` : ""}</dd>
        <dt class="text-muted-foreground">fraction</dt>
        <dd>
          {loc ? loc.fraction.toFixed(3) : "—"}{loc?.size
            ? ` · page ${Math.round(loc.fraction / loc.size) + 1}/${Math.round(1 / loc.size)}`
            : ""}
        </dd>
        <dt class="text-muted-foreground">last reason</dt>
        <dd>{loc?.reason ?? "—"}</dd>
        <dt class="text-muted-foreground">anchor</dt>
        <dd class="truncate" title={anchorCfi ?? ""}>{shortCfi(anchorCfi)}</dd>
        <dt class="text-muted-foreground">visible start</dt>
        <dd class="truncate" title={loc?.cfi ?? ""}>
          {shortCfi(loc?.cfi ?? null)}
        </dd>
        <dt class="text-muted-foreground">reflows</dt>
        <dd>
          {reflowCount}
          {#if anchorHeld === true}<span class="text-primary"
              >· anchor held ✓</span
            >
          {:else if anchorHeld === false}<span class="text-destructive"
              >· anchor lost ✗</span
            >{/if}
        </dd>
      </dl>
    </aside>
  {/if}
</div>
