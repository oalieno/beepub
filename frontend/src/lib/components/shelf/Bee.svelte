<script lang="ts">
  /**
   * The bee: the logo in three layers (body and the two wings, as the
   * launch animation has it), so the wings can beat. As wide as what it
   * is put in.
   */
  let { beat = "slow" }: { beat?: "fast" | "slow" | "still" } = $props();
</script>

<div class="bee {beat}">
  <img class="wing-r" src="/intro/bee-wing-r.webp" alt="" draggable="false" />
  <img src="/intro/bee-body.webp" alt="" draggable="false" />
  <img class="wing-l" src="/intro/bee-wing-l.webp" alt="" draggable="false" />
</div>

<style>
  /* The logo's own canvas (1046×1008): the three layers stack exactly. */
  .bee {
    position: relative;
    width: 100%;
    aspect-ratio: 1046 / 1008;
    user-select: none;
  }
  img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }
  .wing-l {
    transform-origin: 28.7% 43.7%;
    --to: -24deg;
  }
  .wing-r {
    transform-origin: 81% 43.7%;
    --to: 24deg;
  }
  @keyframes flap {
    to {
      transform: rotate(var(--to));
    }
  }
  .fast .wing-l,
  .fast .wing-r {
    animation: flap 60ms ease-in-out infinite alternate;
  }
  .slow .wing-l {
    --to: -14deg;
  }
  .slow .wing-r {
    --to: 14deg;
  }
  .slow .wing-l,
  .slow .wing-r {
    animation: flap 240ms ease-in-out infinite alternate;
  }
  @media (prefers-reduced-motion: reduce) {
    .wing-l,
    .wing-r {
      animation: none !important;
    }
  }
</style>
