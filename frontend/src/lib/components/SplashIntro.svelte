<script lang="ts">
  /**
   * SplashIntro — the app's launch animation. The native launch screen is
   * plain cream (the same colour as this overlay), so the bee's first
   * appearance is this flight: it flaps up from below, settles with a
   * squash, and the name comes up letter by letter; then the overlay fades
   * off the app that has been loading underneath it.
   *
   * The bee is the logo itself, cut into three layers (body and the two
   * wings, the right one completed where the body hides it) so the wings
   * can beat. It never takes input: taps go straight through to the app.
   */
  import { onMount } from "svelte";

  let { ondone }: { ondone?: () => void } = $props();

  let root = $state<HTMLDivElement | null>(null);
  let fly = $state<HTMLDivElement | null>(null);
  let squash = $state<HTMLDivElement | null>(null);
  let wingL = $state<HTMLImageElement | null>(null);
  let wingR = $state<HTMLImageElement | null>(null);
  let word = $state<HTMLDivElement | null>(null);

  const BACK = "cubic-bezier(.34,1.56,.64,1)";
  const LAND = 560; // the bee stops
  const HOLD = 1500; // the whole mark is on screen
  const FADE = 320;

  onMount(() => {
    const running: Animation[] = [];
    const anim = (
      el: Element | null,
      frames: Keyframe[],
      opts: KeyframeAnimationOptions,
    ) => {
      if (el) running.push(el.animate(frames, { fill: "both", ...opts }));
    };
    const letters = word ? Array.from(word.children) : [];
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (reduced) {
      letters.forEach((l) => ((l as HTMLElement).style.opacity = "1"));
    } else {
      anim(
        fly,
        [
          {
            transform: "translate(-18px, 260px) rotate(-8deg)",
            opacity: 0,
            offset: 0,
          },
          {
            transform: "translate(14px, 90px) rotate(6deg)",
            opacity: 1,
            offset: 0.45,
          },
          { transform: "translate(-6px, -14px) rotate(-3deg)", offset: 0.8 },
          { transform: "translate(0, 0) rotate(0)", offset: 1 },
        ],
        { duration: 620, easing: "cubic-bezier(.3,.7,.4,1)" },
      );
      // Quick beats in flight, a lazy beat once it hovers.
      for (const [el, dir] of [
        [wingL, -1],
        [wingR, 1],
      ] as const) {
        anim(
          el,
          [
            { transform: "rotate(0deg)" },
            { transform: `rotate(${26 * dir}deg)` },
          ],
          {
            duration: 55,
            iterations: 12,
            direction: "alternate",
            easing: "ease-in-out",
            fill: "none",
          },
        );
        anim(
          el,
          [
            { transform: "rotate(0deg)" },
            { transform: `rotate(${14 * dir}deg)` },
          ],
          {
            duration: 240,
            delay: 660,
            iterations: Infinity,
            direction: "alternate",
            easing: "ease-in-out",
            fill: "none",
          },
        );
      }
      anim(
        squash,
        [
          { transform: "scale(1)", offset: 0 },
          { transform: "scale(1.08, .92)", offset: 0.3 },
          { transform: "scale(.97, 1.04)", offset: 0.65 },
          { transform: "scale(1)", offset: 1 },
        ],
        { duration: 420, delay: LAND, easing: "ease-out" },
      );
      letters.forEach((l, i) =>
        anim(
          l,
          [
            { opacity: 0, transform: "translateY(12px)" },
            { opacity: 1, transform: "translateY(0)" },
          ],
          { duration: 380, delay: LAND + 140 + i * 50, easing: BACK },
        ),
      );
    }

    const fadeAt = reduced ? 400 : HOLD;
    anim(root, [{ opacity: 1 }, { opacity: 0 }], {
      duration: FADE,
      delay: fadeAt,
      easing: "ease-in",
    });
    const done = setTimeout(() => ondone?.(), fadeAt + FADE);
    return () => {
      clearTimeout(done);
      running.forEach((a) => a.cancel());
    };
  });
</script>

<div
  bind:this={root}
  class="intro pointer-events-none fixed inset-0 z-[200] grid place-items-center"
  data-testid="splash-intro"
  aria-hidden="true"
>
  <div class="flex flex-col items-center">
    <div bind:this={fly} class="bee">
      <div bind:this={squash} class="bee squash">
        <img
          bind:this={wingR}
          class="wing-r"
          src="/intro/bee-wing-r.webp"
          alt=""
        />
        <img src="/intro/bee-body.webp" alt="" />
        <img
          bind:this={wingL}
          class="wing-l"
          src="/intro/bee-wing-l.webp"
          alt=""
        />
      </div>
    </div>
    <div bind:this={word} class="word">
      {#each "BeePub" as letter, i (i)}
        <span>{letter}</span>
      {/each}
    </div>
  </div>
</div>

<style>
  /* Always the launch screen's cream, whatever the app theme. */
  .intro {
    background: #faf7f2;
  }
  /* The logo's own canvas (1046×1008): the three layers stack exactly. */
  .bee {
    position: relative;
    width: min(42vw, 170px);
    aspect-ratio: 1046 / 1008;
  }
  .bee.squash {
    width: 100%;
    transform-origin: 50% 100%;
  }
  .bee img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }
  .wing-l {
    transform-origin: 28.7% 43.7%;
  }
  .wing-r {
    transform-origin: 81% 43.7%;
  }
  .word {
    display: flex;
    margin-top: 18px;
    font:
      700 clamp(32px, 10vw, 40px) / 1 "Playfair Display",
      Georgia,
      serif;
    color: #5c3a21;
  }
  .word span {
    display: inline-block;
    opacity: 0;
  }
</style>
