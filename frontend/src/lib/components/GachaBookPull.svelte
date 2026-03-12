<script lang="ts">
  import { authStore } from "$lib/stores/auth";
  import { toastStore } from "$lib/stores/toast";
  import { booksApi } from "$lib/api/books";
  import type { BookOut } from "$lib/types";
  import { BookOpen, RotateCcw } from "@lucide/svelte";

  type Phase = "idle" | "loading" | "tearing" | "revealed";

  let phase = $state<Phase>("idle");
  let book = $state<BookOut | null>(null);
  let pulling = $state(false);

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
      img.src = `/covers/${b.id}.jpg`;
    });
  }

  async function pull() {
    if (pulling) return;
    pulling = true;
    phase = "loading";
    book = null;

    try {
      const books = await booksApi.getRandomBooks($authStore.token!, 1);
      if (books.length === 0) {
        toastStore.error("No books available");
        phase = "idle";
        pulling = false;
        return;
      }

      book = books[0];
      await preloadCover(book);

      phase = "tearing";
      setTimeout(() => {
        phase = "revealed";
        pulling = false;
      }, 1800);
    } catch (e) {
      toastStore.error((e as Error).message);
      phase = "idle";
      pulling = false;
    }
  }

  function repull() {
    phase = "idle";
    book = null;
    pulling = false;
    tiltX = 0;
    tiltY = 0;
    isHovering = false;
  }

  function handleMouseMove(e: MouseEvent) {
    if (!cardEl) return;
    const rect = cardEl.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const centerX = rect.width / 2;
    const centerY = rect.height / 2;

    // Tilt: max 25 degrees
    tiltY = ((x - centerX) / centerX) * 25;
    tiltX = ((centerY - y) / centerY) * 25;

    // Shine position (percentage)
    shineX = (x / rect.width) * 100;
    shineY = (y / rect.height) * 100;
    isHovering = true;
  }

  function handleMouseLeave() {
    tiltX = 0;
    tiltY = 0;
    shineX = 50;
    shineY = 50;
    isHovering = false;
  }

  // Touch support for mobile
  function handleTouchStart(e: TouchEvent) {
    e.preventDefault();
    applyTouch(e.touches[0]);
  }

  function handleTouchMove(e: TouchEvent) {
    e.preventDefault();
    applyTouch(e.touches[0]);
  }

  function handleTouchEnd() {
    tiltX = 0;
    tiltY = 0;
    shineX = 50;
    shineY = 50;
    isHovering = false;
  }

  function applyTouch(touch: Touch) {
    if (!cardEl) return;
    const rect = cardEl.getBoundingClientRect();
    const x = touch.clientX - rect.left;
    const y = touch.clientY - rect.top;
    const centerX = rect.width / 2;
    const centerY = rect.height / 2;

    tiltY = ((x - centerX) / centerX) * 25;
    tiltX = ((centerY - y) / centerY) * 25;

    shineX = (x / rect.width) * 100;
    shineY = (y / rect.height) * 100;
    isHovering = true;
  }
</script>

<div class="flex flex-col items-center justify-center h-[calc(100dvh-4rem)] gap-8 overflow-hidden">
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
    {:else if phase === "loading"}
      <!-- Loading state with pack image -->
      <div class="relative w-full">
        <img
          src="/bookpack.png"
          alt="BeePub Book Pack"
          class="w-full h-auto"
          draggable="false"
        />
        <div
          class="absolute inset-0 flex items-center justify-center"
        >
          <div
            class="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-white"
          ></div>
        </div>
      </div>
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
        <!-- Book rising from inside -->
        {#if book}
          <div
            class="absolute inset-0 flex items-center justify-center pack-book-rise"
          >
            <div class="w-[70%] aspect-[2/3]">
              {#if book.cover_path}
                <img
                  src="/covers/{book.id}.jpg"
                  alt={book.display_title ?? "Book cover"}
                  class="w-full h-full object-cover rounded-lg book-shadow"
                />
              {:else}
                <div
                  class="w-full h-full bg-secondary rounded-lg flex flex-col items-center justify-center gap-2 p-4 book-shadow"
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
          </div>
        {/if}
      </div>
    {:else if phase === "revealed" && book}
      <!-- Revealed book — 3D tilt card -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="w-full aspect-[2/3] reveal-pop card-perspective"
        bind:this={cardEl}
        onmousemove={handleMouseMove}
        onmouseleave={handleMouseLeave}
        ontouchstart={handleTouchStart}
        ontouchmove={handleTouchMove}
        ontouchend={handleTouchEnd}
      >
        <div
          class="w-full h-full rounded-xl overflow-hidden card-tilt book-shadow"
          style="transform: rotateX({tiltX}deg) rotateY({tiltY}deg); transition: transform {isHovering
            ? '0.1s'
            : '0.4s'} ease-out;"
        >
          <div class="relative w-full h-full">
            {#if book.cover_path}
              <img
                src="/covers/{book.id}.jpg"
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
    {:else if phase === "loading" || phase === "tearing"}
      <div
        class="px-6 py-3 text-muted-foreground text-sm font-medium flex items-center gap-2"
      >
        {#if phase === "loading"}
          <div
            class="animate-spin rounded-full h-4 w-4 border-t-2 border-b-2 border-primary"
          ></div>
        {/if}
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
    animation: tear-top 1.2s cubic-bezier(0.22, 1, 0.36, 1) forwards;
    transform-origin: center top;
  }

  @keyframes tear-top {
    0% {
      transform: translateY(0) rotate(0deg);
      opacity: 1;
    }
    30% {
      transform: translateY(-8%) rotate(2deg);
      opacity: 1;
    }
    100% {
      transform: translateY(-60%) rotate(12deg);
      opacity: 0;
    }
  }

  /* Tear — body stays then fades */
  .pack-tear-body {
    clip-path: polygon(0 20%, 100% 18%, 100% 100%, 0 100%);
    animation: tear-body 1.6s ease-out forwards;
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
    animation: book-rise 1.6s cubic-bezier(0.22, 1, 0.36, 1) forwards;
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

  /* 3D card perspective container */
  .card-perspective {
    perspective: 800px;
    touch-action: none;
  }

  .card-tilt {
    transform-style: preserve-3d;
    will-change: transform;
  }

  /* Shine overlay */
  .card-shine {
    transition: opacity 0.3s ease;
  }

  /* Revealed pop */
  .reveal-pop {
    animation: reveal-pop 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
  }

  @keyframes reveal-pop {
    0% {
      transform: scale(0.9);
      opacity: 0.5;
    }
    50% {
      transform: scale(1.05);
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
