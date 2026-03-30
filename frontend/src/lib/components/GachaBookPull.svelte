<script lang="ts">
  import { onMount } from "svelte";
  import { toastStore } from "$lib/stores/toast";
  import { booksApi } from "$lib/api/books";
  import { coverUrl } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import type { BookOut } from "$lib/types";
  import { BookOpen, RotateCcw } from "@lucide/svelte";

  type Phase = "idle" | "tearing" | "revealed";

  let phase = $state<Phase>("idle");
  let book = $state<BookOut | null>(null);
  let nextBook = $state<BookOut | null>(null);
  let pulling = $state(false);
  let ready = $state(false);

  // 3D tilt state
  let tiltX = $state(0);
  let tiltY = $state(0);
  let shineX = $state(50);
  let shineY = $state(50);
  let isHovering = $state(false);
  let cardEl: HTMLDivElement | undefined = $state();

  function preloadCover(b: BookOut): Promise<void> {
    if (!b.cover_path) return Promise.resolve();
    return new Promise<void>((resolve) => {
      const img = new Image();
      img.onload = () => resolve();
      img.onerror = () => resolve();
      img.src = coverUrl(b.id);
    });
  }

  async function prefetch() {
    try {
      const books = await booksApi.getRandomBooks(1);
      if (books.length === 0) {
        nextBook = null;
        return;
      }
      nextBook = books[0];
      await preloadCover(nextBook);
      ready = true;
    } catch {
      nextBook = null;
    }
  }

  onMount(() => {
    prefetch();
  });

  function pull() {
    if (pulling || !ready || !nextBook) return;
    pulling = true;
    book = nextBook;
    nextBook = null;
    ready = false;

    phase = "tearing";
    setTimeout(() => {
      phase = "revealed";
      pulling = false;
    }, 2600);

    // Prefetch next book in background
    prefetch();
  }

  function repull() {
    phase = "idle";
    book = null;
    pulling = false;
    tiltX = 0;
    tiltY = 0;
    isHovering = false;
  }

  function updateTilt(clientX: number, clientY: number) {
    if (!cardEl) return;
    const rect = cardEl.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    const centerX = rect.width / 2;
    const centerY = rect.height / 2;

    tiltY = ((x - centerX) / centerX) * 25;
    tiltX = ((centerY - y) / centerY) * 25;
    shineX = (x / rect.width) * 100;
    shineY = (y / rect.height) * 100;
    isHovering = true;
  }

  function resetTilt() {
    tiltX = 0;
    tiltY = 0;
    shineX = 50;
    shineY = 50;
    isHovering = false;
  }

  function handleMouseMove(e: MouseEvent) {
    updateTilt(e.clientX, e.clientY);
  }

  function handleTouchStart(e: TouchEvent) {
    e.preventDefault();
    updateTilt(e.touches[0].clientX, e.touches[0].clientY);
  }

  function handleTouchMove(e: TouchEvent) {
    e.preventDefault();
    updateTilt(e.touches[0].clientX, e.touches[0].clientY);
  }
</script>

<div
  class="flex flex-col items-center justify-center gap-8 overflow-hidden"
  style="height: calc(100dvh - 4rem - env(safe-area-inset-top, 0px));"
