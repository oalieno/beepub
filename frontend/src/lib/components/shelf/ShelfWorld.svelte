<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { browser } from "$app/environment";
  import { goto } from "$app/navigation";
  import { booksApi } from "$lib/api/books";
  import { coverUrl } from "$lib/api/client";
  import type { BookOut, InteractionOut } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";
  import type { Shelf, ShelfBook } from "./engine";
  import { iris, type Pool } from "./iris";
  import { authorOf, authorsOf, titleOf } from "./book";
  import BookInHand from "./BookInHand.svelte";
  import ShelfBar from "./ShelfBar.svelte";
  import { portal } from "./portal";
  import ShelfIntro from "./ShelfIntro.svelte";

  let {
    books = [],
    onend,
    onexit,
    query = "",
    onquery,
    placeholder = "",
    busy = false,
    empty = "",
    mark,
    disc,
  }: {
    /** The door's bee, and the pool of honey behind it: the ring opens
     *  out of that pool, and closes back into it. */
    mark: HTMLElement;
    disc: HTMLElement;
    books?: BookOut[];
    /** The end of the shelf is near: load more, if there are more. */
    onend?: () => void;
    /** Out of the bookshelf, back to the list. */
    onexit?: () => void;
    /** The list's search, shown here too. */
    query?: string;
    onquery?: (q: string) => void;
    placeholder?: string;
    /** The list is loading (a search under way). */
    busy?: boolean;
    /** What to say when there are no books. */
    empty?: string;
  } = $props();

  let world = $state<HTMLElement>(null!);
  // The door as it is on the screen: its bee, and the pool of honey
  // behind it — which is the ring that opens and closes.
  let beeBox = $state({ left: 0, top: 0, width: 150 });
  let at = $state({ x: 0, y: 0 });
  let pool = $state<Pool>({ radius: 0, color: "transparent" });
  function place() {
    const b = mark.getBoundingClientRect();
    beeBox = { left: b.left, top: b.top, width: b.width };
    const p = disc.getBoundingClientRect();
    at = { x: p.left + p.width / 2, y: p.top + p.height / 2 };
    pool = {
      radius: p.width / 2,
      color: getComputedStyle(disc).backgroundColor,
    };
    return at;
  }
  let host: HTMLElement;
  let hand: BookInHand;

  let shelf = $state<Shelf | null>(null);
  let failed = $state(false);
  // The book in hand.
  let heldIndex = $state<number | null>(null);
  let held = $derived(heldIndex === null ? null : (books[heldIndex] ?? null));
  let interaction = $state<InteractionOut | null>(null);

  let shelfBooks = $derived<ShelfBook[]>(
    books.map((b) => ({
      id: b.id,
      title: titleOf(b),
      author: authorOf(b),
      cover: b.cover_path ? coverUrl(b.id, b.updated_at) : null,
      words: b.word_count,
      series: b.display_series ?? b.series ?? b.epub_series ?? null,
    })),
  );

  // Back from reading a book taken from this shelf: the screen is held
  // (portal.ts) until that book is open in hand again, then it draws back
  // out of its page. Coming by the browser's own Back, nothing has
  // covered the screen yet: it is covered now, before the first paint.
  const here = () => location.pathname + location.search;
  let cameBack: string | null = null;
  if (browser) {
    const from = portal.origin;
    portal.origin = null;
    if (from && from.href === here()) {
      cameBack = from.id;
      if (!portal.covered) portal.snap();
    } else if (portal.covered) void portal.arrive();
  }
  const arriving = cameBack !== null;
  const calm =
    browser && matchMedia("(prefers-reduced-motion: reduce)").matches;
  // Coming in from the list: the bee, then a ring opening onto the shelf
  // (ShelfIntro). Back from a book, the way out of its page is the coming
  // in.
  let intro = $state(!arriving && !calm);
  let ready = $state(false);
  let returning = $state(cameBack);
  let leaving = $state(false);

  onMount(() => {
    // The bookshelf is the whole screen: on the body, where nothing above
    // it in the page may clip or offset it.
    place();
    document.body.append(world);
    // The book was not found on the shelf (the list came back different):
    // the shelf is shown as it is.
    const giveUp = setTimeout(() => {
      if (returning === null) return;
      returning = null;
      void portal.arrive();
    }, 4000);
    let gone = false;
    let made: Shelf | null = null;
    import("./engine").then(({ createShelf }) => {
      if (gone) return;
      made = createShelf(
        { host, ...hand.elements() },
        {
          held: (i) => {
            heldIndex = i;
            interaction = null;
            const id = i === null ? null : untrack(() => books[i]?.id);
            if (!id) return;
            booksApi
              .getInteraction(id)
              .then((it) => {
                if (untrack(() => held?.id) === id) interaction = it;
              })
              .catch(() => {});
          },
          end: () => onend?.(),
          failed: () => (failed = true),
        },
      );
      shelf = made;
    });
    // Books stand on the shelf (or there are none to stand).
    const t0 = performance.now();
    const look = setInterval(() => {
      const n = untrack(() => books.length);
      const drawn = Number(host.dataset.drawn ?? 0);
      if (
        failed ||
        (n > 0 && drawn >= Math.min(6, n)) ||
        (n === 0 && performance.now() - t0 > 1500)
      ) {
        ready = true;
        clearInterval(look);
      }
    }, 80);
    return () => {
      gone = true;
      clearInterval(look);
      clearTimeout(giveUp);
      made?.destroy();
      world.remove();
    };
  });

  $effect(() => {
    shelf?.setBooks(shelfBooks);
  });

  // The bee can be sent away, and that is remembered.
  const BEE_KEY = "shelf-bee";
  let beeOn = $state(recall(BEE_KEY) !== "off");
  function recall(key: string) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null; // storage is shut: nothing is remembered
    }
  }
  async function toggleBee() {
    beeOn = !beeOn;
    try {
      localStorage.setItem(BEE_KEY, beeOn ? "on" : "off");
    } catch {
      // not remembered, then
    }
    if (beeOn) return; // the effect below brings it in
    await shelf?.beeLeave();
    if (!beeOn) shelf?.beeHide();
  }
  // The ring has opened: the bee that went in through it is there.
  $effect(() => {
    if (shelf && !intro && beeOn) shelf.beeEnter(at.x, at.y);
  });

  $effect(() => {
    const id = returning;
    const s = shelf;
    if (id === null || !s) return;
    const i = books.findIndex((b) => b.id === id);
    if (i < 0) {
      if (books.length) {
        returning = null;
        void portal.arrive();
      }
      return;
    }
    returning = null;
    untrack(() => {
      s.surface(i, (at, tint) => void portal.surface(at, tint)).then((ok) => {
        if (!ok) void portal.arrive();
      });
    });
  });

  // Off to another page: the book goes back first (the layers go with
  // the component).
  function leave(path: string) {
    shelf?.close();
    goto(path);
  }

  // Reading: in through the page. The reader lifts the light when its
  // own page is ready (portal.arrive).
  let going = false;
  async function read(id: string) {
    const at = shelf?.focus();
    if (!shelf || !at || heldIndex === null) return leave(`/books/${id}/read`);
    if (going) return;
    going = true;
    portal.origin = { id, href: here() };
    await Promise.all([
      shelf.dive(),
      portal.dive(at, shelf.clothOf(heldIndex)),
    ]);
    await goto(`/books/${id}/read`);
    going = false;
  }

  // Out: the ring closes on the shelf, the list behind it.
  async function exit() {
    if (leaving || intro || heldIndex !== null) return;
    leaving = true;
    if (!calm) {
      const to = place();
      // The bee is off over the top; the ring closes behind it.
      void shelf?.beeLeave();
      await new Promise((r) => setTimeout(r, 220));
      await iris(world, false, 560, to, pool);
    }
    onexit?.();
  }
  function onkey(e: KeyboardEvent) {
    if (e.key !== "Escape" || heldIndex !== null || e.defaultPrevented) return;
    const t = e.target as HTMLElement | null;
    if (t?.closest?.("input")) return;
    exit();
  }
