<script lang="ts">
  import { authStore } from "$lib/stores/auth";
  import { toastStore } from "$lib/stores/toast";
  import { booksApi } from "$lib/api/books";
  import type { BookOut } from "$lib/types";
  import { Dices, BookOpen, RotateCcw } from "@lucide/svelte";

  type Phase = "idle" | "loading" | "spinning" | "slowing" | "revealed";

  let phase = $state<Phase>("idle");
  let winnerBook = $state<BookOut | null>(null);
  let displayBook = $state<BookOut | null>(null);
  let allBooks = $state<BookOut[]>([]);
  let pulling = $state(false);

  function preloadCovers(books: BookOut[]): Promise<void> {
    const promises = books
      .filter((b) => b.cover_path)
      .map(
        (b) =>
          new Promise<void>((resolve) => {
            const img = new Image();
            img.onload = () => resolve();
            img.onerror = () => resolve();
            img.src = `/covers/${b.id}.jpg`;
          }),
      );
    return Promise.all(promises).then(() => {});
  }

  async function pull() {
    if (pulling) return;
    pulling = true;
    phase = "loading";
    winnerBook = null;
    displayBook = null;

    try {
      const books = await booksApi.getRandomBooks($authStore.token!, 8);
      if (books.length === 0) {
        toastStore.error("No books available");
        phase = "idle";
        pulling = false;
        return;
      }

      await preloadCovers(books);

      winnerBook = books[0];
      allBooks = books;

      if (books.length < 2) {
        displayBook = winnerBook;
        phase = "revealed";
        pulling = false;
        return;
      }

      // Phase 1: Fast cycling
      phase = "spinning";
      let index = 0;
      const decoys = books.slice(1);
      displayBook = decoys[0];

      const spinDuration = 1500;
      const spinInterval = 80;
      let elapsed = 0;

      const spinTimer = setInterval(() => {
        elapsed += spinInterval;
        index = (index + 1) % decoys.length;
        displayBook = decoys[index];
        if (elapsed >= spinDuration) {
          clearInterval(spinTimer);
          slowDown(decoys, index);
        }
      }, spinInterval);
    } catch (e) {
      toastStore.error((e as Error).message);
      phase = "idle";
      pulling = false;
    }
  }

  function slowDown(decoys: BookOut[], startIndex: number) {
    phase = "slowing";
    const delays = [120, 160, 200, 260, 340, 440, 560];
    let step = 0;
    let index = startIndex;

    function tick() {
      if (step < delays.length) {
        index = (index + 1) % decoys.length;
        displayBook = decoys[index];
        step++;
        setTimeout(tick, delays[step - 1]);
      } else {
        // Reveal the winner
        displayBook = winnerBook;
        phase = "revealed";
        pulling = false;
      }
    }
    tick();
  }

  function reset() {
    phase = "idle";
    winnerBook = null;
    displayBook = null;
    allBooks = [];
    pulling = false;
  }
</script>

