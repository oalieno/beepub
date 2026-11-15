<script lang="ts">
  /**
   * The bookshelf view. In the page it is only its door: the bee, to be
   * clicked (choosing the view never goes in by itself). Through it the bookshelf is the whole screen (ShelfWorld);
   * leaving that comes back here.
   */
  import { browser } from "$app/environment";
  import type { BookOut } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";
  import Bee from "./Bee.svelte";
  import { portal } from "./portal";
  import ShelfWorld from "./ShelfWorld.svelte";

  let {
    books = [],
    onend,
    query = "",
    onquery,
    placeholder = "",
    busy = false,
    empty = "",
    oninside,
  }: {
    books?: BookOut[];
    /** The end of the shelf is near: load more, if there are more. */
    onend?: () => void;
    /** The list's search, shown inside too. */
    query?: string;
    onquery?: (q: string) => void;
    placeholder?: string;
    /** The list is loading (a search under way). */
    busy?: boolean;
    /** What to say inside when there are no books. */
    empty?: string;
    /** Told whenever the bookshelf is entered or left, so that the list
     *  keeps this mounted while inside. */
    oninside?: (inside: boolean) => void;
  } = $props();

  let mark = $state<HTMLElement>(null!);
  let disc = $state<HTMLElement>(null!);
  let comings = $state(0);
  let keen = $state(false); // the pointer is on the bee
  // Back from reading a book taken from this shelf: inside at once, where
  // that book is waiting open (ShelfWorld takes it from there).
  let inside = $state(
    browser && portal.origin?.href === location.pathname + location.search,
  );
  $effect(() => oninside?.(inside));

  // The door's height in the stylesheet is a guess at what the page's
  // head and the bars around it take. Here it is corrected by what is
  // measured: whatever the page still overflows by is taken off the
  // door, so the page has nothing to scroll.
  let door = $state<HTMLElement>(null!);
  function scrollerOf(el: HTMLElement): HTMLElement {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const o = getComputedStyle(p).overflowY;
      if (o === "auto" || o === "scroll") return p;
    }
    return (document.scrollingElement as HTMLElement) ?? document.body;
  }
  $effect(() => {
    if (!door) return;
    void books.length; // the list arriving can change what is above
    const scroller = scrollerOf(door);
    let frame = 0;
    const fit = () => {
      door.style.minHeight = "";
      const over = scroller.scrollHeight - scroller.clientHeight;
      if (over > 0)
        door.style.minHeight = `${Math.max(0, door.offsetHeight - over)}px`;
    };
    const later = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(fit);
    };
    later();
    addEventListener("resize", later);
    return () => {
      cancelAnimationFrame(frame);
      removeEventListener("resize", later);
    };
  });
</script>

<!-- The door. Everything on it is the bee's: its brown line, its honey,
     and nothing drawn that it did not do — the dashes are where it flew.
     What moves is the bee, not the ornament. -->
<!-- Its height is what the screen has left under the page's own head, so
     the page does not scroll: on a phone that head, the status bar and the
     tab bar at the foot take more of it. -->
<div
  bind:this={door}
  class="door flex flex-col items-center justify-center pt-3 pb-7 text-center"
  inert={inside}
  data-testid="bookshelf-door"
