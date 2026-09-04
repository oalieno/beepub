<script lang="ts">
  /**
   * read-ng — the experimental route for the new reader engine (reader-ng
   * G0). Loads a book through BookReader and wraps it in a geometry
   * instrument panel: every slider is a layout input, and the readout
   * shows whether the anchor survived the resulting reflow. The panel is
   * a measuring device, not product UI; the settings sheet (G2) replaces it.
   * Highlights and progress are product-shaped already: the sidebar, the
   * share card, the percentage with its desktop scrubber, the peek pill,
   * the kosync offer, and the local-first sync triggers around a session.
   */
  import { onDestroy, onMount } from "svelte";
  import { browser } from "$app/environment";
  import { page } from "$app/state";
  import { booksApi } from "$lib/api/books";
  import { hasServerUrl, isLocalMode } from "$lib/api/client";
  import { resolveReading } from "$lib/reading/resolve";
  import type { BookSource } from "$lib/reading/source";
  import type { SyncBackend } from "$lib/reading/sync";
  import type { LocalBookEntry } from "$lib/services/localLibrary";
  import { getIsOnline } from "$lib/services/network";
  import type { HighlightOut } from "$lib/types";
  import { confirmDialog } from "$lib/stores/confirm";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";
  import type {
    Book,
    LayoutParams,
    PageTurnMode,
    Relocation,
  } from "$lib/reader/core";
  import BookReader from "$lib/components/reader/BookReader.svelte";
  import HighlightSidebar from "$lib/components/reader/HighlightSidebar.svelte";
  import ProgressScrubber from "$lib/components/reader/ProgressScrubber.svelte";
  import ShareHighlightModal from "$lib/components/ShareHighlightModal.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Label } from "$lib/components/ui/label";
  import { Switch } from "$lib/components/ui/switch";
  import {
    ArrowLeft,
    ChevronLeft,
    ChevronRight,
    Highlighter,
    Moon,
    PanelTop,
    SlidersHorizontal,
    Sun,
    Undo2,
    X,
  } from "@lucide/svelte";

  let bookId = $derived(page.params.id as string);
  let initialCfi = $derived(page.url.searchParams.get("cfi"));

  let source = $state<BookSource | null>(null);
  let sync = $state<SyncBackend | null>(null);
  let localEntry = $state<LocalBookEntry | null>(null);
  let isBeepub = $derived(sync?.kind === "beepub");
  let title = $state("");
  let authors = $state<string[]>([]);
  let sectionWeights = $state<number[] | null>(null);
  let ready = $state(false);
  let rendered = $state(false);
  let loadError = $state<string | null>(null);
  let reader: BookReader | undefined = $state();
  let book = $state<Book | null>(null);

  // Highlights: BookReader owns the list and the marks; the page shows
  // the sidebar and the share card.
  let highlights = $state<HighlightOut[]>([]);
  let brokenHighlightIds = $state<Set<string>>(new Set());
  let showHighlights = $state(false);
  let shareHighlight = $state<HighlightOut | null>(null);

  // Progress: the reader owns position and percentage; the page shows
  // them (header, desktop scrubber) and the peek pill's way back.
  let percentage = $state<number | null>(null);
  let isRtl = $state(false);
  let sectionTicks = $state<number[]>([]);
  let peekReturn = $state<{ percentage: number | null } | null>(null);
  const peekLabel = $derived(
    peekReturn
      ? peekReturn.percentage != null
        ? m.reader_peek_return_pct({
            percentage: Math.round(peekReturn.percentage),
          })
        : m.reader_peek_return()
      : null,
  );

  // Progress bridged from an e-reader (KOReader/Readest via kosync). The
  // reader auto-jumps when the book was never read here; otherwise the
  // jump is a real decision tied to opening the book, so it gets a dialog
  // (the KOReader/Readest convention), not a dismissable toast.
  async function handleKosyncPosition(detail: {
    percentage: number;
    device: string | null;
    sectionIndex: number | null;
    xpointer: string | null;
    autoJumped: boolean;
    localPercentage?: number;
  }) {
    const device = detail.device || "KOReader";
    const pct = Math.round(detail.percentage);
    if (detail.autoJumped) {
      toastStore.info(m.reader_kosync_jumped({ device, percentage: pct }));
      return;
    }
    const jump = await confirmDialog({
      title: m.reader_kosync_dialog_title(),
      description: m.reader_kosync_dialog_body({
        device,
        remote: pct,
        local: Math.round(detail.localPercentage ?? percentage ?? 0),
      }),
      confirmLabel: m.reader_kosync_jump(),
      cancelLabel: m.reader_kosync_dialog_stay(),
    });
    if (jump)
      void reader?.displayKosyncPosition(
        detail.percentage,
        detail.sectionIndex,
        detail.xpointer,
      );
  }

  async function deleteHighlight(hl: HighlightOut) {
    if (
      !(await confirmDialog({
        title: m.highlights_delete_confirm(),
        destructive: true,
      }))
    )
      return;
    try {
      await reader?.removeHighlight(hl);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

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
  const turnParam = q.get("turn");
  let pageTurn = $state<PageTurnMode>(
    turnParam === "animated" || turnParam === "follow" ? turnParam : "instant",
  );
  // "Chrome" = an in-flow 48px header. Toggling it changes the container
  // height, the same geometry change hiding/pinning the top bar would make.
  // It is an instrument only (the panel switch): a tap on the page must
  // NOT toggle it — an in-flow bar reflows the text on every tap (owner,
  // 09-04, on device). What a tap does to the chrome is the pin/chrome
  // design question, answered separately; BookReader's ontap stays
  // unwired here until then.
  let chromeBar = $state(true);
  let showPanel = $state(q.get("panel") !== "0");
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
      sync = resolved.sync;
      localEntry = resolved.localEntry;
      if (localEntry) {
        // Local imports carry their own display metadata; there is no
        // server record to fetch it from.
        title = localEntry.title;
        authors = localEntry.authors ?? [];
        sectionWeights = localEntry.sectionWeights ?? null;
        // Pull the linked server state first so the reader restores the
        // newest position — but bounded: past 2.5s the sync continues in
        // the background and this session opens with local state.
        if (!isLocalMode() && hasServerUrl() && getIsOnline()) {
          const { syncLocalBook } = await import("$lib/services/readingSync");
          await Promise.race([
            syncLocalBook(bookId).catch(() => {}),
            new Promise((resolve) => setTimeout(resolve, 2500)),
          ]);
          // Live-session adoption of the server ruler for entries the
          // sync backfill hasn't upgraded yet (persistence is doSync's
          // job); this only makes THIS session measure with real weights.
          if (localEntry.sectionWeights === undefined) {
            const { getLocalBookLinks } =
              await import("$lib/services/localLibrary");
            const serverBookId = (await getLocalBookLinks())[bookId] ?? null;
            if (serverBookId) {
              booksApi
                .get(serverBookId)
                .then((b) => {
                  if (b.section_weights && b.section_weights.length > 0)
                    sectionWeights = b.section_weights;
                })
                .catch(() => {});
            }
          }
        }
      } else {
        booksApi
          .get(bookId)
          .then((b) => {
            title = b.display_title ?? b.title ?? b.epub_title ?? "";
            authors = b.display_authors ?? b.authors ?? b.epub_authors ?? [];
            sectionWeights = b.section_weights ?? null;
          })
          .catch(() => {});
      }
      ready = true;
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e);
    }
  });

  onDestroy(() => {
    if (!browser || !localEntry) return;
    // Push this session's reading state. The delay sequences the sync
    // after the reader's final save (parent/child onDestroy ordering
    // isn't contractual).
    const id = bookId;
    const kind = sync?.kind;
    setTimeout(() => {
      void import("$lib/services/readingSync").then(({ syncLocalBook }) =>
        syncLocalBook(id).catch(() => {}),
      );
      // The session's reading time is final — ship the ledger window.
      void import("$lib/services/readingLedger").then(({ pushLedger }) =>
        pushLedger(),
      );
      // Closing the book shouldn't wait out the push throttle.
      if (kind === "kosync") {
        void import("$lib/reading/kosync").then(({ flushKosyncPushes }) =>
          flushKosyncPushes(),
        );
      }
    }, 600);
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
      class="flex min-h-12 shrink-0 items-center gap-1 border-b border-border px-2 text-foreground"
      style="padding-top: env(safe-area-inset-top, 0px);"
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
      {#if percentage != null}
        <span
          class="text-xs text-muted-foreground tabular-nums"
          data-testid="ng-percent"
        >
          {percentage}%
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
        aria-label={m.reader_highlights()}
        onclick={() => (showHighlights = true)}
      >
        <Highlighter />
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
    {#if ready && source && sync}
      <BookReader
        bind:this={reader}
        {bookId}
        {source}
        {sync}
        {initialCfi}
        {fontFamily}
        {fontSize}
        {lineHeight}
        {darkMode}
        {layout}
        {pageTurn}
        {sectionWeights}
        onbook={(b) => (book = b)}
        onready={() => (rendered = true)}
        onerror={(e) => (loadError = e.message)}
        onrelocate={handleRelocate}
        onhighlightschange={(list) => (highlights = list)}
        onbrokenhighlights={(ids) => (brokenHighlightIds = new Set(ids))}
        onshare={(hl) => (shareHighlight = hl)}
        onprogress={(p) => (percentage = p.percentage)}
        onactivity={() => {
          // beepub-kind saves carry track_activity — the server credits
          // the 'web' device row itself. Local/kosync books tick the
          // device ledger instead.
          if (!isBeepub)
            void import("$lib/services/readingLedger").then(({ tickReading }) =>
              tickReading(),
            );
        }}
        onticks={(t) => (sectionTicks = t)}
        ondirection={(rtl) => (isRtl = rtl)}
        onkosyncposition={handleKosyncPosition}
        onrestorefallback={(pct) =>
          toastStore.info(
            m.reader_restore_fallback({ percentage: Math.round(pct) }),
          )}
        onpeekchange={(peek) => (peekReturn = peek)}
      />
    {/if}

    <!-- Bottom progress (desktop; the header carries the number on
         phones). Collapsed: a hair-thin line at the bottom edge. Hovering
         the bottom strip (or an active peek, whose return link must be
         discoverable) expands the scrubber + info row as an overlay — no
         layout change, so the text never reflows. -->
    {#if rendered && percentage != null}
      <div
        class="hidden md:block absolute bottom-0 left-0 right-0 z-20 h-4 group"
        data-testid="ng-progress"
      >
        <div
          class="absolute bottom-0 left-0 right-0 h-[3px] overflow-hidden transition-opacity {peekLabel
            ? 'opacity-0'
            : 'group-hover:opacity-0'} {darkMode
            ? 'bg-ink-800'
            : 'bg-secondary'}"
        >
          <div
            class="h-full transition-[width] duration-300 {darkMode
              ? 'bg-ink-500'
              : 'bg-primary'} {isRtl ? 'ml-auto' : ''}"
            style="width: {percentage}%;"
          ></div>
        </div>
        <div
          class="absolute bottom-0 left-0 right-0 flex-col items-center gap-0 px-8 pb-3 pt-8 bg-gradient-to-t to-transparent {darkMode
            ? 'from-ink-900 via-ink-900/85'
            : 'from-white via-white/85'} {peekLabel
            ? 'flex'
            : 'hidden group-hover:flex'}"
        >
          <div class="w-full max-w-xl">
            <ProgressScrubber
              {percentage}
              {darkMode}
              {isRtl}
              ticks={sectionTicks}
              ariaLabel={m.reader_progress()}
              onseek={(p) => reader?.seekPercentage(p)}
            />
          </div>
          <div
            class="flex items-center gap-2.5 text-sm min-w-0 max-w-xl {darkMode
              ? 'text-ink-400'
              : 'text-muted-foreground'}"
          >
            <span class="shrink-0">{percentage}%</span>
            {#if peekLabel}
              <span class="opacity-50">·</span>
              <button
                type="button"
                class="flex items-center gap-1.5 underline underline-offset-4 text-primary transition-opacity hover:opacity-80"
                data-testid="ng-peek-return"
                onclick={() => reader?.returnFromPeek()}
              >
                <Undo2 size={14} />
                {peekLabel}
              </button>
            {/if}
          </div>
        </div>
      </div>
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
        class="absolute left-2 z-10 opacity-70"
        style="top: max(0.5rem, env(safe-area-inset-top, 0px));"
        aria-label="Show header"
        onclick={() => (chromeBar = true)}
      >
        <PanelTop />
      </Button>
    {/if}
  </div>

  {#if showHighlights}
    <HighlightSidebar
      {highlights}
      {bookId}
      {darkMode}
      brokenIds={brokenHighlightIds}
      onselect={(hl) => {
        showHighlights = false;
        void reader?.displayHighlight(hl);
      }}
      ondelete={deleteHighlight}
      onshare={(hl) => (shareHighlight = hl)}
      onclose={() => (showHighlights = false)}
    />
  {/if}

  <ShareHighlightModal
    open={shareHighlight !== null}
    highlight={shareHighlight}
    bookTitle={title}
    bookAuthors={authors}
    onclose={() => (shareHighlight = null)}
  />

  {#if showPanel}
    <aside
      class="fixed right-4 z-20 w-72 rounded-lg border border-border bg-card p-3 text-xs text-card-foreground shadow-lg"
      style="bottom: max(1rem, env(safe-area-inset-bottom, 0px));"
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
        <Label for="ng-turn">page turn</Label>
        <select
          id="ng-turn"
          bind:value={pageTurn}
          class="rounded-md border border-input bg-background px-1.5 py-0.5"
        >
          <option value="instant">instant</option>
          <option value="animated">animated</option>
          <option value="follow">follow finger</option>
        </select>
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