>
  <!-- Pack / Card area -->
  <div class="relative w-64 sm:w-80">
    {#if phase === "idle"}
      <!-- Card pack using bookpack.png -->
      <button class="w-full pack-idle cursor-pointer" onclick={pull}>
        <img
          src="/bookpack.png"
          alt="BeePub Book Pack"
          class="w-full h-auto drop-shadow-xl"
          draggable="false"
        />
      </button>
    {:else if phase === "tearing"}
      <!-- Tear animation — top cut -->
      <div class="relative w-full">
        <!-- Top strip (peels away) -->
        <div class="absolute inset-0 pack-tear-top overflow-hidden">
          <img
            src="/bookpack.png"
            alt=""
            class="w-full h-auto"
            draggable="false"
          />
        </div>
        <!-- Bottom body (stays then fades) -->
        <div class="absolute inset-0 pack-tear-body overflow-hidden">
          <img
            src="/bookpack.png"
            alt=""
            class="w-full h-auto"
            draggable="false"
          />
        </div>
        <!-- Invisible spacer to maintain height -->
        <img
          src="/bookpack.png"
          alt=""
          class="w-full h-auto invisible"
          draggable="false"
        />
        <!-- Book rising from inside (3D) -->
        {#if book}
          <div
            class="absolute inset-0 flex items-center justify-center pack-book-rise"
            style="perspective: 800px;"
          >
            <div class="w-[70%] aspect-[2/3] book-3d book-rise-tilt">
              <div class="book-face book-front">
                {#if book.cover_path}
                  <img
                    use:authedSrc={coverUrl(book.id)}
                    alt={book.display_title ?? "Book cover"}
                    class="w-full h-full object-cover"
                  />
                {:else}
                  <div
                    class="w-full h-full bg-secondary flex flex-col items-center justify-center gap-2 p-4"
                  >
                    <BookOpen class="text-muted-foreground/30" size={36} />
                    <span
                      class="text-muted-foreground/60 text-xs text-center line-clamp-3"
                    >
                      {book.display_title ?? "Untitled"}
                    </span>
                  </div>
                {/if}
              </div>

              <div class="book-face book-spine"></div>
              <div class="book-face book-pages-right"></div>
              <div class="book-face book-pages-top"></div>
              <div class="book-face book-pages-bottom"></div>
            </div>
          </div>
        {/if}
      </div>
    {:else if phase === "revealed" && book}
      <!-- Revealed book — 3D book -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="w-full aspect-[2/3] reveal-pop card-perspective"
        bind:this={cardEl}
        onmousemove={handleMouseMove}
        onmouseleave={resetTilt}
        ontouchstart={handleTouchStart}
        ontouchmove={handleTouchMove}
        ontouchend={resetTilt}
      >
        <div
          class="book-3d w-full h-full"
          style="transform: rotateX({tiltX}deg) rotateY({tiltY}deg); transition: transform {isHovering
            ? '0s'
            : '0.4s'} ease-out;"
        >
          <!-- Front cover -->
          <div class="book-face book-front">
            <div class="relative w-full h-full">
              {#if book.cover_path}
                <img
                  use:authedSrc={coverUrl(book.id)}
                  alt={book.display_title ?? "Book cover"}
                  class="w-full h-full object-cover"
                />
              {:else}
                <div
                  class="w-full h-full bg-secondary flex flex-col items-center justify-center gap-2 p-4"
                >
                  <BookOpen class="text-muted-foreground/30" size={36} />
                  <span
                    class="text-muted-foreground/60 text-xs text-center line-clamp-3"
                  >
                    {book.display_title ?? "Untitled"}
                  </span>
                </div>
              {/if}
              <!-- Shine/glare overlay -->
              <div
                class="absolute inset-0 pointer-events-none card-shine"
                style="background: radial-gradient(circle at {shineX}% {shineY}%, rgba(255,255,255,0.25) 0%, rgba(255,255,255,0.08) 30%, transparent 60%); opacity: {isHovering
                  ? 1
                  : 0};"
              ></div>
            </div>
          </div>
          <!-- Spine (left edge) -->
          <div class="book-face book-spine"></div>
          <!-- Page edges (right) -->
          <div class="book-face book-pages-right"></div>
          <!-- Page edges (top) -->
          <div class="book-face book-pages-top"></div>
          <!-- Page edges (bottom) -->
          <div class="book-face book-pages-bottom"></div>
        </div>
      </div>
    {/if}
  </div>

  <!-- Book info (revealed) -->
  {#if phase === "revealed" && book}
    <div class="text-center reveal-fade-in max-w-xs">
      <h3 class="font-semibold text-lg text-foreground line-clamp-2">
        {book.display_title ?? "Untitled"}
      </h3>
      <p class="text-muted-foreground text-sm mt-1 line-clamp-1">
        {(book.display_authors ?? []).join(", ") || "\u00A0"}
      </p>
    </div>
  {/if}

  <!-- Buttons -->
  <div class="flex items-center gap-3">
    {#if phase === "idle"}
      <div class="text-muted-foreground/50 text-sm">
        從你的書庫中隨機抽出一本書
      </div>
    {:else if phase === "tearing"}
      <div
        class="px-6 py-3 text-muted-foreground text-sm font-medium flex items-center gap-2"
      >
        開包中...
      </div>
    {:else if phase === "revealed" && book}
      <a
        href="/books/{book.id}"
        class="px-6 py-3 bg-primary text-primary-foreground rounded-xl font-medium text-sm hover:bg-primary/90 transition-all duration-200 flex items-center gap-2 active:scale-95"
      >
        <BookOpen size={18} />
        去看看
      </a>
      <button
        onclick={repull}
        class="px-4 py-3 bg-secondary text-foreground rounded-xl font-medium text-sm hover:bg-secondary/80 transition-all duration-200 flex items-center gap-2 active:scale-95"
      >
        <RotateCcw size={16} />
        再開一包
      </button>
    {/if}
  </div>
</div>

<style>
  /* Idle pack hover */
  .pack-idle {
    transition: transform 0.3s ease;
  }
  .pack-idle:hover {
    transform: scale(1.04) rotate(0.8deg);
  }
  .pack-idle:active {
    transform: scale(0.97);
  }

  /* Tear — top strip peels up and away */
  .pack-tear-top {
    clip-path: polygon(0 0, 100% 0, 100% 20%, 0 22%);
    animation: tear-top 1.8s cubic-bezier(0.22, 1, 0.36, 1) forwards;
    transform-origin: center top;
  }

  @keyframes tear-top {
    0% {
      transform: translateY(0) rotate(0deg);
      opacity: 1;
    }
    30% {
      transform: translateY(-5px) rotate(4deg);
      opacity: 1;
    }
    100% {
      transform: translateY(-60px) rotate(12deg);
      opacity: 0;
    }
  }

  /* Tear — body stays then fades */
  .pack-tear-body {
    clip-path: polygon(0 20%, 100% 18%, 100% 100%, 0 100%);
    animation: tear-body 2.4s ease-out forwards;
  }

  @keyframes tear-body {
    0% {
      opacity: 1;
      transform: translateY(0);
    }
    50% {
      opacity: 1;
      transform: translateY(0);
    }
    100% {
      opacity: 0;
      transform: translateY(8%);
    }
  }

  /* Book rising from pack */
  .pack-book-rise {
    animation: book-rise 2.4s cubic-bezier(0.22, 1, 0.36, 1) forwards;
  }

  @keyframes book-rise {
    0% {
      transform: translateY(40%) scale(0.7);
      opacity: 0;
    }
    25% {
      opacity: 0;
    }
    45% {
      opacity: 1;
    }
    100% {
      transform: translateY(0) scale(1);
      opacity: 1;
    }
  }

  /* 3D perspective container */
  .card-perspective {
    perspective: 800px;
    touch-action: none;
  }

  /* 3D book */
  .book-3d {
    --book-depth: 30px;
    transform-style: preserve-3d;
    position: relative;
  }

  .book-face {
    position: absolute;
  }

  /* Front cover — at z=0, thickness extends backward */
  .book-front {
    width: 100%;
    height: 100%;
  }

  /* Spine (left edge) — hinges on left, extends backward */
  .book-spine {
    width: var(--book-depth);
    height: 100%;
    left: 0;
    background: linear-gradient(to right, #3a3a3a, #2a2a2a);
    transform-origin: left center;
    transform: rotateY(90deg);
  }

  /* Page edges (right side) — hinges on right, extends backward */
  .book-pages-right {
    width: var(--book-depth);
    height: 100%;
    right: 0;
    background: repeating-linear-gradient(
      to bottom,
      #f5f0e8 0px,
      #f5f0e8 1px,
      #ebe6dc 1px,
      #ebe6dc 2px
    );
    transform-origin: right center;
    transform: rotateY(-90deg);
  }

  /* Page edges (top) — hinges on top, extends backward */
  .book-pages-top {
    width: 100%;
    height: var(--book-depth);
    top: 0;
    background: repeating-linear-gradient(
      to right,
      #f5f0e8 0px,
      #f5f0e8 1px,
      #ebe6dc 1px,
      #ebe6dc 2px
    );
    transform-origin: center top;
    transform: rotateX(-90deg);
  }

  /* Page edges (bottom) — hinges on bottom, extends backward */
  .book-pages-bottom {
    width: 100%;
    height: var(--book-depth);
    bottom: 0;
    background: repeating-linear-gradient(
      to right,
      #f5f0e8 0px,
      #f5f0e8 1px,
      #ebe6dc 1px,
      #ebe6dc 2px
    );
    transform-origin: center bottom;
    transform: rotateX(90deg);
  }

  /* Slight tilt during book rise for 3D effect */
  .book-rise-tilt {
    animation: book-rise-tilt 2.4s cubic-bezier(0.22, 1, 0.36, 1) forwards;
  }

  @keyframes book-rise-tilt {
    0% {
      transform: rotateY(-15deg) rotateX(5deg);
    }
    100% {
      transform: rotateY(-5deg) rotateX(2deg);
    }
  }

  /* Shine overlay */
  .card-shine {
    transition: opacity 0.3s ease;
  }

  /* Revealed pop */
  .reveal-pop {
    animation: reveal-pop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
  }

  @keyframes reveal-pop {
    0% {
      transform: scale(0.97);
      opacity: 0.8;
    }
    50% {
      transform: scale(1.03);
    }
    100% {
      transform: scale(1);
      opacity: 1;
    }
  }

  /* Fade in for book info */
  .reveal-fade-in {
    animation: fade-in 0.4s ease-out 0.2s both;
  }

  @keyframes fade-in {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
</style>
