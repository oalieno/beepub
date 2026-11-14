<script lang="ts">
  /**
   * The way into the bookshelf. The door stays as it is. The bee that
   * stood on it hovers there, wings fast, while the shelf is put
   * together behind; then it darts off into the pool of honey it stood
   * before, and that pool opens (iris.ts) — wider and wider, taking the
   * door with it — onto the shelf. The bee is waiting inside.
   */
  import { onMount } from "svelte";
  import Bee from "./Bee.svelte";
  import { iris, type Pool } from "./iris";

  let {
    target,
    bee,
    at,
    pool,
    ready,
    ondone,
  }: {
    /** The bookshelf's full-screen layer, held shut until the ring opens. */
    target: HTMLElement;
    /** The door's bee, on the screen: this one takes its place. */
    bee: { left: number; top: number; width: number };
    /** The middle of the pool behind it, and the pool: the ring. */
    at: { x: number; y: number };
    pool: Pool;
    /** The shelf has books standing on it. */
    ready: boolean;
    ondone: () => void;
  } = $props();

  let root: HTMLDivElement;
  let fly: HTMLDivElement;
  let bob: HTMLDivElement;

  const SETTLE = 520; // a moment of hovering, however ready the shelf is
  const PATIENCE = 4000; // the shelf is opened onto, ready or not
  let isReady = false;
  $effect(() => {
    isReady = ready;
  });

  onMount(() => {
    document.body.appendChild(root);
    const running: Animation[] = [];
    const anim = (
      el: Element,
      frames: Keyframe[],
      opts: KeyframeAnimationOptions,
    ) => {
      const a = el.animate(frames, { fill: "both", ...opts });
      running.push(a);
      return a;
    };
    let gone = false;
    const where = { ...at };
    anim(
      bob,
      [{ transform: "translateY(-4px)" }, { transform: "translateY(4px)" }],
      {
        duration: 620,
        iterations: Infinity,
        direction: "alternate",
        easing: "ease-in-out",
        fill: "none",
      },
    );

    const t0 = performance.now();
    const wait = setInterval(() => {
      const t = performance.now() - t0;
      if (t < SETTLE || (!isReady && t < PATIENCE)) return;
      clearInterval(wait);
      void open();
    }, 50);

    async function open() {
      // A breath back, then off into the pool — where the ring opens.
      const box = fly.getBoundingClientRect();
      const dx = where.x - (box.left + box.width / 2);
      const dy = where.y - (box.top + box.height / 2);
      anim(
        fly,
        [
          { transform: "translate(0, 0) scale(1)", opacity: 1, offset: 0 },
          {
            transform: "translate(0, 10px) scale(1.12)",
            opacity: 1,
            offset: 0.32,
          },
          {
            transform: `translate(${dx}px, ${dy}px) scale(0.08)`,
            opacity: 0,
            offset: 1,
          },
        ],
        { duration: 620, easing: "cubic-bezier(.5,0,.6,1)" },
      );
      await new Promise((r) => setTimeout(r, 330));
      if (gone) return;
      await iris(target, true, 1100, where, pool);
      if (!gone) ondone();
    }

    return () => {
      gone = true;
      clearInterval(wait);
      running.forEach((a) => a.cancel());
      root.remove();
    };
  });
</script>

<div
  bind:this={root}
  class="pointer-events-none fixed z-59"
  style="left:{bee.left}px;top:{bee.top}px;width:{bee.width}px"
  aria-hidden="true"
  data-testid="shelf-intro"
>
  <div bind:this={fly}>
    <div bind:this={bob}><Bee beat="fast" /></div>
  </div>
</div>