<section class="mb-12">
  <div class="flex items-end justify-between mb-6">
    <div>
      <h2 class="text-2xl font-bold text-foreground">Feeling Lucky?</h2>
      <p class="text-muted-foreground text-sm mt-1">
        Pull a random book from your library
      </p>
    </div>
  </div>

  <div
    class="bg-card card-soft rounded-2xl p-6 sm:p-8 flex flex-col items-center"
  >
    <!-- Cover display area -->
    <div class="relative h-56 sm:h-64 aspect-[2/3] mb-6">
      {#if phase === "idle"}
        <!-- Mystery card -->
        <div
          class="w-full h-full bg-gradient-to-br from-primary/20 to-primary/5 rounded-lg border-2 border-dashed border-primary/30 flex flex-col items-center justify-center gap-3 transition-all duration-300 hover:border-primary/50 hover:from-primary/25"
        >
          <Dices class="text-primary/50" size={48} />
          <span class="text-primary/60 text-sm font-medium">???</span>
        </div>
      {:else if phase === "loading"}
        <!-- Loading covers -->
        <div
          class="w-full h-full bg-gradient-to-br from-primary/20 to-primary/5 rounded-lg border-2 border-dashed border-primary/30 flex flex-col items-center justify-center gap-3"
        >
          <div
            class="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-primary"
          ></div>
        </div>
      {:else if phase === "spinning" || phase === "slowing"}
        <!-- Cycling covers -->
        <div
          class="w-full h-full relative overflow-hidden rounded-lg"
          class:gacha-spinning={phase === "spinning"}
          class:gacha-slowing={phase === "slowing"}
        >
          {#if displayBook?.cover_path}
            <img
              src="/covers/{displayBook.id}.jpg"
              alt="cycling"
              class="w-full h-full object-cover rounded-lg"
            />
          {:else}
            <div
              class="w-full h-full bg-secondary rounded-lg flex items-center justify-center"
            >
              <BookOpen class="text-muted-foreground/30" size={36} />
            </div>
          {/if}
          <!-- Scan line overlay -->
          <div class="absolute inset-0 gacha-scanline rounded-lg"></div>
        </div>
      {:else if phase === "revealed" && displayBook}
        <!-- Revealed book -->
        <div class="w-full h-full gacha-reveal">
          <div class="relative w-full h-full gacha-glow">
            {#if displayBook.cover_path}
              <img
                src="/covers/{displayBook.id}.jpg"
                alt="{displayBook.display_title} cover"
                class="w-full h-full object-cover rounded-lg book-shadow"
              />
            {:else}
              <div
                class="w-full h-full bg-secondary rounded-lg flex flex-col items-center justify-center gap-2 p-4 book-shadow"
              >
                <BookOpen class="text-muted-foreground/30" size={36} />
                <span
                  class="text-muted-foreground/60 text-xs text-center line-clamp-3"
                  >{displayBook.display_title ?? "Untitled"}</span
                >
              </div>
            {/if}
          </div>
        </div>
      {/if}
    </div>

    <!-- Book info (revealed state) -->
    {#if phase === "revealed" && winnerBook}
      <div class="text-center mb-5 gacha-fade-in">
        <h3 class="font-semibold text-lg text-foreground line-clamp-2">
          {winnerBook.display_title ?? "Untitled"}
        </h3>
        <p class="text-muted-foreground text-sm mt-1 line-clamp-1">
          {(winnerBook.display_authors ?? []).join(", ") || "\u00A0"}
        </p>
      </div>
    {/if}

    <!-- Buttons -->
    <div class="flex items-center gap-3">
      {#if phase === "idle"}
        <button
          onclick={pull}
          class="px-6 py-3 bg-primary text-primary-foreground rounded-xl font-medium text-sm hover:bg-primary/90 transition-all duration-200 flex items-center gap-2 active:scale-95"
        >
          <Dices size={18} />
          抽書
        </button>
      {:else if phase === "loading" || phase === "spinning" || phase === "slowing"}
        <div
          class="px-6 py-3 text-muted-foreground text-sm font-medium flex items-center gap-2"
        >
          <div
            class="animate-spin rounded-full h-4 w-4 border-t-2 border-b-2 border-primary"
          ></div>
          抽取中...
        </div>
      {:else if phase === "revealed" && winnerBook}
        <a
          href="/books/{winnerBook.id}"
          class="px-6 py-3 bg-primary text-primary-foreground rounded-xl font-medium text-sm hover:bg-primary/90 transition-all duration-200 flex items-center gap-2 active:scale-95"
        >
          <BookOpen size={18} />
          去看看
        </a>
        <button
          onclick={() => {
            reset();
            pull();
          }}
          class="px-4 py-3 bg-secondary text-foreground rounded-xl font-medium text-sm hover:bg-secondary/80 transition-all duration-200 flex items-center gap-2 active:scale-95"
        >
          <RotateCcw size={16} />
          再抽一次
        </button>
      {/if}
    </div>
  </div>
</section>

<style>
  .gacha-spinning {
    animation: gacha-shake 0.08s linear infinite;
  }

  .gacha-slowing {
    animation: gacha-shake 0.15s linear infinite;
  }

  @keyframes gacha-shake {
    0% {
      transform: translateY(-1px);
    }
    50% {
      transform: translateY(1px);
    }
    100% {
      transform: translateY(-1px);
    }
  }

  .gacha-scanline {
    background: linear-gradient(
      to bottom,
      transparent 0%,
      transparent 48%,
      rgba(255, 255, 255, 0.08) 49%,
      rgba(255, 255, 255, 0.08) 51%,
      transparent 52%,
      transparent 100%
    );
    animation: scanline-move 0.4s linear infinite;
    pointer-events: none;
  }

  @keyframes scanline-move {
    0% {
      background-position: 0 -100%;
    }
    100% {
      background-position: 0 200%;
    }
  }

  .gacha-reveal {
    animation: gacha-pop 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
  }

  @keyframes gacha-pop {
    0% {
      transform: scale(0.9);
      opacity: 0.5;
    }
    50% {
      transform: scale(1.06);
    }
    100% {
      transform: scale(1);
      opacity: 1;
    }
  }

  .gacha-glow::after {
    content: "";
    position: absolute;
    inset: -30%;
    background: radial-gradient(
      circle,
      rgba(var(--primary-rgb, 99, 102, 241), 0.25) 0%,
      transparent 70%
    );
    animation: glow-fade 1s ease-out forwards;
    pointer-events: none;
    border-radius: 50%;
  }

  @keyframes glow-fade {
    0% {
      opacity: 1;
      transform: scale(0.3);
    }
    40% {
      opacity: 0.8;
      transform: scale(1);
    }
    100% {
      opacity: 0;
      transform: scale(1.3);
    }
  }

  .gacha-fade-in {
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