</script>

<svelte:document onkeydown={onkey} />

<!-- One look on purpose, in either theme (`dark`): a bookcase of dark
     wood lit by its own lamp. The ground is the colour the engine clears
     its picture to. Shut (`veiled`) until the ring opens on it: iris.ts
     sets the opening. -->
<div
  bind:this={world}
  class="dark fixed inset-0 z-60 bg-[#0e0a07] text-foreground"
  class:veiled={intro}
  data-testid="bookshelf-world"
>
  {#if failed}
    <p
      class="absolute inset-0 grid place-items-center p-6 text-center text-sm text-muted-foreground"
    >
      {m.shelf_no_webgl()}
    </p>
  {/if}

  <div
    bind:this={host}
    class="case absolute inset-0 touch-pan-x overflow-x-auto overflow-y-hidden overscroll-contain bg-[#0e0a07] leading-[0]"
    class:hidden={failed}
    data-testid="bookshelf"
  ></div>

  {#if !books.length && !busy && !failed && empty}
    <p
      class="pointer-events-none absolute inset-0 grid place-items-center px-6 text-center text-[17px] text-muted-foreground"
      data-testid="bookshelf-empty"
    >
      {empty}
    </p>
  {/if}

  <ShelfBar
    {query}
    {onquery}
    {placeholder}
    bee={beeOn}
    onbee={toggleBee}
    onback={exit}
  />

  <!-- The same books, for the keyboard and for screen readers. -->
  {#if beeOn}
    <button type="button" class="sr-only" onclick={() => shelf?.beePick()}>
      {m.shelf_bee_pick()}
    </button>
  {/if}
  <ul class="sr-only">
    {#each books as b, i (b.id)}
      <li>
        <button type="button" onclick={() => shelf?.open(i)}>
          {m.shelf_take({ title: titleOf(b), author: authorsOf(b) })}
        </button>
      </li>
    {/each}
  </ul>
</div>

{#if intro && world && pool.radius}
  <ShelfIntro
    target={world}
    bee={beeBox}
    {at}
    {pool}
    {ready}
    ondone={() => (intro = false)}
  />
{/if}

<BookInHand
  bind:this={hand}
  book={held}
  {interaction}
  onopen={() => shelf?.flip()}
  onshut={() => shelf?.shut()}
  onputback={() => shelf?.close()}
  onstep={(by) => shelf?.step(by)}
  onread={read}
  ondetails={(id) => leave(`/books/${id}`)}
/>

<style>
  .veiled {
    clip-path: circle(0px at 50% 50%);
  }
  .case {
    scrollbar-width: thin;
    scrollbar-color: #6b4f38 #0e0a07;
  }
</style>