>
  <h2
    class="font-book text-[clamp(24px,5.6vw,50px)] leading-[1.15] font-black tracking-[0.08em] text-balance"
  >
    {m.shelf_enter()}
  </h2>

  <div class="plate">
    <!-- The ring: going in, this is what opens. -->
    <div bind:this={disc} class="disc" aria-hidden="true"></div>
    <!-- The way it came. -->
    <svg class="trail" viewBox="0 0 240 150" aria-hidden="true">
      <path
        d="M6 132C42 150 92 140 96 104C99 76 62 70 60 96C58 124 120 132 164 104C186 90 204 74 218 60"
      />
    </svg>
    <!-- The bee is the way in. Inside, it is in there, not here; each
         time the bookshelf is left it comes up again from below, as it
         first did. -->
    <button
      bind:this={mark}
      type="button"
      class="mark"
      class:gone={inside}
      onclick={() => (inside = true)}
      onpointerenter={() => (keen = true)}
      onpointerleave={() => (keen = false)}
      aria-label={m.shelf_enter()}
      data-testid="bookshelf-enter"
    >
      {#key comings}
        <div class="up">
          <div class="bob">
            <Bee beat={keen ? "fast" : "slow"} />
          </div>
        </div>
      {/key}
    </button>
    <div class="tap" aria-hidden="true">
      <span class="font-book">{m.shelf_tap_me()}</span>
      <svg viewBox="0 0 64 48">
        <path d="M58 6C40 3 17 11 9 36" />
        <path d="M9 36l1-13M9 36l12-6" />
      </svg>
    </div>
  </div>
</div>

{#if inside && mark && disc}
  <ShelfWorld
    {books}
    {onend}
    {query}
    {onquery}
    {placeholder}
    {busy}
    {empty}
    {mark}
    {disc}
    onexit={() => {
      inside = false;
      comings += 1;
    }}
  />
{/if}

<style>
  /* The bee's own colours (taken from the logo); on a dark page its
     line is drawn in its honey instead, to be seen. */
  .door {
    --brown: #5c3a21;
    --honey: #eab844;
    --line: var(--brown);
    --pool: color-mix(in srgb, var(--honey) 30%, var(--background));
    /* A spring: past the mark, and back. */
    --spring: linear(
      0,
      0.35 8%,
      0.87 20%,
      1.12 31%,
      1.17 38%,
      1.09 50%,
      0.99 66%,
      0.98 76%,
      1
    );
  }
  .door {
    min-height: max(
      260px,
      calc(
        100dvh - 320px - env(safe-area-inset-top, 0px) -
          env(safe-area-inset-bottom, 0px)
      )
    );
  }
  @media (min-width: 768px) {
    .door {
      min-height: max(420px, calc(100dvh - 300px));
    }
  }
  :global(.dark) .door {
    --line: var(--honey);
    --pool: color-mix(in srgb, var(--honey) 16%, var(--background));
  }
  /* All of it is measured by the bee. */
  .plate {
    --bee: min(34vw, 176px);
    position: relative;
    margin: calc(var(--bee) * 0.12) 0 calc(var(--bee) * 0.2);
  }
  /* A pool of honey behind it, set off to one side: its wing and its
     feelers stand out past the edge. */
  .disc {
    position: absolute;
    left: 50%;
    top: 50%;
    width: calc(var(--bee) * 0.98);
    aspect-ratio: 1;
    translate: -42% -43%;
    border-radius: 50%;
    background: var(--pool);
    transition: scale 0.5s var(--spring);
  }
  .plate:has(.mark:hover) .disc,
  .plate:has(.mark:focus-visible) .disc {
    scale: 1.05;
  }
  .trail {
    position: absolute;
    right: calc(50% + var(--bee) * 0.18);
    top: calc(var(--bee) * 0.42);
    width: calc(var(--bee) * 0.95);
    fill: none;
    stroke: var(--line);
    stroke-width: 3.2;
    stroke-linecap: round;
    stroke-dasharray: 0.1 11;
    opacity: 0.45;
    pointer-events: none;
    overflow: visible;
  }
  .mark {
    position: relative;
    display: block;
    width: var(--bee);
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }
  .mark:active {
    scale: 0.96;
  }
  .mark:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 6px;
    border-radius: 24px;
  }
  .mark.gone {
    visibility: hidden;
  }
  /* "Tap me", in the bee's own line. It stirs now and then, not always. */
  .tap {
    position: absolute;
    left: calc(50% + var(--bee) * 0.44);
    top: calc(var(--bee) * -0.04);
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    color: var(--line);
    pointer-events: none;
    animation: nudge 4.5s ease-in-out 1.6s infinite;
  }
  .tap span {
    font-weight: 900;
    font-size: clamp(15px, 2.6vw, 22px);
    letter-spacing: 0.08em;
    white-space: nowrap;
    rotate: -8deg;
    margin-left: 20px;
  }
  .tap svg {
    width: 56px;
    margin-top: 2px;
    fill: none;
    stroke: currentColor;
    stroke-width: 3.4;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .up {
    animation: up 0.64s cubic-bezier(0.3, 0.7, 0.4, 1) 0.1s both;
  }
  .bob {
    animation: bob 2.5s ease-in-out 0.76s infinite;
  }
  @keyframes nudge {
    0%,
    16%,
    100% {
      translate: 0 0;
    }
    5% {
      translate: -7px 6px;
    }
    10% {
      translate: 2px -2px;
    }
  }
  @keyframes up {
    0% {
      transform: translate(-18px, 200px) rotate(-8deg);
      opacity: 0;
    }
    45% {
      transform: translate(14px, 70px) rotate(6deg);
      opacity: 1;
    }
    80% {
      transform: translate(-6px, -12px) rotate(-3deg);
    }
    100% {
      transform: none;
    }
  }
  @keyframes bob {
    0%,
    100% {
      transform: none;
    }
    25% {
      transform: translateY(-5px);
    }
    75% {
      transform: translateY(5px);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .up,
    .bob,
    .tap {
      animation: none;
    }
  }
</style>
